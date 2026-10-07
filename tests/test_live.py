import copy
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from autotrader.quant import hl_live, hl_sender  # noqa: E402
from test_quant import QCFG, synth_market  # noqa: E402

FILLED = {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"filled": {"totalSz": "0.01", "avgPx": "80100.0", "oid": 77}}]}}}


def order(side="buy", sz=0.01, cloid="0x" + "a" * 32, asset="UBTC"):
    return {"asset": asset, "side": side, "sz": sz, "limit_px": 80200.0, "usd": sz * 80000, "cloid": cloid}


class ParseTests(unittest.TestCase):
    def test_filled_partial_resting_error(self):
        r = hl_sender.parse_order_response(FILLED, 0.01)
        self.assertEqual((r["status"], r["oid"], r["filled_sz"], r["avg_px"]), ("filled", 77, 0.01, 80100.0))
        self.assertEqual(hl_sender.parse_order_response(FILLED, 0.02)["status"], "partial")
        rest = {"status": "ok", "response": {"data": {"statuses": [{"resting": {"oid": 5}}]}}}
        self.assertEqual(hl_sender.parse_order_response(rest, 1)["status"], "resting")
        rej = {"status": "ok", "response": {"data": {"statuses": [{"error": "Insufficient balance"}]}}}
        r = hl_sender.parse_order_response(rej, 1)
        self.assertEqual((r["status"], r["error"]), ("rejected", "Insufficient balance"))

    def test_anything_unexpected_is_error_not_success(self):
        for bad in (None, "x", {}, {"status": "err", "response": "boom"}, {"status": "ok"}, {"status": "ok", "response": {"data": {"statuses": []}}},
                    {"status": "ok", "response": {"data": {"statuses": [{"weird": 1}]}}}, {"status": "ok", "response": {"data": {"statuses": [{"filled": {"totalSz": "x"}}]}}}):
            self.assertEqual(hl_sender.parse_order_response(bad, 1)["status"], "error", bad)


class FakeExchange:
    def __init__(self, resp=FILLED, exc=None):
        self.calls, self.resp, self.exc = [], resp, exc

    def order(self, name, is_buy, sz, limit_px, order_type, reduce_only=False, cloid=None):
        self.calls.append((name, is_buy, sz, limit_px, order_type, reduce_only, cloid))
        if self.exc:
            raise self.exc
        return self.resp


class SenderTests(unittest.TestCase):
    def test_sends_ioc_limit_with_pair_name_and_cloid(self):
        ex = FakeExchange()
        s = hl_sender.SdkSender({"UBTC": "@142"}, exchange=ex)
        r = s.send(order())
        self.assertEqual(r["status"], "filled")
        name, is_buy, sz, px, ot, ro, cl = ex.calls[0]
        self.assertEqual((name, is_buy, sz, px, ot, ro), ("@142", True, 0.01, 80200.0, {"limit": {"tif": "Ioc"}}, False))
        self.assertEqual(cl, "0x" + "a" * 32)

    def test_exception_and_unknown_asset_become_errors(self):
        s = hl_sender.SdkSender({"UBTC": "@142"}, exchange=FakeExchange(exc=ConnectionError("down")))
        self.assertEqual(s.send(order())["status"], "error")
        self.assertEqual(s.send(order(asset="XYZ"))["status"], "error")

    def test_repr_hides_secrets(self):
        self.assertNotIn("0x", repr(hl_sender.SdkSender({}, exchange=FakeExchange())))


class FakeSender:
    def __init__(self, results):
        self.sent, self.results = [], list(results)

    def send(self, o):
        self.sent.append(o["cloid"])
        return self.results.pop(0)


OK = {"status": "filled", "oid": 1, "filled_sz": 0.01, "avg_px": 80000.0, "error": ""}
REJ = {"status": "rejected", "oid": None, "filled_sz": 0.0, "avg_px": None, "error": "nope"}
UNKNOWN = {"status": "unknownOid"}


