import copy
import os
import sys
import unittest

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from autotrader.agent import Agent
from autotrader.db import Ledger
from autotrader.executor import PaperExecutor
from autotrader.market import FakeProvider
from autotrader.models import Candidate, Decision
from autotrader.research import RuleResearcher, parse_decisions
from autotrader.risk import RiskEngine

with open(os.path.join(os.path.dirname(__file__), "..", "config.yaml"), encoding="utf-8") as f:
    CFG = yaml.safe_load(f)

NOW = 1_800_000_000.0


def cand(addr="0xaaa", sym="AAA", price=1.0, liq=500_000, vol=200_000, h1=5, h24=20, age=500):
    return Candidate(sym, addr, price, liq, vol, h1, h24, age)


def make(cands, researcher=None, cfg=None):
    cfg = cfg or copy.deepcopy(CFG)
    ledger = Ledger(":memory:")
    market = FakeProvider(cands)
    ex = PaperExecutor(ledger, cfg["paper"]["fee_pct"], cfg["paper"]["slippage_pct"])
    risk = RiskEngine(cfg["limits"], ledger)
    agent = Agent(cfg, ledger, market, researcher or RuleResearcher(), ex, risk, notify=lambda m: None)
    agent.init_first_slot(NOW)
    return cfg, ledger, market, ex, risk, agent


class Fixed:
    def __init__(self, decisions):
        self.decisions = decisions

    def decide(self, slot, candidates, positions):
        return self.decisions


class RiskTests(unittest.TestCase):
    def test_rejects_illiquid_and_young(self):
        _, ledger, _, _, risk, _ = make([])
        self.assertFalse(risk.check_buy(1, cand(liq=1000), 20, NOW).ok)
        self.assertFalse(risk.check_buy(1, cand(age=3), 20, NOW).ok)
        self.assertFalse(risk.check_buy(1, cand(vol=100), 20, NOW).ok)

    def test_size_is_clipped_to_max_trade(self):
        _, _, _, _, risk, _ = make([])
        res = risk.check_buy(1, cand(), 10_000, NOW)
        self.assertTrue(res.ok)
        self.assertEqual(res.usd, CFG["limits"]["max_trade_usd"])
        self.assertTrue(res.needs_approval)

    def test_small_trade_is_autonomous(self):
        _, _, _, _, risk, _ = make([])
        res = risk.check_buy(1, cand(), 20, NOW)
        self.assertTrue(res.ok and not res.needs_approval)

    def test_daily_limit(self):
        _, ledger, _, ex, risk, _ = make([])
        for i in range(3):
            ex.buy(1, cand(addr=f"0x{i}", sym=f"T{i}"), 50, now=NOW)
        res = risk.check_buy(1, cand(addr="0xnew"), 50, NOW)
        self.assertFalse(res.ok)
        self.assertIn("Tageslimit", res.reason)

    def test_token_concentration_cap(self):
        _, _, _, ex, risk, _ = make([])
        c = cand()
        ex.buy(1, c, 50, now=NOW)
        ex.buy(1, c, 50, now=NOW)
        ex.buy(1, c, 50, now=NOW)
        # Cap: 25% von ~1000 = ~250, nach 150 sind rund 100 Raum, aber Tageslimit 150 ist erreicht
        self.assertFalse(risk.check_buy(1, c, 50, NOW).ok)

    def test_kill_switch_blocks(self):
        _, ledger, _, _, risk, _ = make([])
        ledger.kv_set("killed", "1")
        self.assertFalse(risk.check_buy(1, cand(), 20, NOW).ok)

    def test_exits(self):
        _, ledger, _, ex, risk, _ = make([])
        c = cand()
        ex.buy(1, c, 20, now=NOW)
        ledger.set_last_price(c.address, 0.8)  # -20% inkl. Slippage
        acts = risk.exit_actions(1)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0][1], 1.0)
        ledger.set_last_price(c.address, 2.0)
        acts = risk.exit_actions(1)
        self.assertEqual(acts[0][1], 0.5)

    def test_drawdown_kill(self):
        _, ledger, _, _, risk, _ = make([])
        ledger.kv_set("hwm", 1000)
        ledger.add_cash(1, -400)  # Equity 600, DD 40%
        self.assertTrue(risk.check_drawdown())
        self.assertEqual(ledger.kv_get("killed"), "1")


class ExecutorTests(unittest.TestCase):
    def test_buy_sell_roundtrip_costs_fees(self):
        _, ledger, _, ex, _, _ = make([])
        c = cand()
        before = ledger.equity(1)
        ex.buy(1, c, 100, now=NOW)
        pos = ledger.positions(1)[0]
        ex.sell(pos, c.price_usd, 1.0, now=NOW)
        after = ledger.equity(1)
        self.assertLess(after, before)
        self.assertGreater(after, before - 3)  # Gebuehren plus Slippage, wenige USD
        self.assertEqual(len(ledger.positions(1)), 0)


