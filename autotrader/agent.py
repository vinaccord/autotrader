"""Agent-Loop: Kandidaten holen, Exits pruefen, recherchieren, Risiko pruefen, ausfuehren, Slots abspalten."""
import time
import uuid

from . import adapt
from .security import Regime


class Agent:
    def __init__(self, cfg, ledger, market, researcher, executor, risk, address_factory=None, notify=print,
                 security=None, reviewer=None):
        self.cfg = cfg
        self.ledger = ledger
        self.market = market
        self.researcher = researcher
        self.executor = executor
        self.risk = risk
        self.security = security  # Objekt mit check(address) -> (ok, grund); None = kein Check (nur Tests)
        self.reviewer = reviewer  # optional ClaudeReviewer
        self.regime = Regime(cfg.get("regime", {}))
        self.regime_state = {"risk_off": False}
        self.address_factory = address_factory or (lambda: "paper:" + uuid.uuid4().hex[:12])
        self.notify = notify

    # --- Hilfen --------------------------------------------------------
    def _say(self, level, msg, now=None):
        self.ledger.log(level, msg, ts=now)
        self.notify(f"[{level}] {msg}")

    def init_first_slot(self, now=None):
        if self.ledger.slots():
            return
        cap = self.cfg["start_capital_usd"]
        strat = self.cfg["slots"]["strategies"][0]
        sid = self.ledger.create_slot("slot-1", strat, cap, self.address_factory(), ts=now)
        self.ledger.kv_set("hwm", cap)
        self._say("INFO", f"Slot {sid} ({strat}) mit {cap:.2f} USD angelegt", now)

    def _refresh_prices(self, candidates):
        by_addr = {c.address: c for c in candidates}
        for p in self.ledger.positions():
            addr = p["address"]
            try:
                price = by_addr[addr].price_usd if addr in by_addr else self.market.price(addr)
            except Exception as e:  # Preisquelle faellt aus: letzten Preis behalten
                self._say("WARN", f"Preis fuer {p['symbol']} nicht abrufbar: {e}")
                continue
            if price and price > 0:
                self.ledger.set_last_price(addr, price)

    # --- Tick ----------------------------------------------------------
    def tick(self, now=None):
        now = now or time.time()
        if self.risk.killed():
            self._say("WARN", "Kill-Switch aktiv, Tick uebersprungen", now)
            return
        try:
            candidates = self.market.discover(now)
        except Exception as e:
            self._say("ERROR", f"Marktdaten nicht abrufbar: {e}", now)
            return
        by_addr = {c.address: c for c in candidates}
        self._refresh_prices(candidates)
        if self.risk.check_drawdown():
            return

        self.regime_state = self.regime.assess(candidates)
        if self.regime_state["risk_off"]:
            self._say("INFO", f"Regime risk-off (Breite {self.regime_state['breadth']:.0%}), keine neuen Kaeufe", now)

        for slot in self.ledger.slots():
            sid = slot["id"]
            for pos, fraction, reason in self.risk.exit_actions(sid):
                res = self.executor.sell(pos, pos["last_price"], fraction, note=reason, now=now)
                self._say("TRADE", f"Slot {sid}: SELL {fraction:.0%} {pos['symbol']} ({reason}) PnL {res['pnl']:+.2f}", now)

            slot = self.ledger.slot(sid)
            if adapt.is_paused(self.ledger, slot["strategy"]):
                continue  # pausierte Strategie: nur Exits, keine neuen Entscheidungen
            positions = self.ledger.positions(sid)
            try:
                decisions = self.researcher.decide(slot, candidates, positions)
            except Exception as e:
                self._say("WARN", f"Research fuer Slot {sid} fehlgeschlagen: {e}", now)
                decisions = []
            for d in decisions:
                self._handle(slot, d, by_addr, now)
            self._maybe_spawn(sid, now)

        paused, applied = adapt.run_review(self.cfg, self.ledger, self.regime_state, self.reviewer, now)
        for name in paused:
            self._say("WARN", f"Strategie {name} automatisch pausiert (negatives Netto nach Kosten)", now)
        if applied:
            self._say("INFO", f"Parameter angepasst: {applied}", now)

    def _handle(self, slot, d, by_addr, now):
        sid = slot["id"]
        if d.action == "sell":
            pos = next((p for p in self.ledger.positions(sid) if p["address"] == d.address), None)
            if pos:
                res = self.executor.sell(pos, pos["last_price"], 1.0, note="research: " + d.thesis, now=now)
                self._say("TRADE", f"Slot {sid}: SELL {pos['symbol']} PnL {res['pnl']:+.2f} ({d.thesis})", now)
            return
        if d.action != "buy":
            return
        cand = by_addr.get(d.address)
        if cand is None:
            self._say("WARN", f"Slot {sid}: Token {d.address} nicht in Kandidatenliste, abgelehnt", now)
            return
        if self.regime_state.get("risk_off"):
            return
        want = d.size_usd or round(slot["cash"] * 0.05, 2)
        res = self.risk.check_buy(sid, cand, want, now)
        if not res.ok:
            self._say("SKIP", f"Slot {sid}: {cand.symbol} abgelehnt: {res.reason}", now)
            return
        if self.security is not None:
            ok, why = self.security.check(cand.address)
            if not ok:
                self._say("SKIP", f"Slot {sid}: {cand.symbol} Sicherheitscheck negativ: {why}", now)
                return
        if res.needs_approval:
            aid = self.ledger.add_approval(
                sid, {"cand": cand.to_dict(), "usd": res.usd, "thesis": d.thesis}, ts=now
            )
            self._say("APPROVAL", f"Freigabe #{aid}: Slot {sid} BUY {cand.symbol} {res.usd:.2f} USD ({d.thesis})", now)
            return
        self.executor.buy(sid, cand, res.usd, note=d.thesis, now=now)
        self._say("TRADE", f"Slot {sid}: BUY {cand.symbol} {res.usd:.2f} USD ({d.thesis})", now)

    # --- Freigaben -----------------------------------------------------
    def resolve_approval(self, approval_id, approve, now=None):
        from .models import Candidate
        import json

        now = now or time.time()
        row = self.ledger.approval(approval_id)
        if row is None or row["status"] != "pending":
            return "Freigabe nicht gefunden oder bereits erledigt"
        if not approve:
            self.ledger.set_approval_status(approval_id, "rejected")
            return "abgelehnt"
        ttl = self.cfg["limits"]["approval_ttl_minutes"] * 60
        if now - row["ts"] > ttl:
            self.ledger.set_approval_status(approval_id, "expired")
            return "abgelaufen (Preis zu alt), bitte naechsten Tick abwarten"
        p = json.loads(row["payload"])
        cand = Candidate(**p["cand"])
        res = self.risk.check_buy(row["slot_id"], cand, p["usd"], now, skip_approval=True)
        if not res.ok:
            self.ledger.set_approval_status(approval_id, "rejected")
            return f"Risk-Check negativ: {res.reason}"
        if self.security is not None:
            ok, why = self.security.check(cand.address)
            if not ok:
                self.ledger.set_approval_status(approval_id, "rejected")
                return f"Sicherheitscheck negativ: {why}"
        self.executor.buy(row["slot_id"], cand, res.usd, note="freigegeben: " + p["thesis"], now=now)
        self.ledger.set_approval_status(approval_id, "approved")
        self._say("TRADE", f"Slot {row['slot_id']}: BUY {cand.symbol} {res.usd:.2f} USD (Freigabe #{approval_id})", now)
        return "ausgefuehrt"

    # --- Slots abspalten ----------------------------------------------
    def _maybe_spawn(self, slot_id, now):
        cfg = self.cfg["slots"]
        slots = self.ledger.slots()
        if len(slots) >= cfg["max_slots"]:
            return
        slot = self.ledger.slot(slot_id)
        equity = self.ledger.equity(slot_id)
        if equity < slot["start_value"] * (1 + cfg["spawn_profit_pct"] / 100):
            return
        profit = equity - slot["start_value"]
        move = min(profit * cfg["spawn_fraction"], slot["cash"])
        if move < cfg["min_spawn_usd"]:
            return
        strategies = cfg["strategies"]
        strat = strategies[len(slots) % len(strategies)]
        with self.ledger.atomic():
            new_id = self.ledger.create_slot(
                f"slot-{len(slots) + 1}", strat, move, self.address_factory(), parent_id=slot_id, ts=now
            )
            self.ledger.add_cash(slot_id, -move)
            self.ledger.set_start_value(slot_id, equity - move)
        self._say("SPAWN", f"Slot {slot_id} gewinnt {profit:.2f} USD, neuer Slot {new_id} ({strat}) mit {move:.2f} USD", now)