class ExecuteTests(unittest.TestCase):
    def run_exec(self, orders, sender, post):
        rows = []
        res, aborted = hl_sender.execute(orders, sender, post, "0xabc", rows.extend, lambda *_: None)
        return res, aborted, rows

    def test_sells_before_buys(self):
        sender = FakeSender([OK, OK])
        o_buy, o_sell = order("buy", cloid="0x" + "1" * 32), order("sell", cloid="0x" + "2" * 32)
        self.run_exec([o_buy, o_sell], sender, lambda b: UNKNOWN)
        self.assertEqual(sender.sent, ["0x" + "2" * 32, "0x" + "1" * 32])

    def test_known_cloid_is_not_sent_again(self):
        sender = FakeSender([])
        res, aborted, rows = self.run_exec([order()], sender, lambda b: {"status": "order", "order": {}})
        self.assertEqual((sender.sent, res[0]["status"], aborted), ([], "duplicate", False))

    def test_rejection_stops_remaining_orders(self):
        sender = FakeSender([REJ, OK])
        a, b = order(cloid="0x" + "1" * 32), order(cloid="0x" + "2" * 32)
        res, aborted, rows = self.run_exec([a, b], sender, lambda x: UNKNOWN)
        self.assertTrue(aborted)
        self.assertEqual(len(sender.sent), 1)
        self.assertEqual([r["status"] for r in rows], ["rejected", "not_sent"])

    def test_unreadable_order_status_sends_nothing_and_aborts(self):
        def post(b):
            raise ConnectionError("x")

        sender = FakeSender([OK])
        res, aborted, rows = self.run_exec([order()], sender, post)
        self.assertEqual((sender.sent, aborted, res[0]["status"]), ([], True, "error"))

    def test_already_sent_unclear_answer_counts_as_known(self):
        self.assertTrue(hl_sender.already_sent(lambda b: None, "0xabc", "0x1"))
        self.assertFalse(hl_sender.already_sent(lambda b: UNKNOWN, "0xabc", "0x1"))


class GateTests(unittest.TestCase):
    TODAY = dt.date(2026, 12, 1)
    ENV = {"HL_AGENT_KEY": "k", "HL_ACCOUNT_ADDRESS": "0xabc"}

    def plan(self, **kw):
        return {"mode": "live", "live": {"armed_until": "2026-12-01"}, **kw}

    def test_all_open(self):
        self.assertEqual(hl_live.check_gates(self.plan(), True, self.ENV, self.TODAY), [])

    def test_each_gate_blocks(self):
        self.assertTrue(hl_live.check_gates(dict(self.plan(), mode="dry-run"), True, self.ENV, self.TODAY))
        self.assertTrue(hl_live.check_gates(self.plan(), False, self.ENV, self.TODAY))
        self.assertTrue(hl_live.check_gates(self.plan(), True, {"HL_ACCOUNT_ADDRESS": "x"}, self.TODAY))
        self.assertTrue(hl_live.check_gates(self.plan(), True, {"HL_AGENT_KEY": "x"}, self.TODAY))
        self.assertTrue(hl_live.check_gates({"mode": "live", "live": {"armed_until": None}}, True, self.ENV, self.TODAY))
        self.assertTrue(hl_live.check_gates({"mode": "live"}, True, self.ENV, self.TODAY))
        self.assertTrue(hl_live.check_gates({"mode": "live", "live": {"armed_until": "2026-11-30"}}, True, self.ENV, self.TODAY))

    def test_repo_plan_is_not_armed(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "live_plan.yaml"), encoding="utf-8") as f:
            import yaml

            plan = yaml.safe_load(f)
        self.assertEqual(plan["mode"], "dry-run")
        self.assertIsNone(plan["live"]["armed_until"])
        self.assertTrue(hl_live.check_gates(plan, True, self.ENV, self.TODAY))

    def test_main_exits_before_any_network(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "plan.yaml")
            with open(p, "w") as f:
                f.write("mode: dry-run\n")
            with self.assertRaises(SystemExit) as cm:
                hl_live.main(["--plan", p, "--confirm-real-money"], env={})
            self.assertIn("Keine Orders", str(cm.exception))


class R:
    status_code = 200

    def __init__(self, j):
        self.j = j

    def raise_for_status(self):
        pass

    def json(self):
        return self.j