class AgentTests(unittest.TestCase):
    def test_tick_buys_with_rules(self):
        c = cand(h1=5, h24=20)
        cfg = copy.deepcopy(CFG)
        _, ledger, _, _, _, agent = make([c], cfg=cfg)
        agent.tick(NOW)
        # Momentum-Slot kauft, 5% von 1000 = 50 -> braucht Freigabe
        self.assertEqual(len(ledger.positions(1)), 0)
        self.assertEqual(len(ledger.pending_approvals()), 1)

    def test_approval_executes(self):
        c = cand()
        _, ledger, _, _, _, agent = make([c])
        agent.tick(NOW)
        aid = ledger.pending_approvals()[0]["id"]
        self.assertEqual(agent.resolve_approval(aid, True, NOW + 60), "ausgefuehrt")
        self.assertEqual(len(ledger.positions(1)), 1)

    def test_approval_expires(self):
        c = cand()
        _, ledger, _, _, _, agent = make([c])
        agent.tick(NOW)
        aid = ledger.pending_approvals()[0]["id"]
        msg = agent.resolve_approval(aid, True, NOW + 3 * 3600)
        self.assertIn("abgelaufen", msg)
        self.assertEqual(len(ledger.positions(1)), 0)

    def test_unknown_token_from_researcher_is_rejected(self):
        c = cand()
        r = Fixed([Decision("buy", "0xevil", "EVIL", 500, "to the moon")])
        _, ledger, _, _, _, agent = make([c], researcher=r)
        agent.tick(NOW)
        self.assertEqual(len(ledger.positions(1)), 0)
        self.assertEqual(len(ledger.pending_approvals()), 0)

    def test_stop_loss_runs_in_tick(self):
        c = cand()
        r = Fixed([])
        _, ledger, market, ex, _, agent = make([c], researcher=r)
        ex.buy(1, c, 20, now=NOW)
        market.set_price(c.address, 0.7)
        agent.tick(NOW + 900)
        self.assertEqual(len(ledger.positions(1)), 0)

    def test_spawn_new_slot_on_profit(self):
        c = cand()
        r = Fixed([])
        cfg = copy.deepcopy(CFG)
        _, ledger, market, ex, _, agent = make([c], researcher=r, cfg=cfg)
        ledger.add_cash(1, 400)  # simuliert +40% Gewinn (start_value 1000, Equity 1400)
        before = ledger.total_equity()
        agent.tick(NOW)
        slots = ledger.slots()
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[1]["parent_id"], 1)
        self.assertAlmostEqual(slots[1]["cash"], 200.0)
        self.assertAlmostEqual(ledger.total_equity(), before)  # Summe bleibt gleich
        # kein sofortiger zweiter Spawn
        agent.tick(NOW + 900)
        self.assertEqual(len(ledger.slots()), 2)

    def test_max_slots_respected(self):
        c = cand()
        cfg = copy.deepcopy(CFG)
        cfg["slots"]["max_slots"] = 1
        _, ledger, _, _, _, agent = make([c], researcher=Fixed([]), cfg=cfg)
        ledger.add_cash(1, 400)
        agent.tick(NOW)
        self.assertEqual(len(ledger.slots()), 1)

    def test_kill_switch_stops_tick(self):
        c = cand()
        _, ledger, _, _, _, agent = make([c])
        ledger.kv_set("killed", "1")
        agent.tick(NOW)
        self.assertEqual(len(ledger.pending_approvals()), 0)


class ResearchParsingTests(unittest.TestCase):
    def test_parses_valid_json_with_noise(self):
        text = 'Hier meine Analyse: {"decisions":[{"action":"buy","address":"0xAAA","size_usd":30,"thesis":"ok","confidence":0.7}]} Ende'
        out = parse_decisions(text, {"0xaaa"})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].size_usd, 30)

    def test_drops_unknown_addresses_and_bad_actions(self):
        text = '{"decisions":[{"action":"buy","address":"0xevil","size_usd":999},{"action":"transfer","address":"0xaaa"}]}'
        self.assertEqual(parse_decisions(text, {"0xaaa"}), [])

    def test_garbage_returns_empty(self):
        self.assertEqual(parse_decisions("kein json", {"0xaaa"}), [])
        self.assertEqual(parse_decisions("{kaputt", {"0xaaa"}), [])


if __name__ == "__main__":
    unittest.main()
