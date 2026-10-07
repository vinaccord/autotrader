import copy
import datetime as dt
import os
import random
import sys
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from autotrader.quant import pipeline  # noqa: E402
from autotrader.quant.data import daily_sum, day_str  # noqa: E402
from autotrader.quant.metrics import stats  # noqa: E402
from autotrader.quant.strategies import carry_returns, trend_returns  # noqa: E402
from autotrader.quant.walkforward import allocate, make_grid, walk_forward  # noqa: E402

with open(os.path.join(os.path.dirname(__file__), "..", "quant.yaml"), encoding="utf-8") as f:
    QCFG = yaml.safe_load(f)

ZERO_COSTS = {"spot_fee_bps": 0, "perp_fee_bps": 0, "slippage_bps": 0, "trend_bps": 0}
COSTS = {"spot_fee_bps": 7, "perp_fee_bps": 4.5, "slippage_bps": 2, "trend_bps": 10}


def make_dates(n, start="2020-01-01"):
    d0 = dt.date.fromisoformat(start)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


def make_ohlc(dates, daily_returns, p0=100.0):
    out, price = {}, p0
    for d, r in zip(dates, daily_returns):
        o = price
        price = price * (1 + r)
        out[d] = (o, max(o, price) * 1.005, min(o, price) * 0.995, price)
    return out


def synth_market(n=1500, seed=3):
    rnd = random.Random(seed)
    dates = make_dates(n)
    rets, fund = [], {}
    regime = 1
    for i, d in enumerate(dates):
        if i % 250 == 0:
            regime = rnd.choice([1, 1, -1])
        rets.append(0.0012 * regime + rnd.gauss(0, 0.025))
        fund[d] = (0.0003 if regime == 1 else -0.0001) + rnd.gauss(0, 0.00005)
    return dates, make_ohlc(dates, rets), fund


class MetricsTests(unittest.TestCase):
    def test_constant_growth(self):
        s = stats([0.01] * 100)
        self.assertAlmostEqual(s["max_dd"], 0.0)
        self.assertAlmostEqual(s["total"], 1.01 ** 100 - 1, places=6)

    def test_drawdown(self):
        s = stats([0.1, -0.5, 0.1])
        self.assertAlmostEqual(s["max_dd"], -0.5)

    def test_daily_sum_groups_by_utc_day(self):
        rows = [(1_577_836_800_000, 0.0001), (1_577_836_800_000 + 8 * 3600_000, 0.0002), (1_577_836_800_000 + 25 * 3600_000, 0.0005)]
        out = daily_sum(rows)
        self.assertEqual(day_str(rows[0][0]), "2020-01-01")
        self.assertAlmostEqual(out["2020-01-01"], 0.0003)
        self.assertAlmostEqual(out["2020-01-02"], 0.0005)


class CarryTests(unittest.TestCase):
    def setUp(self):
        self.dates = make_dates(200)
        self.ohlc = make_ohlc(self.dates, [0.0] * 200)
        self.fund = {d: 0.0003 for d in self.dates}  # ca. 11% p.a.

    def test_earns_funding_without_costs(self):
        rets, info = carry_returns(self.dates, self.fund, self.ohlc, 7, 0.05, 0.0, 2, ZERO_COSTS)
        eff = 2 / 3
        self.assertGreater(info["days_in"], 150)
        self.assertAlmostEqual(sum(rets), eff * 0.0003 * info["days_in"], places=9)
        self.assertEqual(info["position"], 1)

    def test_costs_reduce_return(self):
        a, _ = carry_returns(self.dates, self.fund, self.ohlc, 7, 0.05, 0.0, 2, ZERO_COSTS)
        b, _ = carry_returns(self.dates, self.fund, self.ohlc, 7, 0.05, 0.0, 2, COSTS)
        self.assertLess(sum(b), sum(a))

    def test_exits_when_funding_turns_negative(self):
        fund = {d: (0.0003 if i < 60 else -0.0003) for i, d in enumerate(self.dates)}
        rets, info = carry_returns(self.dates, fund, self.ohlc, 7, 0.05, 0.0, 2, ZERO_COSTS)
        self.assertEqual(info["position"], 0)
        # Negatives Funding kostet nur, bis der Trailing-Schnitt unter die Austrittsschwelle faellt
        self.assertLessEqual(sum(1 for r in rets if r < 0), 5)
        self.assertEqual(sum(1 for r in rets[80:] if r != 0), 0)

    def test_no_entry_below_threshold(self):
        fund = {d: 0.00005 for d in self.dates}  # ca. 1.8% p.a.
        _, info = carry_returns(self.dates, fund, self.ohlc, 7, 0.08, 0.0, 2, ZERO_COSTS)
        self.assertEqual(info["days_in"], 0)

    def test_causality(self):
        dates, ohlc, fund = synth_market(400)
        full, _ = carry_returns(dates, fund, ohlc, 14, 0.1, 0.04, 2, COSTS)
        cut = 300
        part, _ = carry_returns(dates[:cut], fund, ohlc, 14, 0.1, 0.04, 2, COSTS)
        self.assertEqual(full[:cut], part)

    def test_liquidation_flag_on_spike(self):
        rets_px = [0.0] * 200
        rets_px[100] = 0.6  # +60% an einem Tag
        ohlc = make_ohlc(self.dates, rets_px)
        _, info = carry_returns(self.dates, self.fund, ohlc, 7, 0.05, 0.0, 2, ZERO_COSTS)
        self.assertGreaterEqual(info["liq_flags"], 1)


class TrendTests(unittest.TestCase):
    def test_flat_in_persistent_downtrend(self):
        dates = make_dates(400)
        ohlc = make_ohlc(dates, [-0.002] * 400)
        rets, target = trend_returns(dates, ohlc, 100, 20, 0.25, 1.0, 0.1, 10)
        self.assertEqual(target, 0.0)
        self.assertEqual(sum(abs(r) for r in rets), 0.0)

    def test_long_in_uptrend_respects_leverage_cap(self):
        rnd = random.Random(5)
        dates = make_dates(500)
        ohlc = make_ohlc(dates, [0.002 + rnd.gauss(0, 0.01) for _ in range(500)])
        rets, target = trend_returns(dates, ohlc, 100, 20, 0.25, 1.0, 0.1, 10)
        self.assertGreater(target, 0.0)
        self.assertLessEqual(target, 1.0)
        self.assertGreater(sum(rets), 0.0)

    def test_vol_target_reduces_exposure_in_high_vol(self):
        rnd = random.Random(7)
        dates = make_dates(500)
        calm = make_ohlc(dates, [0.001 + rnd.gauss(0, 0.005) for _ in range(500)])
        wild = make_ohlc(dates, [0.001 + rnd.gauss(0, 0.06) for _ in range(500)])
        _, t_calm = trend_returns(dates, calm, 100, 20, 0.25, 1.0, 0.0, 0)
        _, t_wild = trend_returns(dates, wild, 100, 20, 0.25, 1.0, 0.0, 0)
        if t_wild > 0:
            self.assertLess(t_wild, t_calm)

    def test_causality(self):
        dates, ohlc, _ = synth_market(500)
        full, _ = trend_returns(dates, ohlc, 100, 20, 0.25, 1.0, 0.1, 10)
        cut = 400
        part, _ = trend_returns(dates[:cut], ohlc, 100, 20, 0.25, 1.0, 0.1, 10)
        self.assertEqual(full[:cut], part)