class LiveRunTests(unittest.TestCase):
    def setUp(self):
        from autotrader.quant import hl_exec as h, pipeline as pl

        self.h = h
        self.dates, ohlc, fund = synth_market(1300)
        self.last = ohlc[self.dates[-1]][3]
        self.cfg = copy.deepcopy(QCFG)
        self.cfg["coins"] = ["BTC"]
        self.cfg["data_dir"] = tempfile.mkdtemp()
        dates = self.dates
        self.orig = (h.data.load_all, pl.signal)
        self.pl = pl
        h.data.load_all = lambda c: (dates, {"BTC": ohlc}, {"BTC": fund})
        pl.signal = lambda cfg_, d, o, f, r: {"as_of": dates[-1], "trend": {"BTC": {"target_exposure": 0.8}}, "carry": {"BTC": {"in_position": False, "trailing_apr": 0.0}}, "weights": {"trend": 0.7, "carry": 0.3}}
        self.plan = {"mode": "live", "live": {"armed_until": "2099-01-01", "max_equity_usdc": 3000},
                     "kill_switch": {"warn_dd": 0.2, "brake_dd": 0.3, "brake_release_dd": 0.2, "stop_dd": 0.4, "stop_below_deposits": 0.6, "global_stop_dd": 0.4},
                     "safety": {"max_data_age_hours": 36, "max_source_divergence": 0.03, "unit_token_max_deviation": 0.02, "usdc_depeg_floor": 0.98,
                                "max_order_frac": 0.25, "max_daily_turnover_frac": 1.0, "max_slippage_bps": 30, "max_position_mismatch": 0.05},
                     "venue": {"fees_bps": {"spot_taker": 7.0}}}
        self.now = dt.datetime.fromisoformat(dates[-1]).replace(tzinfo=dt.timezone.utc) + dt.timedelta(days=1, hours=1)

    def tearDown(self):
        self.h.data.load_all, self.pl.signal = self.orig

    def session(self, usdc, state, fills_update):
        last, dates, h = self.last, self.dates, self.h

        class S:
            def request(s, method, url, timeout=0, json=None, params=None, **kw):
                if "coingecko" in url:
                    return R({"usd-coin": {"usd": 1.0}})
                t = json["type"]
                if t == "spotMetaAndAssetCtxs":
                    return R([{"tokens": [{"name": "USDC", "index": 0, "szDecimals": 8}, {"name": "UBTC", "index": 1, "szDecimals": 5}],
                               "universe": [{"name": "@10", "tokens": [1, 0], "index": 0}]}, [{"dayNtlVlm": "1"}]])
                if t == "allMids":
                    return R({"@10": str(last), "BTC": str(last)})
                if t == "candleSnapshot":
                    return R([{"t": h.data.ms(dates[-1]), "o": last, "h": last, "l": last, "c": str(last), "v": 1}])
                if t == "spotClearinghouseState":
                    return R({"balances": [{"coin": "USDC", "total": str(state["usdc"])}, {"coin": "UBTC", "total": str(state["ubtc"])}]})
                if t == "clearinghouseState":
                    return R({"marginSummary": {"accountValue": str(state.get("perp", 0.0))}})
                if t == "orderStatus":
                    return R({"status": "order", "order": {}} if json["oid"] in state["seen"] else {"status": "unknownOid"})
                raise AssertionError(t)

        return S()

    def test_live_run_sends_orders_logs_and_reconciles(self):
        state = {"usdc": 1000.0, "ubtc": 0.0, "seen": set()}

        class Sender:
            def send(s, o):
                state["seen"].add(o["cloid"])
                state["usdc"] -= o["usd"]
                state["ubtc"] += o["sz"]
                return {"status": "filled", "oid": 1, "filled_sz": o["sz"], "avg_px": o["limit_px"], "error": ""}

        out = self.h.run(self.cfg, self.plan, session=self.session(1000, state, None), now=self.now, log=lambda *_: None, address="0xabc", sender=Sender())
        self.assertFalse(out["blocked"])
        self.assertTrue(out["orders"])
        self.assertEqual(out["live"]["mismatch"], [])
        self.assertFalse(out["live"]["aborted"])
        self.assertTrue(os.path.exists(os.path.join(self.cfg["data_dir"], "orders_live.csv")))
        self.assertFalse(os.path.exists(os.path.join(self.cfg["data_dir"], "orders_dryrun.csv")))
        self.assertTrue(os.path.exists(os.path.join(self.cfg["data_dir"], "killswitch_A_live.json")))
        self.assertFalse(os.path.exists(os.path.join(self.cfg["data_dir"], "paper_account_A.json")))
        # zweiter Lauf am selben Tag: Konto steht schon auf dem Ziel, nichts Neues
        again = self.h.run(self.cfg, self.plan, session=self.session(0, state, None), now=self.now, log=lambda *_: None, address="0xabc", sender=Sender())
        self.assertEqual(again["orders"], [])

    def test_mismatch_is_reported_when_fills_do_not_show_in_account(self):
        state = {"usdc": 1000.0, "ubtc": 0.0, "seen": set()}

        class Sender:
            def send(s, o):  # Fill gemeldet, Konto aendert sich aber nicht
                return {"status": "filled", "oid": 1, "filled_sz": o["sz"], "avg_px": o["limit_px"], "error": ""}

        out = self.h.run(self.cfg, self.plan, session=self.session(1000, state, None), now=self.now, log=lambda *_: None, address="0xabc", sender=Sender())
        self.assertTrue(out["live"]["mismatch"])

    def test_rejection_aborts_and_reports(self):
        state = {"usdc": 1000.0, "ubtc": 0.0, "seen": set()}

        class Sender:
            def send(s, o):
                return {"status": "rejected", "oid": None, "filled_sz": 0.0, "avg_px": None, "error": "nope"}

        out = self.h.run(self.cfg, self.plan, session=self.session(1000, state, None), now=self.now, log=lambda *_: None, address="0xabc", sender=Sender())
        self.assertTrue(out["live"]["aborted"])

    def test_equity_above_cap_blocks_orders(self):
        state = {"usdc": 5000.0, "ubtc": 0.0, "seen": set()}

        class Sender:
            def send(s, o):
                raise AssertionError("darf nicht senden")

        out = self.h.run(self.cfg, self.plan, session=self.session(5000, state, None), now=self.now, log=lambda *_: None, address="0xabc", sender=Sender())
        self.assertTrue(out["blocked"])
        self.assertTrue(any("Obergrenze" in v for v in out["violations"]))

    def test_usdc_in_perp_account_blocks_with_clear_message(self):
        state = {"usdc": 0.0, "ubtc": 0.0, "perp": 1000.0, "seen": set()}

        class Sender:
            def send(s, o):
                raise AssertionError("darf nicht senden")

        out = self.h.run(self.cfg, self.plan, session=self.session(0, state, None), now=self.now, log=lambda *_: None, address="0xabc", sender=Sender())
        self.assertTrue(any("Perp-Konto" in v for v in out["violations"]))
        self.assertTrue(out["blocked"])

    def test_unified_account_same_value_in_both_is_not_flagged(self):
        state = {"usdc": 1000.0, "ubtc": 0.0, "perp": 1000.0, "seen": set()}

        class Sender:
            def send(s, o):
                state["usdc"] -= o["usd"]
                state["ubtc"] += o["sz"]
                return {"status": "filled", "oid": 1, "filled_sz": o["sz"], "avg_px": o["limit_px"], "error": ""}

        out = self.h.run(self.cfg, self.plan, session=self.session(1000, state, None), now=self.now, log=lambda *_: None, address="0xabc", sender=Sender())
        self.assertFalse(any("Perp-Konto" in v for v in out["violations"]))

    def test_old_data_blocks_live_orders(self):
        state = {"usdc": 1000.0, "ubtc": 0.0, "seen": set()}

        class Sender:
            def send(s, o):
                raise AssertionError("darf nicht senden")

        out = self.h.run(self.cfg, self.plan, session=self.session(1000, state, None), now=self.now + dt.timedelta(days=5), log=lambda *_: None, address="0xabc", sender=Sender())
        self.assertTrue(out["blocked"])

    def test_mode_and_sender_must_match(self):
        class Sender:
            def send(s, o):
                raise AssertionError

        state = {"usdc": 1000.0, "ubtc": 0.0, "seen": set()}
        sess = self.session(1000, state, None)
        with self.assertRaises(SystemExit):
            self.h.run(self.cfg, dict(self.plan, mode="dry-run"), session=sess, now=self.now, log=lambda *_: None, address="0xabc", sender=Sender())
        with self.assertRaises(SystemExit):
            self.h.run(self.cfg, self.plan, session=sess, now=self.now, log=lambda *_: None)
        with self.assertRaises(SystemExit):
            self.h.run(self.cfg, self.plan, session=sess, now=self.now, log=lambda *_: None, address=None, sender=Sender())


