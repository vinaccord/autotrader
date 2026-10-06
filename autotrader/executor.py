"""Ausfuehrung. Paper ist implementiert, Live absichtlich nicht."""


class PaperExecutor:
    def __init__(self, ledger, fee_pct, slippage_pct):
        self.ledger = ledger
        self.fee = fee_pct / 100.0
        self.slip = slippage_pct / 100.0

    def buy(self, slot_id, cand, usd, note="", now=None):
        price = cand.price_usd * (1 + self.slip)
        fee = usd * self.fee
        qty = (usd - fee) / price
        with self.ledger.atomic():
            self.ledger.add_cash(slot_id, -usd)
            self.ledger.add_to_position(slot_id, cand.symbol, cand.address, qty, usd, price, ts=now)
            self.ledger.record_trade(slot_id, "buy", cand.symbol, cand.address, qty, price, usd, fee, note=note, ts=now)
        return {"qty": qty, "price": price, "fee": fee}

    def sell(self, pos, price_now, fraction, note="", now=None):
        qty = pos["qty"] * fraction
        price = price_now * (1 - self.slip)
        gross = qty * price
        fee = gross * self.fee
        proceeds = gross - fee
        pnl = proceeds - pos["cost_usd"] * fraction
        with self.ledger.atomic():
            self.ledger.add_cash(pos["slot_id"], proceeds)
            self.ledger.reduce_position(pos["id"], fraction)
            self.ledger.record_trade(
                pos["slot_id"], "sell", pos["symbol"], pos["address"], qty, price, proceeds, fee,
                pnl=pnl, note=note, ts=now,
            )
        return {"qty": qty, "price": price, "pnl": pnl}


class LiveExecutor:
    """Absichtlich nicht implementiert.

    Bevor hier echtes Geld bewegt wird, braucht es mindestens:
    - web3.py plus DEX-Aggregator (0x, 1inch oder ParaSwap), jede Tx vorher per eth_call simuliert
    - Allowlist fuer Router-Adressen, keine unbegrenzten Token-Approvals
    - Schluessel nur aus Umgebungsvariable oder Hardware-/KMS-Signer, nie im Repo
    - Unterwallets per HD-Ableitung aus einem Master-Schluessel, Gelder nur manuell oder per Allowlist verschiebbar
    - Honeypot-Check (Verkauf simulieren), Mindest-Output (minOut) pro Swap
    Erst nach mehreren Wochen Paper-Ergebnissen sinnvoll.
    """

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("Live-Modus ist nicht implementiert. Siehe Docstring in executor.py.")
