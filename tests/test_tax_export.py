import csv
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from autotrader.quant import tax_export as tx  # noqa: E402


def write(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


class TaxTests(unittest.TestCase):
    def setup(self, name, rows):
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "d"))
        with open(os.path.join(tmp, "q.yaml"), "w") as f:
            f.write("data_dir: d\n")
        write(os.path.join(tmp, "d", name), rows, ["ts", "date", "wallet", "asset", "side", "sz", "limit_px", "usd", "cloid", "status", "reason", "filled_sz", "avg_px", "oid"])
        return tmp

    def call(self, tmp, *extra):
        out = StringIO()
        with redirect_stdout(out):
            code = tx.main(["--config", os.path.join(tmp, "q.yaml"), "--plan", "/nonexistent", *extra])
        return code, out.getvalue()

    def test_live_only_filled_and_partial_deduped(self):
        base = {"date": "2026-12-02", "wallet": "A", "asset": "UBTC", "limit_px": "80000", "usd": "1", "reason": ""}
        rows = [dict(base, ts="2026-12-02T01:06:00Z", side="buy", sz="0.01", cloid="c1", status="filled", filled_sz="0.01", avg_px="80100"),
                dict(base, ts="2026-12-02T01:06:00Z", side="buy", sz="0.01", cloid="c1", status="filled", filled_sz="0.01", avg_px="80100"),
                dict(base, ts="2026-12-03T01:06:00Z", side="sell", sz="0.01", cloid="c2", status="partial", filled_sz="0.005", avg_px="81000"),
                dict(base, ts="2026-12-04T01:06:00Z", side="buy", sz="0.01", cloid="c3", status="rejected", filled_sz="", avg_px=""),
                dict(base, ts="2026-12-04T01:06:00Z", side="buy", sz="0.01", cloid="c4", status="blocked", filled_sz="", avg_px="")]
        tmp = self.setup("orders_live.csv", rows)
        code, out = self.call(tmp, "--source", "live")
        self.assertEqual(code, 0)
        with open(os.path.join(tmp, "d", "tax_trades_live.csv"), newline="", encoding="utf-8") as f:
            res = list(csv.DictReader(f))
        self.assertEqual([r["seite"] for r in res], ["Kauf", "Verkauf"])
        self.assertAlmostEqual(float(res[0]["wert_usd"]), 801.0)
        self.assertAlmostEqual(float(res[1]["menge"]), 0.005)
        self.assertEqual(res[0]["chf_kurs"], "")

    def test_dryrun_and_missing_source(self):
        rows = [{"ts": "2026-10-07T01:05:00Z", "date": "2026-10-06", "wallet": "A", "asset": "UBTC", "side": "buy", "sz": "0.1", "limit_px": "70000", "usd": "7000", "cloid": "x1", "status": "planned", "reason": ""}]
        tmp = self.setup("orders_dryrun.csv", rows)
        code, _ = self.call(tmp, "--source", "dryrun")
        self.assertEqual(code, 0)
        code2, out2 = self.call(tmp, "--source", "live")
        self.assertEqual(code2, 1)
        self.assertIn("nicht gefunden", out2)

    def test_source_file_untouched(self):
        rows = [{"ts": "t", "date": "d", "wallet": "A", "asset": "UBTC", "side": "buy", "sz": "0.1", "limit_px": "70000", "usd": "7000", "cloid": "x1", "status": "planned", "reason": ""}]
        tmp = self.setup("orders_dryrun.csv", rows)
        p = os.path.join(tmp, "d", "orders_dryrun.csv")
        before = open(p, "rb").read()
        self.call(tmp, "--source", "dryrun")
        self.assertEqual(open(p, "rb").read(), before)


if __name__ == "__main__":
    unittest.main()
