import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from autotrader.quant import paper_status as ps  # noqa: E402
from autotrader.quant.ledger import FIELDS  # noqa: E402
from autotrader.quant.hl_exec import LOG_FIELDS  # noqa: E402

START = dt.date(2026, 10, 6)


def utc(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc)


def block(ts, signal_date=None, equity=10000.0, ziel=(("BTC", 7000.0, "UBTC"), ("ETH", 0.0, "UETH")), failed=()):
    out = [f"=== {ts} ==="]
    for f in failed:
        out += [f"--- {f} ---", f"!!! Schritt fehlgeschlagen: {f}"]
    if failed:
        out.append(f"FEHLER in: {' '.join(failed)}")
    if signal_date:
        out.append(f"Trockenlauf Wallet A, Signal {signal_date}, Kontowert {equity:,.2f} USD (Papier)")
        out.append("Kill-Switch: normal (Verlust ab Hoechststand 0.0%, Exposure x1.0)")
        for c, usd, tok in ziel:
            out.append(f"  Ziel {c}: Exposure 1.00 -> {usd:,.0f} USD {tok}")
    return "\n".join(out)


def ledger_rows(dates, coins=("BTC", "ETH"), realised=True, profile="quant_40"):
    rows = []
    for i, d in enumerate(dates):
        for c in coins:
            rows.append({"profile": profile, "kind": "signal", "date": d, "coin": c, "close": "70000" if c == "BTC" else "2400"})
            if realised and i < len(dates) - 1:
                rows.append({"profile": profile, "kind": "realised", "date": d, "coin": c, "close": "70000"})
    return rows


class ParseTests(unittest.TestCase):
    def test_runs_failed_and_clean(self):
        t = "\n".join([block("2026-10-07T01:05:10Z"), block("2026-10-08T01:05:15Z", failed=["Daten"])])
        runs = ps.parse_runs(t)
        self.assertEqual(len(runs), 2)
        self.assertTrue(runs[0]["clean"])
        self.assertFalse(runs[1]["clean"])
        self.assertEqual(runs[1]["failed"], ["Daten"])

    def test_makro_hinweis_ist_kein_fehler(self):
        t = block("2026-10-07T01:05:10Z") + "\nMakro-Abruf fehlgeschlagen (nicht kritisch)"
        self.assertTrue(ps.parse_runs(t)[0]["clean"])


