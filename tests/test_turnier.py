import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_autotrader import CFG, NOW, Fixed, cand, make  # noqa: E402

from autotrader import adapt  # noqa: E402
from autotrader.models import Decision  # noqa: E402
from autotrader.security import FakeChecker, Regime, evaluate_goplus  # noqa: E402

GOOD = {"is_honeypot": "0", "is_open_source": "1", "buy_tax": "0.01", "sell_tax": "0.01", "holder_count": "500"}


class SecurityTests(unittest.TestCase):
    def test_good_token_passes(self):
        self.assertTrue(evaluate_goplus(GOOD)[0])

    def test_honeypot_and_unknown_fail_closed(self):
        self.assertFalse(evaluate_goplus({**GOOD, "is_honeypot": "1"})[0])
        self.assertFalse(evaluate_goplus(None)[0])
        self.assertFalse(evaluate_goplus({})[0])
        bad = dict(GOOD)
        del bad["is_honeypot"]
        self.assertFalse(evaluate_goplus(bad)[0])
        no_sell_tax = dict(GOOD)
        del no_sell_tax["sell_tax"]
        self.assertFalse(evaluate_goplus(no_sell_tax)[0])

    def test_tax_holders_and_flags(self):
        self.assertFalse(evaluate_goplus({**GOOD, "sell_tax": "0.30"})[0])
        self.assertFalse(evaluate_goplus({**GOOD, "holder_count": "20"})[0])
        self.assertFalse(evaluate_goplus({**GOOD, "is_open_source": "0"})[0])
        self.assertFalse(evaluate_goplus({**GOOD, "hidden_owner": "1"})[0])
        self.assertFalse(evaluate_goplus({**GOOD, "cannot_sell_all": "1"})[0])


class RegimeTests(unittest.TestCase):
    def test_risk_off_when_market_falls(self):
        r = Regime({"min_breadth": 0.35, "min_median_change_24h": -8.0})
        falling = [cand(addr=f"0x{i}", h24=-12) for i in range(6)]
        rising = [cand(addr=f"0x{i}", h24=10) for i in range(6)]
        self.assertTrue(r.assess(falling)["risk_off"])
        self.assertFalse(r.assess(rising)["risk_off"])

    def test_too_few_candidates_means_no_signal(self):
        r = Regime({})
        self.assertFalse(r.assess([cand()])["risk_off"])


class AgentGuardTests(unittest.TestCase):
    def _agent_with(self, decisions, checker=None, cands=None):
        cands = cands or [cand()]
        _, ledger, _, _, _, agent = make(cands, researcher=Fixed(decisions))
        agent.security = checker
        return ledger, agent

    def test_security_blocks_buy(self):
        d = Decision("buy", "0xaaa", "AAA", 20, "test")
        ledger, agent = self._agent_with([d], FakeChecker({"0xaaa": (False, "Honeypot")}))
        agent.tick(NOW)
        self.assertEqual(len(ledger.positions(1)), 0)

    def test_security_ok_allows_buy(self):
        d = Decision("buy", "0xaaa", "AAA", 20, "test")
        ledger, agent = self._agent_with([d], FakeChecker())
        agent.tick(NOW)
        self.assertEqual(len(ledger.positions(1)), 1)

    def test_risk_off_blocks_buy(self):
        cands = [cand(addr=f"0x{i}", sym=f"T{i}", h24=-15) for i in range(6)]
        d = Decision("buy", "0x0", "T0", 20, "test")
        ledger, agent = self._agent_with([d], FakeChecker(), cands)
        agent.tick(NOW)
        self.assertEqual(len(ledger.positions(1)), 0)

    def test_paused_strategy_does_not_trade(self):
        d = Decision("buy", "0xaaa", "AAA", 20, "test")
        ledger, agent = self._agent_with([d], FakeChecker())
        ledger.kv_set("paused:momentum", "1")
        agent.tick(NOW)
        self.assertEqual(len(ledger.positions(1)), 0)

    def test_security_checked_again_on_approval(self):
        c = cand()
        _, ledger, _, _, _, agent = make([c])
        agent.tick(NOW)  # Kauf 50 USD landet in der Freigabe-Queue
        aid = ledger.pending_approvals()[0]["id"]
        agent.security = FakeChecker({"0xaaa": (False, "jetzt auffaellig")})
        msg = agent.resolve_approval(aid, True, NOW + 60)
        self.assertIn("Sicherheitscheck", msg)
        self.assertEqual(len(ledger.positions(1)), 0)


