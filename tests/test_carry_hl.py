import copy
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from autotrader.quant import carry_hl as ch  # noqa: E402
from autotrader.quant import data  # noqa: E402
from test_quant import QCFG, data_ms, synth_market  # noqa: E402


def good():
    s = {"total": 0.12, "cagr": 0.05, "max_dd": -0.04, "sharpe": 3.0, "n": 700, "half1": 0.05, "half2": 0.06}
    return {"V2x2 HL, Walk-Forward, Kosten x2": s}, {"V1x2": {"liq": 0}}


class DecideTests(unittest.TestCase):
    def test_all_criteria_met(self):
        res, info = good()
        ok, checks = ch.decide(res, info)
        self.assertTrue(ok)
        self.assertEqual(len(checks), 4)

    def test_each_criterion_can_fail_alone(self):
        for key, val in (("cagr", 0.03), ("max_dd", -0.12), ("half2", -0.01), ("total", -0.01)):
            res, info = good()
            res["V2x2 HL, Walk-Forward, Kosten x2"][key] = val
            self.assertFalse(ch.decide(res, info)[0], key)
        res, info = good()
        info["V1x2"]["liq"] = 1
        self.assertFalse(ch.decide(res, info)[0])


class VariantTests(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(QCFG)
        self.cfg["coins"] = ["BTC"]
        self.dates, ohlc, fund = synth_market(1100)
        self.ohlc, self.bn = {"BTC": ohlc}, {"BTC": fund}

    def test_six_runs_same_window_and_costs_x2_never_better(self):
        hl = {"BTC": {d: v * 1.2 for d, v in self.bn["BTC"].items()}}
        v = ch.run_variants(self.cfg, self.dates, self.ohlc, self.bn, hl)
        self.assertEqual(len(v["res"]), 6)
        n = {s["n"] for s in v["res"].values()}
        self.assertEqual(len(n), 1)  # gleiches Fenster fuer alle Laeufe
        r = v["res"]
        self.assertLessEqual(r["V1x2 HL, Standard, Kosten x2"]["total"], r["V1 HL, Standard"]["total"] + 1e-12)
        self.assertLessEqual(r["V2x2 HL, Walk-Forward, Kosten x2"]["total"], r["V2 HL, Walk-Forward"]["total"] + 1e-12)

    def test_too_short_history_not_evaluated(self):
        self.assertIsNone(ch.run_variants(self.cfg, self.dates[:400], self.ohlc, self.bn, {"BTC": self.bn["BTC"]}))

    def test_report_has_decision_and_no_eszett(self):
        hl = {"BTC": {d: v * 1.2 for d, v in self.bn["BTC"].items()}}
        v = ch.run_variants(self.cfg, self.dates, self.ohlc, self.bn, hl)
        out = []
        ch.report(v, 0, len(self.dates), out.append)
        text = "\n".join(out)
        self.assertIn("ERGEBNIS", text)
        self.assertNotIn("ß", text)


class LoadTests(unittest.TestCase):
    def test_load_inputs_and_cli_without_data(self):
        tmp = tempfile.mkdtemp()
        d = os.path.join(tmp, "data", "quant")
        os.makedirs(d)
        with open(os.path.join(tmp, "q.yaml"), "w") as f:
            f.write("data_dir: data/quant\nsource: binance\ncoins: [BTC]\nwalkforward: {train_days: 365, step_days: 30, switch_cost_bps: 5}\ncarry: {lev: 2, default: {lookback: 14, entry_apr: 0.12, exit_apr: 0.04}, grid: {lookback: [14], entry_apr: [0.12], exit_apr: [0.04]}}\ncosts: {spot_fee_bps: 7, perp_fee_bps: 4.5, slippage_bps: 2, trend_bps: 10}\n")
        out = StringIO()
        with redirect_stdout(out):
            code = ch.main(["--config", os.path.join(tmp, "q.yaml")])
        self.assertEqual(code, 1)
        self.assertIn("Keine HL-Funding-Daten", out.getvalue())

    def test_doubled(self):
        self.assertEqual(ch.doubled({"spot_fee_bps": 7, "slippage_bps": 2}), {"spot_fee_bps": 14, "slippage_bps": 4})


if __name__ == "__main__":
    unittest.main()