class CriterionATests(unittest.TestCase):
    def run_a(self, text, now, ledger=None, **kw):
        return ps.evaluate_a(ps.parse_runs(text), ledger, START, utc(now), **kw)

    def test_all_days_ok(self):
        t = "\n".join(block(f"2026-10-0{d}T01:05:00Z") for d in (6, 7, 8, 9))
        r = self.run_a(t, "2026-10-09T12:00:00")
        self.assertEqual(r["missed"], [])
        self.assertFalse(r["violated"])
        self.assertTrue(r["verdict"].startswith("laeuft"))

    def test_two_runs_same_day_and_manual_runs_count_once(self):
        t = "\n".join([block("2026-10-06T12:43:42Z"), block("2026-10-06T13:07:51Z"), block("2026-10-07T01:05:10Z"), block("2026-10-07T06:51:17Z")])
        r = self.run_a(t, "2026-10-07T12:00:00")
        self.assertEqual(r["clean_days"], 2)
        self.assertEqual(r["missed"], [])

    def test_one_missed_day_allowed_two_violate(self):
        # 8.10. fehlt
        t = "\n".join(block(f"2026-10-{d:02d}T01:05:00Z") for d in (6, 7, 9, 10))
        r = self.run_a(t, "2026-10-10T12:00:00")
        self.assertEqual(r["missed"], [dt.date(2026, 10, 8)])
        self.assertFalse(r["violated"])
        t2 = "\n".join(block(f"2026-10-{d:02d}T01:05:00Z") for d in (6, 7, 10, 11))
        r2 = self.run_a(t2, "2026-10-11T12:00:00")
        self.assertEqual(len(r2["missed"]), 2)
        self.assertTrue(r2["violated"])
        self.assertEqual(r2["verdict"], "VERLETZT")

    def test_day_with_only_failed_run_counts_as_missed(self):
        t = "\n".join([block("2026-10-06T12:00:00Z"), block("2026-10-07T01:05:00Z", failed=["Daten"])])
        r = self.run_a(t, "2026-10-07T12:00:00")
        self.assertEqual(r["missed"], [dt.date(2026, 10, 7)])
        self.assertEqual(r["failed_days"], [dt.date(2026, 10, 7)])

    def test_gap_over_48h_violates_even_with_one_missed(self):
        t = "\n".join(block(f"2026-10-{d:02d}T01:05:00Z") for d in (6, 7, 10))
        r = self.run_a(t, "2026-10-10T12:00:00")
        self.assertGreater(r["gap_h"], 48)
        self.assertTrue(r["violated"])

    def test_open_gap_to_now_counts(self):
        t = block("2026-10-06T01:05:00Z")
        r = self.run_a(t, "2026-10-09T12:00:00")
        self.assertGreater(r["gap_h"], 48)

    def test_today_pending_before_grace(self):
        t = block("2026-10-06T12:00:00Z")
        r = self.run_a(t, "2026-10-07T01:30:00")
        self.assertEqual(r["missed"], [])
        r2 = self.run_a(t, "2026-10-07T04:00:00")
        self.assertEqual(r2["missed"], [dt.date(2026, 10, 7)])

    def test_pass_after_56_days(self):
        days = [START + dt.timedelta(days=i) for i in range(56)]
        t = "\n".join(block(f"{d}T01:05:00Z") for d in days)
        r = self.run_a(t, f"{days[-1]}T12:00:00")
        self.assertEqual(r["verdict"], "PASS")

    def test_ledger_gap_duplicate_and_missing_realised(self):
        t = "\n".join(block(f"2026-10-{d:02d}T01:05:00Z") for d in (6, 7, 8, 9))
        rows = ledger_rows(["2026-10-05", "2026-10-06", "2026-10-08"])
        r = self.run_a(t, "2026-10-09T12:00:00", rows)
        self.assertIn("BTC 2026-10-07", r["ledger"]["gaps"])
        self.assertTrue(r["violated"])
        rows2 = ledger_rows(["2026-10-05", "2026-10-06"]) + [ledger_rows(["2026-10-05"])[0]]
        r2 = self.run_a(t, "2026-10-09T12:00:00", rows2)
        self.assertEqual(r2["ledger"]["dups"], 1)
        rows3 = ledger_rows(["2026-10-05", "2026-10-06", "2026-10-07"], realised=False)
        r3 = self.run_a(t, "2026-10-09T12:00:00", rows3)
        self.assertTrue(r3["ledger"]["missing_realised"])

    def test_clean_ledger_other_profile_ignored(self):
        t = "\n".join(block(f"2026-10-{d:02d}T01:05:00Z") for d in (6, 7))
        rows = ledger_rows(["2026-10-05", "2026-10-06"]) + ledger_rows(["2026-10-01", "2026-10-09"], profile="quant")
        r = self.run_a(t, "2026-10-07T12:00:00", rows)
        self.assertEqual(r["ledger"]["gaps"], [])
        self.assertFalse(r["violated"])


def order(date, side, sz, usd, cloid, status="planned", ts=None):
    return {"ts": ts or f"{date}T01:00:00Z", "date": date, "wallet": "A", "asset": "UBTC", "side": side, "sz": str(sz), "limit_px": "70000", "usd": str(usd), "cloid": cloid, "status": status, "reason": ""}


class CriterionBCTests(unittest.TestCase):
    def setUp(self):
        self.runs = ps.parse_runs("\n".join([
            block("2026-10-07T01:05:00Z", "2026-10-06", 10000, (("BTC", 7000.0, "UBTC"), ("ETH", 0.0, "UETH"))),
            block("2026-10-08T01:05:00Z", "2026-10-07", 10000, (("BTC", 7000.0, "UBTC"), ("ETH", 0.0, "UETH"))),
        ]))
        self.ledger = ledger_rows(["2026-10-06", "2026-10-07"])

    def test_b_ok_when_holdings_match_target(self):
        orders = [order("2026-10-06", "buy", 0.1, 7000, "c1")]
        b = ps.evaluate_b(self.runs, self.ledger, orders, {"holdings": {"UBTC": 0.1}})
        self.assertTrue(b["available"])
        self.assertTrue(b["ok"])
        self.assertTrue(b["cross"])
        self.assertAlmostEqual(b["max_dev"], 0.0, places=6)

    def test_b_flags_days_over_limit_and_dedups_cloid(self):
        orders = [order("2026-10-06", "buy", 0.05, 3500, "c1"), order("2026-10-06", "buy", 0.05, 3500, "c1")]  # doppelt
        b = ps.evaluate_b(self.runs, self.ledger, orders, {"holdings": {"UBTC": 0.05}}, max_days=1)
        self.assertEqual(len(b["over"]), 2)
        self.assertFalse(b["ok"])
        self.assertGreater(b["max_dev"], 0.05)

    def test_b_blocked_orders_not_counted_and_cross_check_warns(self):
        orders = [order("2026-10-06", "buy", 0.1, 7000, "c1", status="blocked")]
        b = ps.evaluate_b(self.runs, self.ledger, orders, {"holdings": {"UBTC": 0.1}})
        self.assertFalse(b["cross"])

    def test_b_not_evaluable_without_files_or_ziel(self):
        self.assertFalse(ps.evaluate_b(self.runs, self.ledger, None, None)["available"])
        self.assertFalse(ps.evaluate_b(ps.parse_runs(block("2026-10-07T01:05:00Z")), self.ledger, [], None)["available"])

    def test_b_no_price_not_evaluable(self):
        b = ps.evaluate_b(self.runs, [], [order("2026-10-06", "buy", 0.1, 7000, "c1")], None)
        self.assertFalse(b["available"])

    def test_c_costs(self):
        orders = [order("2026-10-06", "buy", 0.1, 7000, "c1"), order("2026-10-07", "sell", 0.01, 700, "c2")]
        c = ps.evaluate_c(orders, 7.0, 10.0)
        self.assertEqual(c["n"], 2)
        self.assertAlmostEqual(c["turnover"], 7700)
        self.assertAlmostEqual(c["cost"], 5.39)
        self.assertTrue(c["ok"])
        self.assertFalse(ps.evaluate_c(orders, 25.0, 10.0)["ok"])
        self.assertFalse(ps.evaluate_c(None, 7.0, 10.0)["available"])