class WalkForwardTests(unittest.TestCase):
    def test_picks_better_candidate(self):
        n = 600
        rnd = random.Random(9)
        good = [0.001 + rnd.gauss(0, 0.002) for _ in range(n)]
        bad = [-0.001 + rnd.gauss(0, 0.002) for _ in range(n)]
        oos, off, chosen = walk_forward([({"id": "bad"}, bad), ({"id": "good"}, good)], 200, 50)
        self.assertEqual(off, 200)
        self.assertTrue(all(p["id"] == "good" for _, p in chosen))
        self.assertEqual(oos, good[200:])

    def test_no_lookahead_in_selection(self):
        rnd = random.Random(1)
        n = 700
        a = [rnd.gauss(0.0005, 0.01) for _ in range(n)]
        b = [rnd.gauss(0.0005, 0.01) for _ in range(n)]
        base_oos, _, base_chosen = walk_forward([({"id": "a"}, a), ({"id": "b"}, b)], 200, 50)
        a2 = a[:500] + [x + 0.5 for x in a[500:]]  # Zukunft nach Tag 500 manipulieren
        new_oos, _, new_chosen = walk_forward([({"id": "a"}, a2), ({"id": "b"}, b)], 200, 50)
        k = 500 - 200
        self.assertEqual(base_oos[:k], new_oos[:k])
        self.assertEqual([c for c in base_chosen if c[0] <= 500], [c for c in new_chosen if c[0] <= 500])

    def test_grid_size(self):
        self.assertEqual(len(make_grid({"x": [1, 2, 3], "y": [4, 5]})), 6)


class AllocatorTests(unittest.TestCase):
    def test_weights_bounded_and_normalized(self):
        rnd = random.Random(2)
        s = {"carry": [rnd.gauss(0.0004, 0.002) for _ in range(800)], "trend": [rnd.gauss(0.0006, 0.02) for _ in range(800)]}
        out, hist = allocate(s, w_min=0.1, w_max=0.9)
        self.assertEqual(len(out), 800)
        self.assertGreater(len(hist), 3)
        for _, w in hist:
            self.assertAlmostEqual(sum(w.values()), 1.0, places=2)
            self.assertTrue(all(0.099 <= x <= 0.901 for x in w.values()))

    def test_allocator_is_causal(self):
        rnd = random.Random(4)
        a = [rnd.gauss(0.0004, 0.002) for _ in range(800)]
        b = [rnd.gauss(0.0006, 0.02) for _ in range(800)]
        out1, _ = allocate({"carry": a, "trend": b})
        b2 = b[:600] + [x + 0.3 for x in b[600:]]
        out2, _ = allocate({"carry": a, "trend": b2})
        self.assertEqual(out1[:600], out2[:600])


class PipelineTests(unittest.TestCase):
    def test_end_to_end_on_synthetic_data(self):
        dates, ohlc, fund = synth_market(1300)
        cfg = copy.deepcopy(QCFG)
        cfg["coins"] = ["BTC", "ETH"]
        ohlc2 = {"BTC": ohlc, "ETH": ohlc}
        fund2 = {"BTC": fund, "ETH": fund}
        res = pipeline.run(cfg, dates, ohlc2, fund2)
        n = len(res["dates"])
        self.assertEqual(n, 1300 - cfg["walkforward"]["train_days"])
        for k in ("carry", "trend", "combined", "buyhold", "fixed_5050"):
            self.assertEqual(len(res[k]), n)
        self.assertGreater(res["trials"], 20)
        sig = pipeline.signal(cfg, dates, ohlc2, fund2, res)
        self.assertEqual(set(sig["carry"]), {"BTC", "ETH"})
        self.assertIn("target_exposure", sig["trend"]["BTC"])
        self.assertEqual(len(pipeline.summary(res)), 7)


if __name__ == "__main__":
    unittest.main()


class ProfileTests(unittest.TestCase):
    def test_fixed_weights_and_no_trend_adapt(self):
        dates, ohlc, fund = synth_market(1300)
        cfg = copy.deepcopy(QCFG)
        cfg["coins"] = ["BTC"]
        cfg["trend"]["adapt"] = False
        cfg["allocator"]["fixed"] = {"carry": 0.3, "trend": 0.7}
        res = pipeline.run(cfg, dates, {"BTC": ohlc}, {"BTC": fund})
        self.assertEqual(res["weights"][-1][1], {"carry": 0.3, "trend": 0.7})
        self.assertEqual(len({str(p) for _, p in res["trend_chosen"]}), 1)
        exp = [0.3 * a + 0.7 * b for a, b in zip(res["carry"], res["trend"])]
        self.assertEqual(exp, res["combined"])


class ReportTests(unittest.TestCase):
    def _pack(self, cfg, dates, ohlc, fund):
        return {"cfg": cfg, "dates": dates, "ohlc": {"BTC": ohlc}, "fund": {"BTC": fund}}

    def test_report_runs_flags_stale_and_changes(self):
        from autotrader.quant import report
        dates, ohlc, fund = synth_market(1300)
        cfg = copy.deepcopy(QCFG)
        cfg["coins"] = ["BTC"]
        m = self._pack(cfg, dates, ohlc, fund)
        c = self._pack(cfg, dates, ohlc, fund)
        start = dates[-10]
        today = dt.date.fromisoformat(dates[-1]) + dt.timedelta(days=5)
        text, state, warns = report.build_report(m, c, start, None, today=today)
        self.assertIn("DATEN VERALTET", warns[0])
        self.assertIn("seit " + start, text)
        self.assertIn("Effektiv mit Spill", text)
        self.assertIn("Haupt+Spill", text)
        self.assertIn("main", state)
        prev = copy.deepcopy(state)
        prev["main"]["trend"]["BTC"] = round(1 - state["main"]["trend"]["BTC"], 2) if state["main"]["trend"]["BTC"] > 0.5 else 1.0
        m2 = self._pack(cfg, dates, ohlc, fund)
        c2 = self._pack(cfg, dates, ohlc, fund)
        text2, _, warns2 = report.build_report(m2, c2, start, prev, today=dt.date.fromisoformat(dates[-1]))
        self.assertTrue(any("Exposure" in w for w in warns2))
        self.assertNotIn("VERALTET", " ".join(warns2))


class LedgerTests(unittest.TestCase):
    def test_append_only_no_duplicates_and_realised(self):
        import csv
        import tempfile
        from autotrader.quant import ledger
        dates, ohlc, fund = synth_market(300)
        o = {"BTC": ohlc}
        path = os.path.join(tempfile.mkdtemp(), "ledger.csv")

        def sig(asof):
            return {"as_of": asof, "trend": {"BTC": {"target_exposure": 0.7}}, "carry": {"BTC": {"in_position": True}}, "weights": {"trend": 0.7, "carry": 0.3}}

        d1 = dates[:200]
        self.assertEqual(ledger.update(path, "p", sig(d1[-1]), d1, o), (1, 0))
        self.assertEqual(ledger.update(path, "p", sig(d1[-1]), d1, o), (0, 0))  # idempotent
        before = open(path, encoding="utf-8").read()
        d2 = dates[:201]
        self.assertEqual(ledger.update(path, "p", sig(d2[-1]), d2, o), (1, 1))
        after = open(path, encoding="utf-8").read()
        self.assertTrue(after.startswith(before))  # nur angehaengt
        rows = list(csv.DictReader(open(path, encoding="utf-8")))
        real = [r for r in rows if r["kind"] == "realised"][0]
        self.assertEqual(real["date"], d1[-1])
        self.assertAlmostEqual(float(real["next_day_ret"]), o["BTC"][dates[200]][3] / o["BTC"][d1[-1]][3] - 1, places=5)

    def test_report_writes_ledger(self):
        import tempfile
        from autotrader.quant import report
        dates, ohlc, fund = synth_market(1300)
        cfg = copy.deepcopy(QCFG)
        cfg["coins"] = ["BTC"]
        m = {"cfg": cfg, "dates": dates, "ohlc": {"BTC": ohlc}, "fund": {"BTC": fund}}
        c = {"cfg": cfg, "dates": dates, "ohlc": {"BTC": ohlc}, "fund": {"BTC": fund}}
        path = os.path.join(tempfile.mkdtemp(), "ledger.csv")
        _, _, warns = report.build_report(m, c, dates[-10], None, today=dt.date.fromisoformat(dates[-1]), ledger_path=path)
        self.assertTrue(os.path.exists(path))
        self.assertFalse(any("LEDGER" in w for w in warns))