def add_sells(ledger, n, pnl, slot_id=1):
    for i in range(n):
        ledger.record_trade(slot_id, "sell", "X", f"0x{i}", 1, 1, 10, 0.03, pnl=pnl, ts=NOW)


class AdaptTests(unittest.TestCase):
    def test_pause_after_enough_losing_trades(self):
        _, ledger, _, _, _, _ = make([])
        add_sells(ledger, 20, -1.0)
        self.assertEqual(adapt.apply_pause_rules(ledger, CFG), ["momentum"])
        self.assertTrue(adapt.is_paused(ledger, "momentum"))

    def test_no_pause_with_few_trades(self):
        _, ledger, _, _, _, _ = make([])
        add_sells(ledger, 5, -1.0)
        self.assertEqual(adapt.apply_pause_rules(ledger, CFG), [])

    def test_no_pause_when_profitable(self):
        _, ledger, _, _, _, _ = make([])
        add_sells(ledger, 25, 1.0)
        self.assertEqual(adapt.apply_pause_rules(ledger, CFG), [])

    def test_tuning_needs_enough_trades(self):
        _, ledger, _, _, _, _ = make([])
        add_sells(ledger, 10, 1.0)
        self.assertEqual(adapt.sanitize_changes(CFG, ledger, {"momentum": {"min_h1": 4}}), {})

    def test_changes_are_clamped(self):
        _, ledger, _, _, _, _ = make([])
        add_sells(ledger, 30, 1.0)
        out = adapt.sanitize_changes(
            CFG, ledger, {"momentum": {"min_h1": 100, "h24_max": 5, "unknown": 1}, "evil": {"x": 1}}
        )
        self.assertAlmostEqual(out["momentum"]["min_h1"], 3.75)  # max. +25% von 3
        self.assertAlmostEqual(out["momentum"]["h24_max"], 60.0)  # max. -25% von 80, Grenze 30 unterschritten nicht
        self.assertNotIn("unknown", out["momentum"])
        self.assertNotIn("evil", out)

    def test_commit_and_get_params(self):
        _, ledger, _, _, _, _ = make([])
        adapt.commit_changes(ledger, {"momentum": {"min_h1": 3.75}})
        self.assertEqual(adapt.get_params(CFG, ledger, "momentum")["min_h1"], 3.75)
        self.assertEqual(adapt.get_params(CFG, ledger, "conservative")["min_liq"], 250000)

    def test_review_runs_once_per_interval(self):
        class FakeReviewer:
            calls = 0

            def review(self, stats, params, bounds, regime):
                FakeReviewer.calls += 1
                return {"momentum": {"min_h1": 4}}, "test"

        _, ledger, _, _, _, _ = make([])
        add_sells(ledger, 30, 1.0)
        adapt.run_review(CFG, ledger, {}, FakeReviewer(), NOW)
        adapt.run_review(CFG, ledger, {}, FakeReviewer(), NOW + 3600)
        self.assertEqual(FakeReviewer.calls, 1)
        self.assertEqual(adapt.get_params(CFG, ledger, "momentum")["min_h1"], 3.75)

    def test_stats_include_unrealized_and_fees(self):
        _, ledger, _, ex, _, _ = make([])
        c = cand()
        ex.buy(1, c, 20, now=NOW)
        ledger.set_last_price(c.address, 2.0)
        st = adapt.strategy_stats(ledger)["momentum"]
        self.assertGreater(st["unrealized"], 0)
        self.assertGreater(st["fees"], 0)


if __name__ == "__main__":
    unittest.main()
