"""Risiko-Engine. Gilt fuer jede Entscheidung, egal ob Regel-Logik oder LLM.

Das LLM kann Vorschlaege machen, die Limits hier kann es nicht umgehen.
"""
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class RiskResult:
    ok: bool
    usd: float = 0.0
    reason: str = ""
    needs_approval: bool = False


def start_of_utc_day(ts):
    d = datetime.fromtimestamp(ts, tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return d.timestamp()


class RiskEngine:
    def __init__(self, limits, ledger):
        self.l = limits
        self.ledger = ledger

    def killed(self):
        return self.ledger.kv_get("killed", "0") == "1"

    def check_buy(self, slot_id, cand, usd, now, skip_approval=False):
        L = self.l
        if self.killed():
            return RiskResult(False, reason="Kill-Switch aktiv")
        if cand.price_usd <= 0:
            return RiskResult(False, reason="ungueltiger Preis")
        if cand.liquidity_usd < L["min_liquidity_usd"]:
            return RiskResult(False, reason=f"Liquiditaet {cand.liquidity_usd:.0f} < {L['min_liquidity_usd']}")
        if cand.volume_24h_usd < L["min_volume_24h_usd"]:
            return RiskResult(False, reason=f"Volumen 24h {cand.volume_24h_usd:.0f} zu tief")
        if cand.age_hours < L["min_pool_age_hours"]:
            return RiskResult(False, reason=f"Pool zu jung ({cand.age_hours:.0f}h)")

        slot = self.ledger.slot(slot_id)
        positions = self.ledger.positions(slot_id)
        existing = next((p for p in positions if p["address"] == cand.address), None)
        if existing is None and len(positions) >= L["max_open_positions_per_slot"]:
            return RiskResult(False, reason="max. offene Positionen erreicht")

        equity = self.ledger.equity(slot_id)
        exposure = existing["qty"] * existing["last_price"] if existing else 0.0
        room_token = L["max_token_pct_of_slot"] * equity - exposure
        daily_left = L["max_daily_usd"] - self.ledger.buys_usd_since(start_of_utc_day(now))
        impact_cap = cand.liquidity_usd * L["max_trade_pct_of_liquidity"]

        allowed = min(usd, L["max_trade_usd"], slot["cash"], room_token, daily_left, impact_cap)
        if allowed < L["min_trade_usd"]:
            return RiskResult(
                False,
                reason=(
                    f"erlaubte Groesse {allowed:.2f} < Minimum {L['min_trade_usd']} "
                    f"(cash {slot['cash']:.2f}, Token-Raum {room_token:.2f}, Tageslimit-Rest {daily_left:.2f})"
                ),
            )
        needs = (not skip_approval) and allowed > L["approval_above_usd"]
        return RiskResult(True, usd=allowed, needs_approval=needs, reason="ok")

    def exit_actions(self, slot_id):
        """Liefert (position, anteil, grund) fuer Stop-Loss und Teil-Take-Profit."""
        out = []
        for p in self.ledger.positions(slot_id):
            pnl_pct = (p["last_price"] / p["entry_price"] - 1) * 100
            if pnl_pct <= -self.l["stop_loss_pct"]:
                out.append((p, 1.0, f"stop_loss {pnl_pct:.1f}%"))
            elif pnl_pct >= self.l["take_profit_pct"] and not p["tp_done"]:
                out.append((p, 0.5, f"take_profit {pnl_pct:.1f}%"))
        return out

    def check_drawdown(self):
        """Globaler Kill-Switch bei Drawdown ueber der Hoechstmarke."""
        total = self.ledger.total_equity()
        hwm = float(self.ledger.kv_get("hwm", total))
        if total > hwm:
            hwm = total
        self.ledger.kv_set("hwm", hwm)
        dd = (1 - total / hwm) * 100 if hwm > 0 else 0.0
        if dd >= self.l["max_drawdown_pct"]:
            self.ledger.kv_set("killed", "1")
            self.ledger.log("ERROR", f"Kill-Switch: Drawdown {dd:.1f}% (Gesamt {total:.2f}, Hoechst {hwm:.2f})")
            return True
        return False