class SensitivityTests(unittest.TestCase):
    def _args(self):
        dates, ohlc, fund = synth_market(900)
        return dates, ohlc, fund, (200, 30, 0.45, 1.0, 0.1)

    def test_delay_zero_is_unchanged_and_delay_one_shifts_by_one_day(self):
        from autotrader.quant.strategies import trend_returns
        dates, ohlc, fund, a = self._args()
        r0, _ = trend_returns(dates, ohlc, *a, 10)
        r0b, _ = trend_returns(dates, ohlc, *a, 10, delay=0)
        r1, _ = trend_returns(dates, ohlc, *a, 10, delay=1)
        self.assertEqual(r0, r0b)
        f0 = next(i for i, x in enumerate(r0) if x != 0)
        f1 = next(i for i, x in enumerate(r1) if x != 0)
        self.assertEqual(f1, f0 + 1)

    def test_delay_is_causal(self):
        from autotrader.quant.strategies import trend_returns
        dates, ohlc, fund, a = self._args()
        k = 600
        o2 = dict(ohlc)
        d = dates[k]
        o2[d] = tuple(x * 1.3 for x in ohlc[d])
        r, _ = trend_returns(dates, ohlc, *a, 10, delay=1)
        r2, _ = trend_returns(dates, o2, *a, 10, delay=1)
        self.assertEqual(r[:k], r2[:k])

    def test_funding_only_charges_long_days(self):
        from autotrader.quant.strategies import trend_returns
        dates, ohlc, fund, a = self._args()
        base, _ = trend_returns(dates, ohlc, *a, 10)
        f = [0.0003] * len(dates)
        withf, _ = trend_returns(dates, ohlc, *a, 10, funding=f)
        for b, w in zip(base, withf):
            if b == 0:
                self.assertEqual(w, 0)
            else:
                self.assertLessEqual(w, b + 1e-15)
        self.assertLess(sum(withf), sum(base))

    def test_sensitivity_run_matches_pipeline_trend(self):
        from autotrader.quant import sensitivity
        dates, ohlc, fund = synth_market(1300)
        cfg = copy.deepcopy(QCFG)
        cfg["coins"] = ["BTC"]
        cfg["allocator"] = {"fixed": {"carry": 0.3, "trend": 0.7}}
        cfg["trend"]["adapt"] = False
        rows, dev, _ = sensitivity.run(cfg, dates, {"BTC": ohlc}, {"BTC": fund})
        self.assertEqual(len(rows), len(sensitivity.SCENARIOS))
        self.assertLess(dev, 1e-9)


class HlLiquidityTests(unittest.TestCase):
    BOOK = {"levels": [[{"px": "99", "sz": "1", "n": 1}, {"px": "98", "sz": "10", "n": 1}], [{"px": "101", "sz": "1", "n": 1}, {"px": "102", "sz": "10", "n": 1}]]}

    def test_walk_book_and_impact(self):
        from autotrader.quant import hl_liquidity as h
        avg, filled = h.walk_book([("101", "1"), ("102", "10")], 101)
        self.assertAlmostEqual(avg, 101)
        self.assertAlmostEqual(filled, 101)
        r = h.impact_bps(self.BOOK, 202)  # 101 auf Ebene 1, 101 auf Ebene 2
        self.assertAlmostEqual(r["mid"], 100)
        self.assertAlmostEqual(r["spread_bps"], 200)
        self.assertGreater(r["buy_bps"], 100)  # teurer als bester Ask
        self.assertAlmostEqual(r["buy_fill"], 202)
        thin = h.impact_bps(self.BOOK, 100000)
        self.assertLess(thin["buy_fill"], 100000)

    def test_find_spot(self):
        from autotrader.quant import hl_liquidity as h
        meta = {"tokens": [{"name": "USDC", "index": 0}, {"name": "UBTC", "index": 142}], "universe": [{"name": "@1", "tokens": [5, 0], "index": 1}, {"name": "@142", "tokens": [142, 0], "index": 7}]}
        self.assertEqual(h.find_spot(meta, "UBTC"), (7, "@142"))
        self.assertIsNone(h.find_spot(meta, "UETH"))

    def test_check_with_fake_api(self):
        from autotrader.quant import hl_liquidity as h

        class R:
            def __init__(self, j):
                self.j = j
                self.status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return self.j

        class S:
            def request(self, method, url, timeout=0, json=None, **kw):
                t = json["type"]
                if t == "spotMetaAndAssetCtxs":
                    meta = {"tokens": [{"name": "USDC", "index": 0}, {"name": "UBTC", "index": 1}, {"name": "UETH", "index": 2}],
                            "universe": [{"name": "@10", "tokens": [1, 0], "index": 0}, {"name": "@11", "tokens": [2, 0], "index": 1}]}
                    return R([meta, [{"dayNtlVlm": "5000000"}, {"dayNtlVlm": "3000000"}]])
                if t == "metaAndAssetCtxs":
                    return R([{"universe": [{"name": "BTC"}, {"name": "ETH"}]}, [{"dayNtlVlm": "9e8"}, {"dayNtlVlm": "5e8"}]])
                return R(TestBook)

        TestBook = self.BOOK
        logs = []
        out = h.check([1000, 10000], session=S(), log=logs.append)
        self.assertIn("UBTC", out)
        self.assertTrue(any("Basis Spot-Mid" in l for l in logs))


class KillSwitchTests(unittest.TestCase):
    KS = {"warn_dd": 0.20, "brake_dd": 0.30, "brake_release_dd": 0.20, "stop_dd": 0.40, "stop_below_deposits": 0.60, "global_stop_dd": 0.40}

    def test_levels_and_hysteresis(self):
        from autotrader.quant import killswitch as k
        s = k.new_state(1000)
        s, i = k.evaluate(s, 1100, self.KS)
        self.assertEqual((i["level"], s["hwm"]), ("normal", 1100))
        s, i = k.evaluate(s, 1100 * 0.79, self.KS)
        self.assertEqual(i["level"], "warn")
        s, i = k.evaluate(s, 1100 * 0.69, self.KS)
        self.assertEqual((i["level"], i["exposure_mult"]), ("brake", 0.5))
        s, i = k.evaluate(s, 1100 * 0.75, self.KS)  # -25%: Bremse bleibt (erst unter -20% frei)
        self.assertEqual(i["level"], "brake")
        s, i = k.evaluate(s, 1100 * 0.81, self.KS)  # -19%
        self.assertEqual(i["level"], "normal")

    def test_stop_is_sticky_and_reset_needs_call(self):
        from autotrader.quant import killswitch as k
        s = k.new_state(1000)
        s, i = k.evaluate(s, 590, self.KS)
        self.assertEqual((i["level"], i["exposure_mult"]), ("stop", 0.0))
        s, i = k.evaluate(s, 1000, self.KS)  # Erholung hebt den Stopp nicht auf
        self.assertEqual(i["level"], "stop")
        s = k.reset(s, 1000)
        s, i = k.evaluate(s, 1000, self.KS)
        self.assertEqual(i["level"], "normal")

    def test_stop_below_deposits_even_with_small_drawdown(self):
        from autotrader.quant import killswitch as k
        s = k.new_state(1000, deposits=2000)  # frueher eingezahlt, Kontowert schon tief, Hoechststand 1000
        s, i = k.evaluate(s, 900, self.KS)  # 900 < 60% von 2000
        self.assertEqual(i["level"], "stop")

    def test_flows_move_hwm(self):
        from autotrader.quant import killswitch as k
        s = k.new_state(1000)
        s = k.record_flow(s, 1000, 500)
        self.assertEqual((s["hwm"], s["deposits"]), (1500, 1500))
        s = k.record_flow(s, 1500, -750)  # halbe Auszahlung
        self.assertAlmostEqual(s["hwm"], 750)
        s, i = k.evaluate(s, 750, self.KS)
        self.assertEqual(i["level"], "normal")  # Auszahlung ist kein Verlust
        with self.assertRaises(ValueError):
            k.record_flow(s, 750, -800)

    def test_global_and_persistence(self):
        import tempfile
        from autotrader.quant import killswitch as k
        hwm, stop, dd = k.global_check(590, 1000, self.KS)
        self.assertTrue(stop)
        hwm, stop, dd = k.global_check(900, 1000, self.KS)
        self.assertFalse(stop)
        p = os.path.join(tempfile.mkdtemp(), "ks.json")
        self.assertIsNone(k.load(p))
        k.save(p, k.new_state(500))
        self.assertEqual(k.load(p)["hwm"], 500)


