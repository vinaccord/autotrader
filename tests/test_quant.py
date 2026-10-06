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