class CliTests(unittest.TestCase):
    def make_dir(self, runs_text, ledger=None, orders=None, paper=None, ks=None):
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "data", "quant"))
        d = os.path.join(tmp, "data", "quant")
        with open(os.path.join(tmp, "q.yaml"), "w") as f:
            f.write("data_dir: data/quant\ncosts: {trend_bps: 10}\n")
        if runs_text is not None:
            with open(os.path.join(d, "daily.log"), "w") as f:
                f.write(runs_text)
        import csv
        if ledger is not None:
            with open(os.path.join(d, "ledger.csv"), "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                w.writeheader()
                for r in ledger:
                    w.writerow({k: r.get(k, "") for k in FIELDS})
        if orders is not None:
            with open(os.path.join(d, "orders_dryrun.csv"), "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
                w.writeheader()
                for r in orders:
                    w.writerow({k: r.get(k, "") for k in LOG_FIELDS})
        if paper is not None:
            with open(os.path.join(d, "paper_account_A.json"), "w") as f:
                json.dump(paper, f)
        if ks is not None:
            with open(os.path.join(d, "killswitch_A_dryrun.json"), "w") as f:
                json.dump(ks, f)
        return os.path.join(tmp, "q.yaml")

    def call(self, cfgpath, today):
        out = StringIO()
        with redirect_stdout(out):
            code = ps.main(["--config", cfgpath, "--plan", "/nonexistent.yaml", "--today", today])
        return code, out.getvalue()

    def test_missing_files_do_not_crash(self):
        cfg = self.make_dir(None)
        code, out = self.call(cfg, "2026-10-09")
        self.assertIn("nicht auswertbar", out)
        self.assertIn("nicht gefunden", out)
        self.assertEqual(code, 1)  # kein einziger Lauf = A verletzt

    def test_healthy_run_prints_compact_report(self):
        text = "\n".join(block(f"2026-10-{d:02d}T01:05:00Z", f"2026-10-{d - 1:02d}", 10000, (("BTC", 7000.0, "UBTC"), ("ETH", 0.0, "UETH"))) for d in (7, 8, 9))
        text = block("2026-10-06T12:43:00Z") + "\n" + text
        led = ledger_rows(["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"])
        orders = [order("2026-10-06", "buy", 0.1, 7000, "c1")]
        cfg = self.make_dir(text, led, orders, {"usdc": 3000, "holdings": {"UBTC": 0.1}, "fills": 1}, {"level": "normal", "hwm": 10000})
        code, out = self.call(cfg, "2026-10-09")
        self.assertEqual(code, 0, out)
        self.assertLessEqual(len(out.splitlines()), 25)
        for key in ("A Betrieb", "B Positionen", "C Kosten", "Kill-Switch Papier"):
            self.assertIn(key, out)
        self.assertNotIn("ß", out)

    def test_violation_gives_exit_1(self):
        text = block("2026-10-06T12:43:00Z") + "\n" + block("2026-10-10T01:05:00Z")
        code, out = self.call(self.make_dir(text), "2026-10-10")
        self.assertEqual(code, 1)
        self.assertIn("VERLETZT", out)

    def test_read_only(self):
        text = block("2026-10-06T12:43:00Z")
        cfg = self.make_dir(text)
        d = os.path.join(os.path.dirname(cfg), "data", "quant")
        before = sorted(os.listdir(d))
        self.call(cfg, "2026-10-06")
        self.assertEqual(sorted(os.listdir(d)), before)


if __name__ == "__main__":
    unittest.main()