class SafetyTests(unittest.TestCase):
    def test_all_checks(self):
        from autotrader.quant import safety as sf
        now = dt.datetime(2026, 10, 8, 1, 5, tzinfo=dt.timezone.utc)
        self.assertEqual(sf.data_age("2026-10-07", now, 36), [])
        self.assertTrue(sf.data_age("2026-10-05", now, 36))
        self.assertTrue(sf.data_age(None, now, 36))
        self.assertEqual(sf.source_divergence({"BTC": 100}, {"BTC": 102}, 0.03), [])
        self.assertTrue(sf.source_divergence({"BTC": 100}, {"BTC": 105}, 0.03))
        self.assertTrue(sf.source_divergence({"BTC": 100}, {}, 0.03))  # fail-closed
        self.assertTrue(sf.usdc_peg(0.97, 0.98))
        self.assertTrue(sf.usdc_peg(None, 0.98))
        self.assertEqual(sf.usdc_peg(0.999, 0.98), [])
        self.assertTrue(sf.unit_deviation({"UBTC": 103}, {"UBTC": 100}, 0.02))
        self.assertEqual(sf.unit_deviation({"UBTC": 100.5}, {"UBTC": 100}, 0.02), [])
        self.assertTrue(sf.orders([3000], 10000, 0, 0.25, 1.0))
        self.assertTrue(sf.orders([2000, 2000], 10000, 7000, 0.25, 1.0))
        self.assertEqual(sf.orders([2000], 10000, 0, 0.25, 1.0), [])
        self.assertTrue(sf.orders([1], 0, 0, 0.25, 1.0))
        self.assertTrue(sf.position_mismatch({"UBTC": 5000}, {"UBTC": 4000}, 10000, 0.05))
        self.assertEqual(sf.position_mismatch({"UBTC": 5000}, {"UBTC": 4800}, 10000, 0.05), [])


class HlExecTests(unittest.TestCase):
    def test_plan_orders_rounding_threshold_and_cloid(self):
        from autotrader.quant import hl_exec as h
        prices, szd = {"UBTC": 80000.0}, {"UBTC": 5}
        o, sk = h.plan_orders({"BTC": 4000.0}, {}, prices, szd, 10000, "A", "2026-10-07")
        self.assertEqual(len(o), 2)  # 4000 USD ueber 2250 USD Teilgrenze (90% von 25%) -> 2 Teilorders
        self.assertAlmostEqual(sum(x["sz"] for x in o), 0.05, places=5)
        self.assertEqual(o[0]["side"], "buy")
        self.assertAlmostEqual(o[0]["limit_px"], 80240.0)  # +30 bps, 5 gueltige Stellen
        again, _ = h.plan_orders({"BTC": 4000.0}, {}, prices, szd, 10000, "A", "2026-10-07")
        self.assertEqual([x["cloid"] for x in o], [x["cloid"] for x in again])  # idempotent
        self.assertEqual(len(o[0]["cloid"]), 34)
        # Aenderung unter 2% des Kontowerts: nicht handeln
        o, sk = h.plan_orders({"BTC": 4100.0}, {"UBTC": 0.05}, prices, szd, 10000, "A", "2026-10-07")
        self.assertEqual(o, [])
        self.assertTrue(sk)
        # vollstaendiger Verkauf geht immer, auch klein
        o, _ = h.plan_orders({"BTC": 0.0}, {"UBTC": 0.0002}, prices, szd, 10000, "A", "2026-10-07")
        self.assertEqual((len(o), o[0]["side"]), (1, "sell"))  # 16 USD, ueber Mindestwert 10, trotz Schwelle
        # unbekannter Coin
        o, sk = h.plan_orders({"XRP": 1000.0}, {}, prices, szd, 10000, "A", "2026-10-07")
        self.assertEqual((o, len(sk)), ([], 1))

    def test_large_order_is_split_below_cap(self):
        from autotrader.quant import hl_exec as h, safety as sf
        prices, szd = {"UBTC": 80000.0}, {"UBTC": 5}
        o, _ = h.plan_orders({"BTC": 8000.0}, {}, prices, szd, 10000, "A", "2026-10-07", max_order_frac=0.25)
        self.assertGreater(len(o), 1)
        self.assertAlmostEqual(sum(x["sz"] for x in o), 0.1, places=5)
        self.assertEqual(sf.orders([x["usd"] for x in o], 10000, 0, 0.25, 1.0), [])
        self.assertEqual(len({x["cloid"] for x in o}), len(o))

    def test_log_is_idempotent(self):
        import tempfile
        from autotrader.quant import hl_exec as h
        p = os.path.join(tempfile.mkdtemp(), "o.csv")
        row = {"ts": "t", "date": "d", "wallet": "A", "asset": "UBTC", "side": "buy", "sz": 1, "limit_px": 1, "usd": 1, "cloid": "0xabc", "status": "planned", "reason": ""}
        self.assertEqual(h.log_orders(p, [row]), 1)
        self.assertEqual(h.log_orders(p, [row]), 0)

    def test_targets_and_killswitch_mult(self):
        from autotrader.quant import hl_exec as h
        ew = {"trend": 1.0, "carry": 0.0, "cash": 0.0}
        t = h.targets_usd(ew, {"BTC": 1.0, "ETH": 0.5}, 10000, 0.5, ["BTC", "ETH"])
        self.assertAlmostEqual(t["BTC"], 2500)
        self.assertAlmostEqual(t["ETH"], 1250)

    def test_run_with_fake_api_dry_run_only(self):
        import tempfile
        from autotrader.quant import hl_exec as h, pipeline as pl

        dates, ohlc, fund = synth_market(1300)
        cfg = copy.deepcopy(QCFG)
        cfg["coins"] = ["BTC"]
        cfg["data_dir"] = tempfile.mkdtemp()
        last = ohlc[dates[-1]][3]
        data_mod = h.data
        orig_load, orig_sig = data_mod.load_all, pl.signal
        data_mod.load_all = lambda c: (dates, {"BTC": ohlc}, {"BTC": fund})
        pl.signal = lambda cfg_, d, o, f, r: {"as_of": dates[-1], "trend": {"BTC": {"target_exposure": 0.8}}, "carry": {"BTC": {"in_position": False, "trailing_apr": 0.0}}, "weights": {"trend": 0.7, "carry": 0.3}}

        class R:
            status_code = 200

            def __init__(self, j):
                self.j = j

            def raise_for_status(self):
                pass

            def json(self):
                return self.j

        class S:
            def request(self, method, url, timeout=0, json=None, params=None, **kw):
                if "coingecko" in url:
                    return R({"usd-coin": {"usd": 1.0}})
                t = json["type"]
                if t == "spotMetaAndAssetCtxs":
                    return R([{"tokens": [{"name": "USDC", "index": 0, "szDecimals": 8}, {"name": "UBTC", "index": 1, "szDecimals": 5}],
                               "universe": [{"name": "@10", "tokens": [1, 0], "index": 0}]}, [{"dayNtlVlm": "1"}]])
                if t == "allMids":
                    return R({"@10": str(last), "BTC": str(last)})
                if t == "candleSnapshot":
                    return R([{"t": data_mod.ms(dates[-1]), "o": last, "h": last, "l": last, "c": str(last), "v": 1}])
                raise AssertionError(t)

        try:
            plan = {"mode": "dry-run", "dry_run": {"paper_equity_usdc": 10000},
                    "kill_switch": {"warn_dd": 0.2, "brake_dd": 0.3, "brake_release_dd": 0.2, "stop_dd": 0.4, "stop_below_deposits": 0.6, "global_stop_dd": 0.4},
                    "safety": {"max_data_age_hours": 36, "max_source_divergence": 0.03, "unit_token_max_deviation": 0.02, "usdc_depeg_floor": 0.98, "max_order_frac": 0.25, "max_daily_turnover_frac": 1.0, "max_slippage_bps": 30}}
            now = dt.datetime.fromisoformat(dates[-1]).replace(tzinfo=dt.timezone.utc) + dt.timedelta(days=1, hours=1)
            out = h.run(cfg, plan, session=S(), now=now, log=lambda *_: None)
            self.assertEqual(out["violations"], [])
            self.assertGreaterEqual(len(out["orders"]), 1)
            self.assertTrue(all(o["side"] == "buy" for o in out["orders"]))
            self.assertTrue(os.path.exists(os.path.join(cfg["data_dir"], "orders_dryrun.csv")))
            # veraltete Daten blockieren
            out2 = h.run(cfg, plan, session=S(), now=now + dt.timedelta(days=5), log=lambda *_: None)
            self.assertTrue(any("alt" in v for v in out2["violations"]))
            # Papierkonto: zweiter Lauf am selben Tag plant nichts mehr nach
            again = h.run(cfg, plan, session=S(), now=now, log=lambda *_: None)
            self.assertEqual(again["orders"], [])
            self.assertGreater(again["equity"], 9900)  # Gebuehr kostet etwas, Rest bleibt
            # Stopp verkauft auch bei Sicherungs-Verstoss (alte Daten)
            import json
            ksp = os.path.join(cfg["data_dir"], "killswitch_A_dryrun.json")
            st = json.load(open(ksp))
            st["level"] = "stop"
            json.dump(st, open(ksp, "w"))
            stop = h.run(cfg, plan, session=S(), now=now + dt.timedelta(days=5), log=lambda *_: None)
            self.assertTrue(stop["violations"])
            self.assertFalse(stop["blocked"])
            self.assertTrue(stop["orders"] and all(o["side"] == "sell" for o in stop["orders"]))
            with self.assertRaises(SystemExit):
                h.run(cfg, dict(plan, mode="live"), session=S(), now=now, log=lambda *_: None)
        finally:
            data_mod.load_all, pl.signal = orig_load, orig_sig