if __name__ == "__main__":
    unittest.main()


class KillSwitchCliTests(unittest.TestCase):
    def setUp(self):
        from autotrader.quant import killswitch as k

        self.k = k
        self.t = tempfile.mkdtemp()
        self.cfgp = os.path.join(self.t, "c.yaml")
        with open(self.cfgp, "w") as f:
            f.write("data_dir: data\n")
        os.makedirs(os.path.join(self.t, "data"))
        self.sp = os.path.join(self.t, "data", "killswitch_A_live.json")
        k.save(self.sp, k.new_state(1000))
        self.lines = []

    def call(self, *args):
        return self.k.cli(["--config", self.cfgp, *args], out=self.lines.append)

    def test_status_missing_state_exits(self):
        os.remove(self.sp)
        with self.assertRaises(SystemExit):
            self.call("status")

    def test_deposit_preview_does_not_change_state_confirm_does(self):
        self.call("flow", "--amount", "500")
        self.assertEqual(self.k.load(self.sp)["deposits"], 1000)
        self.call("flow", "--amount", "500", "--confirm")
        st = self.k.load(self.sp)
        self.assertEqual((st["hwm"], st["deposits"]), (1500, 1500))
        self.assertTrue(os.path.exists(os.path.join(self.t, "data", "killswitch_flows.csv")))

    def test_withdrawal_needs_equity_and_scales_hwm(self):
        with self.assertRaises(SystemExit):
            self.call("flow", "--amount", "-200", "--confirm")
        self.call("flow", "--amount", "-200", "--equity-before", "1000", "--confirm")
        st = self.k.load(self.sp)
        self.assertAlmostEqual(st["hwm"], 800)
        self.assertAlmostEqual(st["deposits"], 800)
        # Auszahlung loest keinen Verlust aus
        s, info = self.k.evaluate(st, 800, {"warn_dd": 0.2, "brake_dd": 0.3, "brake_release_dd": 0.2, "stop_dd": 0.4, "stop_below_deposits": 0.6, "global_stop_dd": 0.4})
        self.assertEqual(info["level"], "normal")

    def test_withdrawal_larger_than_equity_refused(self):
        with self.assertRaises(SystemExit):
            self.call("flow", "--amount", "-1000", "--equity-before", "900", "--confirm")

    def test_reset_only_after_stop_and_with_confirm(self):
        with self.assertRaises(SystemExit):
            self.call("reset", "--equity", "700", "--confirm")
        st = self.k.load(self.sp)
        st["level"] = "stop"
        self.k.save(self.sp, st)
        self.call("reset", "--equity", "700")
        self.assertEqual(self.k.load(self.sp)["level"], "stop")
        with self.assertRaises(SystemExit):
            self.call("reset", "--confirm")
        self.call("reset", "--equity", "700", "--confirm")
        st = self.k.load(self.sp)
        self.assertEqual((st["level"], st["hwm"]), ("normal", 700))


