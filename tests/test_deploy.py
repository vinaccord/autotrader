import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from autotrader.quant import report  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPT = os.path.join(ROOT, "deploy", "update_signed.sh")
HAVE = bool(shutil.which("ssh-keygen") and shutil.which("git"))


def run(cmd, cwd=None, env=None, check=True):
    e = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    e.update(env or {})
    r = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"{cmd}: {r.stdout}{r.stderr}")
    return r


class NotifyBodyTests(unittest.TestCase):
    TEXT = "Autotrader Tagesbericht 2026-10-07\nWARNUNGEN:\n  - Trend BTC Exposure 0.00 -> 0.85\n"

    def test_full_keeps_text(self):
        self.assertEqual(report.notify_body(self.TEXT, ["x"], "full"), self.TEXT)

    def test_short_hides_positions(self):
        b = report.notify_body(self.TEXT, ["Trend BTC Exposure 0.00 -> 0.85"], "short")
        self.assertIn("1 Warnung", b)
        self.assertNotIn("0.85", b)
        self.assertNotIn("BTC", b)

    def test_short_without_warnings(self):
        self.assertIn("Keine Warnungen", report.notify_body(self.TEXT, [], "short"))


@unittest.skipUnless(HAVE, "ssh-keygen und git noetig")
class SignedUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        t = self.tmp
        self.origin, self.work, self.src, self.app = (os.path.join(t, n) for n in ("origin.git", "work", "src", "app"))
        for d in (self.app,):
            os.makedirs(d)
        run(["git", "init", "-q", "--bare", self.origin])
        run(["git", "clone", "-q", self.origin, self.work])
        for k in ("good", "evil"):
            run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", os.path.join(t, k)])
        self.signers = os.path.join(t, "allowed_signers")
        with open(self.signers, "w") as f:
            f.write("release@autotrader " + open(os.path.join(t, "good.pub")).read())
        run(["git", "config", "user.email", "t@t"], cwd=self.work)
        run(["git", "config", "user.name", "t"], cwd=self.work)
        os.makedirs(os.path.join(self.work, "deploy"))
        with open(os.path.join(self.work, "deploy", "quant_daily.sh"), "w") as f:
            f.write("echo v1\n")
        run(["git", "add", "-A"], cwd=self.work)
        run(["git", "commit", "-q", "-m", "v1"], cwd=self.work)
        run(["git", "branch", "-M", "main"], cwd=self.work)
        run(["git", "push", "-q", "origin", "main"], cwd=self.work)
        run(["git", "clone", "-q", self.origin, self.src])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tag(self, name, key, content=None):
        if content is not None:
            with open(os.path.join(self.work, "deploy", "quant_daily.sh"), "w") as f:
                f.write(content)
            run(["git", "commit", "-q", "-am", name], cwd=self.work)
            run(["git", "push", "-q", "origin", "main"], cwd=self.work)
        run(["git", "-c", "gpg.format=ssh", "-c", f"user.signingkey={os.path.join(self.tmp, key)}.pub", "tag", "-s", name, "-m", name], cwd=self.work)
        run(["git", "push", "-q", "origin", name], cwd=self.work)

    def update(self, tag):
        env = {"SRC": self.src, "APP": self.app, "SIGNERS": self.signers, "AUTOTRADER_SKIP_SYSTEM": "1"}
        return run(["bash", SCRIPT, tag], env=env, check=False)

    def deployed(self):
        p = os.path.join(self.app, "deploy", "quant_daily.sh")
        return open(p).read() if os.path.exists(p) else None

    def test_valid_signed_tag_deploys(self):
        self.tag("v1", "good")
        r = self.update("v1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.deployed(), "echo v1\n")

    def test_tag_signed_with_other_key_is_refused(self):
        self.tag("v2", "evil", content="echo EVIL\n")
        r = self.update("v2")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIsNone(self.deployed())

    def test_unsigned_lightweight_tag_is_refused(self):
        run(["git", "tag", "v3"], cwd=self.work)
        run(["git", "push", "-q", "origin", "v3"], cwd=self.work)
        r = self.update("v3")
        self.assertEqual(r.returncode, 4)
        self.assertIsNone(self.deployed())

    def test_push_to_main_alone_does_not_deploy(self):
        self.tag("v1", "good")
        self.update("v1")
        with open(os.path.join(self.work, "deploy", "quant_daily.sh"), "w") as f:
            f.write("echo EVIL\n")
        run(["git", "commit", "-q", "-am", "evil"], cwd=self.work)
        run(["git", "push", "-q", "origin", "main"], cwd=self.work)
        r = self.update("v1")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.deployed(), "echo v1\n")

    def test_bad_tag_name_and_missing_signers(self):
        self.assertEqual(self.update("main").returncode, 2)
        self.assertEqual(self.update("").returncode, 2)
        os.remove(self.signers)
        self.tag("v1", "good")
        self.assertEqual(self.update("v1").returncode, 3)


if __name__ == "__main__":
    unittest.main()