class P1Tests(unittest.TestCase):
    def test_carry_rebalances_on_drift_and_liquidates_on_spike(self):
        dates = make_dates(120)
        fund = {d: 0.0005 for d in dates}
        up = make_ohlc(dates, [0.0] * 20 + [0.02] * 60 + [0.0] * 40)  # stetiger Anstieg ueber 60 Tage
        r, info = carry_returns(dates, fund, up, 7, 0.05, 0.0, 2, COSTS)
        self.assertGreaterEqual(info["rebalances"], 2)
        self.assertEqual(info["liq_flags"], 0)
        r0, _ = carry_returns(dates, fund, up, 7, 0.05, 0.0, 2, ZERO_COSTS)
        self.assertEqual(sum(1 for x in r0 if x < 0), 0)  # ohne Kosten nie ein Verlusttag
        spike = [0.0] * 120
        spike[50] = 0.6
        r, info = carry_returns(dates, fund, make_ohlc(dates, spike), 7, 0.05, 0.0, 2, ZERO_COSTS)
        self.assertEqual(info["liq_flags"], 1)
        self.assertLess(min(r), -0.30)  # Margin-Verlust 1/(lev+1) = 33%

    def test_spill_uses_walkforward_parameters(self):
        from autotrader.quant import spill
        d1, o1, f1 = synth_market(1300, seed=3)
        d2, o2, f2 = synth_market(1300, seed=4)
        cfg = copy.deepcopy(QCFG)
        cfg["coins"] = ["BTC", "ETH"]
        ohlc, fund = {"BTC": o1, "ETH": o2}, {"BTC": f1, "ETH": f2}
        res = pipeline.run(cfg, d1, ohlc, fund)
        cr, cf, pos = spill.carry_wf_parts(cfg, d1, ohlc, fund, res)
        self.assertEqual(len(cr["BTC"]), len(res["dates"]))
        mean_rets = [(a + b) / 2 for a, b in zip(cr["BTC"], cr["ETH"])]
        for a, b in zip(mean_rets, res["carry"]):
            self.assertAlmostEqual(a, b, places=12)  # Korb aus Einzelreihen == Walk-Forward-Carry
        cp = res["carry_chosen"][-1][1]
        for x in cfg["coins"]:
            _, info = carry_returns(d1, fund[x], ohlc[x], cp["lookback"], cp["entry_apr"], cp["exit_apr"], cfg["carry"]["lev"], cfg["costs"])
            self.assertEqual(pos[x], info["position"])  # gleiche Position wie das Signal
        ew = spill.effective_weights(cfg, d1, ohlc, fund, "spill", res=res)
        sig = pipeline.signal(cfg, d1, ohlc, fund, res)
        self.assertEqual(sorted(ew["carry_aktiv"]), sorted(c for c, v in sig["carry"].items() if v["in_position"]))

    def test_load_all_keeps_days_with_missing_funding(self):
        import tempfile
        from autotrader.quant import data as dm
        tmp = tempfile.mkdtemp()
        cfg = {"data_dir": tmp, "coins": ["BTC"], "source": "binance"}
        dates = make_dates(10)
        ts = lambda d: int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
        dm.save_rows(dm.cache_path(cfg, "prices", "BTC"), ["t", "o", "h", "l", "c", "v"], [(ts(d), 1, 2, 1, 1.5, 9) for d in dates])
        have = [d for k, d in enumerate(dates) if k not in (4, 9)]  # Luecke in der Mitte und am Ende
        dm.save_rows(dm.cache_path(cfg, "funding", "BTC"), ["t", "rate"], [(ts(d) + 3600_000, 0.0001) for d in have])
        logs = []
        out_dates, ohlc, fund = dm.load_all(cfg, log=logs.append)
        self.assertIn(dates[4], out_dates)  # Luecke bleibt im Kalender
        self.assertEqual(fund["BTC"][dates[4]], 0.0)
        self.assertEqual(out_dates[-1], dates[8])  # Ende ohne Funding wird abgeschnitten
        self.assertTrue(any("Funding-Luecke" in l for l in logs))
        self.assertTrue(any("Funding endet" in l for l in logs))


class VisionProbeTests(unittest.TestCase):
    XML1 = """<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>data.binance.vision</Name><IsTruncated>true</IsTruncated><NextMarker>data/spot/monthly/klines/BTCUSDT/</NextMarker><CommonPrefixes><Prefix>data/spot/monthly/klines/BTCUSDT/</Prefix></CommonPrefixes><CommonPrefixes><Prefix>data/spot/monthly/klines/ETHBTC/</Prefix></CommonPrefixes></ListBucketResult>"""
    XML2 = """<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated><CommonPrefixes><Prefix>data/spot/monthly/klines/FTTUSDT/</Prefix></CommonPrefixes><CommonPrefixes><Prefix>data/spot/monthly/klines/BTCUPUSDT/</Prefix></CommonPrefixes></ListBucketResult>"""

    def test_parse_and_classify(self):
        from autotrader.quant import vision_probe as v
        p, k, nm, tr = v.parse_listing(self.XML1)
        self.assertEqual((len(p), tr, nm), (2, True, "data/spot/monthly/klines/BTCUSDT/"))
        syms = v.symbols_from_prefixes(p)
        self.assertEqual(syms, ["BTCUSDT", "ETHBTC"])
        now, gone = v.classify(["BTCUSDT", "FTTUSDT", "BTCUPUSDT", "ETHBTC", "LUNAUSDT"], {"BTCUSDT"})
        self.assertEqual(now, ["BTCUSDT"])
        self.assertEqual(gone, ["FTTUSDT", "LUNAUSDT"])  # gehebelte Token und Nicht-USDT-Paare raus
        self.assertEqual(v.month_range(["x/FTT-1d-2021-05.zip", "x/FTT-1d-2022-11.zip", "x/FTT-1d-2022-11.zip.CHECKSUM"]), ("2021-05", "2022-11"))

    def test_probe_with_fake_session_and_paging(self):
        from autotrader.quant import vision_probe as v

        class R:
            status_code = 200

            def __init__(self, text=None, j=None):
                self.text, self.j = text, j

            def raise_for_status(self):
                pass

            def json(self):
                return self.j

        calls = []

        class S:
            def request(self, method, url, timeout=0, params=None, **kw):
                if "exchangeInfo" in url:
                    return R(j={"symbols": [{"symbol": "BTCUSDT", "status": "TRADING"}, {"symbol": "ETHUSDT", "status": "TRADING"}]})
                calls.append(dict(params))
                if params["prefix"] == v.BASE:
                    return R(self_xml := (TestXML2 if params.get("marker") else TestXML1))
                return R("""<ListBucketResult><IsTruncated>false</IsTruncated><Contents><Key>data/spot/monthly/klines/FTTUSDT/1d/FTTUSDT-1d-2021-05.zip</Key></Contents><Contents><Key>data/spot/monthly/klines/FTTUSDT/1d/FTTUSDT-1d-2022-11.zip</Key></Contents></ListBucketResult>""")

        TestXML1, TestXML2 = self.XML1, self.XML2
        logs = []
        out = v.probe(S(), log=logs.append)
        self.assertIn("FTTUSDT", out["gone"])
        self.assertEqual(len([c for c in calls if c["prefix"] == v.BASE]), 2)  # Seitenwechsel
        self.assertTrue(any("2021-05 bis 2022-11" in l for l in logs))