class ProtectionCheckTests(unittest.TestCase):
    def test_all_scenarios_pass_with_repo_plan(self):
        from autotrader.quant import protection_check as pc

        lines = []
        rc = pc.main(["--plan", os.path.join(os.path.dirname(__file__), "..", "live_plan.yaml")], out=lines.append)
        self.assertEqual(rc, 0, "\n".join(lines))
        text = "\n".join(lines)
        for level in ("warn", "brake", "stop"):
            self.assertIn(f"erhalten {level}", text)
        self.assertGreaterEqual(text.count("erwartet Verstoss, erhalten Verstoss"), 6)

    def test_loosened_threshold_is_detected(self):
        import yaml
        from autotrader.quant import protection_check as pc

        with open(os.path.join(os.path.dirname(__file__), "..", "live_plan.yaml"), encoding="utf-8") as f:
            plan = yaml.safe_load(f)
        plan["safety"]["max_data_age_hours"] = 500
        plan["kill_switch"]["stop_dd"] = 0.9
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, "plan.yaml")
            with open(p, "w") as f:
                yaml.safe_dump(plan, f)
            lines = []
            rc = pc.main(["--plan", p], out=lines.append)
        self.assertEqual(rc, 1)
        self.assertTrue(any(l.strip().startswith("FAIL") for l in lines))


class AlertTests(unittest.TestCase):
    def test_alert_text_cases_and_no_amounts(self):
        self.assertIsNone(hl_live.alert_text({"live": {"aborted": False, "mismatch": []}, "blocked": False, "orders": []}))
        self.assertIn("fehlgeschlagen", hl_live.alert_text({"live": {"aborted": True}}))
        self.assertIn("Abweichung", hl_live.alert_text({"live": {"mismatch": ["UBTC: 20.0% (1234 USD)"]}}))
        t = hl_live.alert_text({"live": {}, "blocked": True, "orders": [1], "violations": ["Daten 73 h alt (max. 36 h)"]})
        self.assertIn("blockiert", t)
        self.assertNotIn("1234", hl_live.alert_text({"live": {"mismatch": ["UBTC: 20.0% (1234 USD)"]}}))

    def test_notify_posts_to_topic_and_survives_errors(self):
        calls = []
        self.assertTrue(hl_live.notify({"NTFY_TOPIC": "abc"}, "T", "B", post=lambda url, **kw: calls.append((url, kw))))
        self.assertEqual(calls[0][0], "https://ntfy.sh/abc")
        self.assertFalse(hl_live.notify({}, "T", "B", post=lambda *a, **k: calls.append(1)))

        def boom(*a, **k):
            raise hl_live.requests.ConnectionError("x")

        self.assertFalse(hl_live.notify({"NTFY_TOPIC": "abc"}, "T", "B", post=boom))