class UniverseDataTests(unittest.TestCase):
    @staticmethod
    def make_zip(rows, header=False):
        import io as _io, zipfile as _zf
        lines = (["open_time,open,high,low,close,volume,close_time,quote_volume,count,tbb,tbq,ignore"] if header else [])
        lines += [",".join(str(x) for x in r) for r in rows]
        buf = _io.BytesIO()
        with _zf.ZipFile(buf, "w") as z:
            z.writestr("x.csv", "\n".join(lines))
        return buf.getvalue()

    @staticmethod
    def row(day, close, micro=False):
        t = int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
        if micro:
            t *= 1000
        return [t, close, close + 1, close - 1, close, 10, t + 86399999, close * 10, 5, 1, 1, 0]

    def test_parse_timestamps_header_and_checksum(self):
        import hashlib
        from autotrader.quant import universe_data as u
        z = self.make_zip([self.row("2024-12-31", 100), self.row("2025-01-01", 101, micro=True)], header=True)
        good = hashlib.sha256(z).hexdigest() + "  x.zip"
        text = u.verify_and_read(z, good)
        rows = u.parse_csv(text)
        self.assertEqual([r[0] for r in rows], ["2024-12-31", "2025-01-01"])  # ms und Mikrosekunden, Kopfzeile uebersprungen
        with self.assertRaises(ValueError):
            u.verify_and_read(z, "0" * 64 + "  x.zip")

    def test_eligible(self):
        from autotrader.quant import universe_data as u
        self.assertTrue(u.eligible("SRMUSDT"))
        self.assertTrue(u.eligible("SUPERUSDT"))  # Basis SUPER endet nicht auf UP/DOWN/BULL/BEAR
        self.assertFalse(u.eligible("BTCUPUSDT"))
        self.assertFalse(u.eligible("USDCUSDT"))
        self.assertFalse(u.eligible("ETHBTC"))

    def test_run_resume_and_daily_after_last_month(self):
        import hashlib
        import tempfile
        from autotrader.quant import universe_data as u, vision_probe as v

        files = {
            "data/spot/monthly/klines/FOOUSDT/1d/FOOUSDT-1d-2022-10.zip": self.make_zip([self.row("2022-10-30", 5), self.row("2022-10-31", 6)]),
            "data/spot/daily/klines/FOOUSDT/1d/FOOUSDT-1d-2022-10-31.zip": self.make_zip([self.row("2022-10-31", 6)]),  # schon im Monat: ignorieren
            "data/spot/daily/klines/FOOUSDT/1d/FOOUSDT-1d-2022-11-01.zip": self.make_zip([self.row("2022-11-01", 1)]),
            "data/spot/daily/klines/FOOUSDT/1d/FOOUSDT-1d-2022-11-02.zip": self.make_zip([self.row("2022-11-02", 0.5)]),
        }
        counter = {"zip": 0}

        class R:
            status_code = 200

            def __init__(self, text="", content=b""):
                self.text, self.content = text, content

            def raise_for_status(self):
                pass

        class S:
            def request(self, method, url, timeout=0, params=None, **kw):
                if params is not None and "prefix" in params:
                    pre = params["prefix"]
                    if pre == u.MONTHLY:
                        return R("<ListBucketResult><IsTruncated>false</IsTruncated><CommonPrefixes><Prefix>%sFOOUSDT/</Prefix></CommonPrefixes><CommonPrefixes><Prefix>%sFOOUP/</Prefix></CommonPrefixes></ListBucketResult>" % (u.MONTHLY, u.MONTHLY))
                    keys = [k for k in files if k.startswith(pre)]
                    return R("<ListBucketResult><IsTruncated>false</IsTruncated>" + "".join(f"<Contents><Key>{k}</Key></Contents><Contents><Key>{k}.CHECKSUM</Key></Contents>" for k in keys) + "</ListBucketResult>")
                key = url.replace(u.FILES, "")
                if key.endswith(".CHECKSUM"):
                    return R(text=hashlib.sha256(files[key[:-9]]).hexdigest() + "  f.zip")
                counter["zip"] += 1
                return R(content=files[key])

        out = tempfile.mkdtemp()
        st = u.run(out, workers=2, session_factory=S, log=lambda *_: None)
        self.assertEqual(st["failed"], [])
        rows = u.read_symbol_csv(os.path.join(out, "FOOUSDT.csv"))
        self.assertEqual(sorted(rows), ["2022-10-30", "2022-10-31", "2022-11-01", "2022-11-02"])
        self.assertEqual(counter["zip"], 3)  # Monat + 2 Tage nach dem letzten Monat; Tag 2022-10-31 uebersprungen
        n = counter["zip"]
        u.run(out, workers=2, session_factory=S, log=lambda *_: None)
        self.assertEqual(counter["zip"], n)  # fortsetzbar: nichts erneut geladen
        self.assertFalse(os.path.exists(os.path.join(out, "FOOUP.csv")))


class XsMomTests(unittest.TestCase):
    @staticmethod
    def panel(n=400, coins=8, seed=11, delist=None, young=None, drift0=0.003):
        from autotrader.quant import xsmom as x
        rnd = random.Random(seed)
        dates = make_dates(n)
        raw = {}
        for k in range(coins):
            drift = drift0 if k == 0 else 0.0
            price, rows = 100.0, {}
            for i, d in enumerate(dates):
                price *= 1 + drift + rnd.gauss(0, 0.03)
                rows[d] = (price, price, price, price, 5_000_000.0 + k)
            raw[f"C{k}USDT"] = rows
        raw["BTCUSDT"] = {d: (100.0 + i, 0, 0, 100.0 + i, 9e9) for i, d in enumerate(dates)}
        raw["ETHUSDT"] = {d: (50.0 + i * 0.5, 0, 0, 50.0 + i * 0.5, 8e9) for i, d in enumerate(dates)}
        if delist:
            sym, day = delist
            raw[sym] = {d: v for d, v in raw[sym].items() if d <= dates[day]}
        if young:
            sym, day = young
            raw[sym] = {d: v for d, v in raw[sym].items() if d >= dates[day]}
        return x.build_panel(raw), dates

    def test_stablecoin_removed_and_universe_point_in_time(self):
        from autotrader.quant import xsmom as x
        raw = {"USDXUSDT": {f"2021-01-{d:02d}": (1, 1, 1, 1.0, 1e6) for d in range(1, 29)}}
        raw["USDXUSDT"].update({f"2021-02-{d:02d}": (1, 1, 1, 1.0, 1e6) for d in range(1, 29)})
        raw["USDXUSDT"].update({f"2021-03-{d:02d}": (1, 1, 1, 1.0, 1e6) for d in range(1, 29)})
        raw["BTCUSDT"] = {d: (10, 10, 10, 10.0 + i, 1e9) for i, d in enumerate(sorted(raw["USDXUSDT"]))}
        p = x.build_panel(raw)
        self.assertNotIn("USDXUSDT", p["close"])
        p2, dates = self.panel(young=("C3USDT", 200))
        self.assertNotIn("C3USDT", x.universe_at(p2, 250))  # erst 50 Tage alt (<90)
        self.assertIn("C3USDT", x.universe_at(p2, 300))

    def test_causality_changing_future_does_not_change_past(self):
        from autotrader.quant import xsmom as x
        p, dates = self.panel()
        p2, _ = self.panel()  # frisches Panel ohne Zwischenspeicher
        m = 300
        for s in p2["close"]:
            if p2["close"][s][m] is not None:
                p2["close"][s][m] *= 1.5
        r1, _ = x.backtest(p, 120, 30, False, 20)
        r2, _ = x.backtest(p2, 120, 30, False, 20)
        self.assertEqual(r1[:m], r2[:m])  # Kurs am Tag m darf nur Renditen ab Index m aendern
        self.assertNotEqual(r1[m], r2[m])

    def test_momentum_picks_the_trending_coin_and_costs_matter(self):
        from autotrader.quant import xsmom as x
        p, dates = self.panel(seed=5)
        r, info = x.backtest(p, 120, 30, False, 20)
        r_hi, _ = x.backtest(p, 120, 30, False, 400)
        self.assertGreater(sum(r), sum(r_hi))
        w = x.pick(p, 300, 30, False)
        self.assertLessEqual(len(w), x.K)
        self.assertTrue(all(abs(v - 1.0 / x.K) < 1e-12 for v in w.values()))

    def test_delisting_while_held_books_penalty_then_cash(self):
        from autotrader.quant import xsmom as x
        p, dates = self.panel(delist=("C0USDT", 250), drift0=0.02)
        # C0 hat Drift und wird gehalten; Datenende an Tag 250
        r, info = x.backtest(p, 120, 30, False, 0)
        self.assertGreaterEqual(info["delisted_events"], 1)
        self.assertLess(min(r[251:252]), 0)  # Abschlag am Tag nach dem letzten Kurs


class GdeltOffTests(unittest.TestCase):
    def test_gdelt_disabled_makes_no_tone_requests(self):
        import tempfile
        from autotrader.quant import macro

        class S:
            def get(self, url, **kw):
                if "gdelt" in url:
                    raise AssertionError("GDELT darf nicht abgefragt werden")
                raise RuntimeError("offline")

        orig = macro.fetch_fng
        macro.fetch_fng = lambda session=None: {"2026-10-01": 50}
        try:
            cfg = {"data_dir": tempfile.mkdtemp(), "macro": {"gdelt_enabled": False, "queries": {"x": "y"}}}
            logs = []
            macro.cmd_fetch(cfg, log=logs.append, session=S())
        finally:
            macro.fetch_fng = orig
        self.assertTrue(any("GDELT aus" in l for l in logs))


class MacroTests(unittest.TestCase):
    def test_parse_fng_and_gdelt(self):
        from autotrader.quant import macro
        fng = macro.parse_fng({"data": [{"value": "47", "timestamp": "1700000000"}, {"value": "80", "timestamp": "1700086400"}]})
        self.assertEqual(fng, {"2023-11-14": 47.0, "2023-11-15": 80.0})
        tone = macro.parse_gdelt_tone({"timeline": [{"series": "Average Tone", "data": [{"date": "x", "value": -2.0}, {"date": "y", "value": -4.0}, {"date": "z"}]}]})
        self.assertAlmostEqual(tone, -3.0)
        self.assertIsNone(macro.parse_gdelt_tone({}))

    def test_rule_is_lagged_and_scales_returns(self):
        from autotrader.quant import macro
        dates = make_dates(6)
        fng = {dates[0]: 90.0}  # extreme Gier nur am Tag 0
        rets = [0.01] * 6
        out = macro.apply_rule("greed_cut", dates, fng, rets, cost_bps=0)
        self.assertEqual(out[0], 0.01)                 # Tag 0: kein Wert von gestern -> voll
        self.assertAlmostEqual(out[1], 0.005)           # Tag 1: Wert von Tag 0 (Gier) -> halbe Position
        self.assertEqual(out[2], 0.01)                  # danach wieder voll
        c = macro.apply_rule("greed_cut", dates, fng, rets, cost_bps=10)
        self.assertLess(c[1], out[1])                   # Wechselkosten

    def test_rule_causal(self):
        from autotrader.quant import macro
        dates = make_dates(10)
        base = {d: 50.0 for d in dates}
        a = macro.apply_rule("greed_cut", dates, base, [0.01] * 10)
        fut = dict(base)
        fut[dates[8]] = 99.0
        b = macro.apply_rule("greed_cut", dates, fut, [0.01] * 10)
        self.assertEqual(a[:9], b[:9])

    def test_fetch_and_log_with_fake_session(self):
        import tempfile
        from autotrader.quant import macro

        class R:
            def __init__(s, j): s.j = j
            def raise_for_status(s): pass
            def json(s): return s.j

        class S:
            def get(s, url, params=None, timeout=None):
                if "alternative" in url:
                    return R({"data": [{"value": "30", "timestamp": "1700000000"}]})
                return R({"timeline": [{"data": [{"value": -1.0}]}]})

        with tempfile.TemporaryDirectory() as td:
            cfg = {"data_dir": td, "macro": {"queries": {"fed": "x"}}}
            lines = []
            macro.cmd_fetch(cfg, log=lines.append, session=S(), pause=0, retry_wait=0)
            self.assertEqual(macro.load_fng(cfg), {"2023-11-14": 30.0})
            self.assertIn("Fear & Greed", macro.latest_line(cfg))
            self.assertFalse(macro.append_tone(cfg, dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"), {"fed": -1.0}))


    def test_empty_day_is_replaced_and_all_none_not_written(self):
        import tempfile
        from autotrader.quant import macro
        with tempfile.TemporaryDirectory() as td:
            cfg = {"data_dir": td}
            self.assertFalse(macro.append_tone(cfg, "2026-10-06", {"a": None, "b": None}))
            self.assertFalse(os.path.exists(macro.tone_path(cfg)))
            data_rows = [["2026-10-06", "", ""]]
            from autotrader.quant import data as d
            d.save_rows(macro.tone_path(cfg), ["date", "a", "b"], data_rows)
            self.assertTrue(macro.append_tone(cfg, "2026-10-06", {"a": -1.0, "b": None}))
            self.assertEqual(d.load_rows(macro.tone_path(cfg)), [["2026-10-06", "-1.000", ""]])


class VariantTests(unittest.TestCase):
    def test_ensemble_scales_and_int_equals_list_of_one(self):
        dates, ohlc, _ = synth_market(900)
        kw = dict(vol_window=30, target_vol=0.45, max_lev=1.0, band=0.0, cost_bps=0)
        a, _ = trend_returns(dates, ohlc, 100, **kw)
        b, _ = trend_returns(dates, ohlc, [100], **kw)
        self.assertEqual(a, b)
        m, _ = trend_returns(dates, ohlc, [50, 100, 200], **kw)
        self.assertEqual(len(m), len(a))
        self.assertTrue(any(0 < abs(x) for x in m))

    def test_crash_and_event_reduce_exposure_causally(self):
        dates = make_dates(400)
        rets = [0.003] * 300 + [-0.04] * 5 + [0.003] * 95
        ohlc = make_ohlc(dates, rets)
        kw = dict(vol_window=30, target_vol=5.0, max_lev=1.0, band=0.0, cost_bps=0)
        plain, _ = trend_returns(dates, ohlc, 100, **kw)
        cut, _ = trend_returns(dates, ohlc, 100, crash={"days": 3, "pct": 0.08, "mult": 0.5}, **kw)
        self.assertLess(sum(abs(x) for x in cut[300:320]), sum(abs(x) for x in plain[300:320]))
        self.assertEqual(plain[:303], cut[:303])        # vor dem Crash identisch -> keine Zukunft
        ev = {dates[350]}
        e, _ = trend_returns(dates, ohlc, 100, event_days=ev, **kw)
        self.assertAlmostEqual(e[350], plain[350] * 0.5)
        self.assertEqual(e[349], plain[349])

    def test_event_set_and_compare_runs_on_files(self):
        import tempfile
        from autotrader.quant import variants, data as d
        s = variants.event_set(["2024-01-31"])
        self.assertEqual(s, {"2024-01-31", "2024-02-01"})
        with tempfile.TemporaryDirectory() as td:
            dates, ohlc, _ = synth_market(900)
            for c in ("BTC", "ETH"):
                rows = [[int(dt.datetime.fromisoformat(x).replace(tzinfo=dt.timezone.utc).timestamp() * 1000), *ohlc[x], 1.0] for x in dates]
                d.save_rows(os.path.join(td, f"binance_prices_{c}.csv"), ["ts", "open", "high", "low", "close", "volume"], rows)
            cfg = {"data_dir": td, "source": "binance", "eval_start": dates[400], "costs": {"trend_bps": 10},
                   "trend": {"vol_window": 30, "target_vol": 0.45, "max_lev": 1.0, "band": 0.1},
                   "events": {"fomc": [dates[500]]},
                   "variants": {"a": {"coins": ["BTC", "ETH"], "sma_n": 200},
                                "b": {"coins": ["BTC", "ETH"], "sma_n": [50, 100, 200], "fomc": 0.5, "crash": {"days": 7, "pct": 0.15, "mult": 0.5}}}}
            lines = []
            res = variants.compare(cfg, 2.0, log=lines.append)
            self.assertEqual(set(res), {"a", "b"})
            self.assertTrue(any("Kosten x2" in x for x in lines))


    def test_late_coin_joins_after_warmup_and_missing_cache_skipped(self):
        import tempfile
        from autotrader.quant import variants, data as d
        with tempfile.TemporaryDirectory() as td:
            dates, ohlc, _ = synth_market(900)
            def write(c, ds):
                rows = [[int(dt.datetime.fromisoformat(x).replace(tzinfo=dt.timezone.utc).timestamp() * 1000), *ohlc[x], 1.0] for x in ds]
                d.save_rows(os.path.join(td, f"binance_prices_{c}.csv"), ["ts", "open", "high", "low", "close", "volume"], rows)
            write("BTC", dates); write("ETH", dates); write("NEW", dates[600:])
            cfg = {"data_dir": td, "source": "binance", "eval_start": dates[400], "costs": {"trend_bps": 10},
                   "trend": {"vol_window": 30, "target_vol": 0.45, "max_lev": 1.0, "band": 0.1},
                   "variants": {"a": {"coins": ["BTC", "ETH"], "sma_n": 200},
                                "b": {"coins": ["BTC", "ETH", "NEW", "GONE"], "sma_n": 100}}}
            lines = []
            res = variants.compare(cfg, 1.0, log=lines.append)
            self.assertTrue(any("GONE" in x for x in lines))
            self.assertEqual(len(res["a"]), len(res["b"]))
            ser = variants.coin_series(cfg, "NEW", cfg["variants"]["b"], 10, set())
            self.assertGreater(ser[1], dates[600])  # Einlaufzeit


class SpillTests(unittest.TestCase):
    def test_modes_weights(self):
        from autotrader.quant import spill
        trend = [0.01] * 4
        cr = {"A": [0.0] * 4, "B": [0.0] * 4}
        cf = {"A": [0, 0, 0, 0], "B": [0, 0, 0, 0]}  # beide Carry-Teile flat
        idle = spill.combine(cr, cf, trend, 0.3, "idle")
        full = spill.combine(cr, cf, trend, 0.3, "spill")
        half = spill.combine(cr, cf, trend, 0.3, "spill_half")
        tonly = spill.combine(cr, cf, trend, 0.3, "trend_only")
        self.assertAlmostEqual(idle[0], 0.007)
        self.assertAlmostEqual(full[0], 0.01)
        self.assertAlmostEqual(half[0], 0.0085)
        self.assertAlmostEqual(tonly[0], 0.01)
        cf2 = {"A": [1] * 4, "B": [0] * 4}
        cr2 = {"A": [0.001] * 4, "B": [0.0] * 4}
        m = spill.combine(cr2, cf2, trend, 0.3, "spill")
        self.assertAlmostEqual(m[0], 0.15 * 0.001 + (0.7 + 0.15) * 0.01)

    def test_flags_exposed_and_run_end_to_end(self):
        from autotrader.quant import spill
        dates, ohlc, fund = synth_market(900)
        r, info = carry_returns(dates, fund, ohlc, 14, 0.12, 0.04, 2, COSTS)
        self.assertEqual(len(info["flags"]), len(dates))
        self.assertEqual(sum(info["flags"]), info["days_in"])
        import tempfile
        from autotrader.quant import data as d
        with tempfile.TemporaryDirectory() as td:
            cfg = copy.deepcopy(QCFG)
            cfg["coins"] = ["BTC"]
            cfg["data_dir"] = td
            cfg["allocator"]["fixed"] = {"carry": 0.3, "trend": 0.7}
            dates, ohlc, fund = synth_market(1300)
            rows = [[int(dt.datetime.fromisoformat(x).replace(tzinfo=dt.timezone.utc).timestamp() * 1000), *ohlc[x], 1.0] for x in dates]
            d.save_rows(os.path.join(td, "binance_prices_BTC.csv"), ["ts", "open", "high", "low", "close", "volume"], rows)
            frows = [[int(dt.datetime.fromisoformat(x).replace(tzinfo=dt.timezone.utc).timestamp() * 1000), fund[x]] for x in dates]
            d.save_rows(os.path.join(td, "binance_funding_BTC.csv"), ["ts", "rate"], frows)
            lines = []
            out = spill.run(cfg, log=lines.append)
            self.assertEqual(set(out), {"idle", "spill_half", "spill", "trend_only"})
            self.assertTrue(any("Carry war an" in x for x in lines))


class FetchSafetyTests(unittest.TestCase):
    class R:
        def __init__(self, j, code=200):
            self.j, self.status_code = j, code

        def raise_for_status(self):
            if self.status_code >= 400:
                import requests
                raise requests.HTTPError(response=self)

        def json(self):
            return self.j

    def _cfg(self, td):
        return {"data_dir": td, "source": "binance", "coins": ["BTC"], "start": "2020-01-01"}

    def test_failed_funding_keeps_old_cache_and_short_fetch_does_not_overwrite(self):
        import tempfile
        from autotrader.quant import data as d
        R = self.R
        kl = [[1577836800000 + i * 86400000, "1", "1", "1", "1", "1"] for i in range(5)]

        class S:
            def request(s, method, url, **kw):
                if "klines" in url:
                    return R(kl[:2])  # Teil-Abruf: nur 2 statt 5 Kerzen
                return R({}, 500)  # Funding faellt aus

        with tempfile.TemporaryDirectory() as td:
            cfg = self._cfg(td)
            d.save_rows(d.cache_path(cfg, "prices", "BTC"), ["ts", "open", "high", "low", "close", "volume"], kl)
            d.save_rows(d.cache_path(cfg, "funding", "BTC"), ["ts", "rate"], [[1577836800000, "0.0001"]])
            orig = d.time.sleep
            d.time.sleep = lambda x: None
            try:
                lines = []
                d.fetch_all(cfg, log=lines.append, session=S())
            finally:
                d.time.sleep = orig
            self.assertEqual(d.count_rows(d.cache_path(cfg, "prices", "BTC")), 5)
            self.assertEqual(d.count_rows(d.cache_path(cfg, "funding", "BTC")), 1)
            self.assertTrue(any("Cache bleibt" in x or "alter Funding-Cache" in x for x in lines))

    def test_request_retries_on_429(self):
        from autotrader.quant import data as d
        R = self.R
        calls = []

        class S:
            def request(s, method, url, **kw):
                calls.append(1)
                return R([], 429) if len(calls) < 3 else R([1])

        orig = d.time.sleep
        d.time.sleep = lambda x: None
        try:
            r = d._request(S(), "GET", "http://x")
        finally:
            d.time.sleep = orig
        self.assertEqual(r.json(), [1])
        self.assertEqual(len(calls), 3)
