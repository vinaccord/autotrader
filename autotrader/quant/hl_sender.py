"""Order senden ueber das offizielle Hyperliquid-SDK (hyperliquid-python-sdk, Version festgenagelt) und Ergebnis auswerten.

Gebaut nach dem SDK-Quelltext (Release 0.24.0, GitHub hyperliquid-dex/hyperliquid-python-sdk, Exchange.order, Cloid, Info.query_order_by_cloid).
In der Build-Umgebung nur mit Fakes getestet, das echte SDK ist dort nicht installierbar. Erster echter Test: Patrick, Kleinstbetrag, nach Freigabe.

Ablauf je Order: erst per orderStatus pruefen, ob die cloid schon gesendet wurde (kein Doppelsenden nach Absturz/Neustart), dann senden
als Limit-Order mit IOC (kein liegenbleibender Rest), Ergebnis protokollieren. Bei Ablehnung oder Fehler werden die restlichen Orders
nicht gesendet (fail-closed). Verkaeufe laufen vor Kaeufen, damit USDC frei ist.
Der Agent-Key kommt nur aus der Umgebungsvariable HL_AGENT_KEY, wird nie protokolliert oder ausgegeben.
"""
import os

SDK_VERSION = "0.24.0"
MAINNET = "https://api.hyperliquid.xyz"
SEND_FIELDS = ["ts", "date", "wallet", "asset", "side", "sz", "limit_px", "usd", "cloid", "status", "reason", "filled_sz", "avg_px", "oid"]


def parse_order_response(resp, requested_sz):
    """SDK-Antwort -> dict(status, oid, filled_sz, avg_px, error). status: filled | partial | resting | rejected | error.

    Erwartete Form: {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"filled": {...}} | {"resting": {...}} | {"error": "..."}]}}}
    oder {"status": "err", "response": "<Text>"}. Alles andere gilt als Fehler (nie als Erfolg raten).
    """
    out = {"status": "error", "oid": None, "filled_sz": 0.0, "avg_px": None, "error": ""}
    try:
        if not isinstance(resp, dict) or resp.get("status") != "ok":
            out["error"] = f"Antwort nicht ok: {str(resp)[:200]}"
            return out
        st = resp["response"]["data"]["statuses"][0]
        if "error" in st:
            out.update(status="rejected", error=str(st["error"])[:200])
        elif "filled" in st:
            f = st["filled"]
            sz = float(f["totalSz"])
            out.update(status="filled" if sz >= requested_sz * 0.999 else "partial", oid=f.get("oid"), filled_sz=sz, avg_px=float(f["avgPx"]))
        elif "resting" in st:
            out.update(status="resting", oid=st["resting"].get("oid"))
        else:
            out["error"] = f"Unbekannter Status: {str(st)[:200]}"
    except (KeyError, IndexError, TypeError, ValueError) as e:
        out["error"] = f"Antwort nicht lesbar ({type(e).__name__})"
    return out


class SdkSender:
    """pairs: Token -> SDK-Name des Spot-Paares (z.B. 'UBTC' -> '@142', aus spotMeta). exchange nur fuer Tests von aussen uebergeben."""

    def __init__(self, pairs, exchange=None, cloid_factory=None):
        self.pairs = dict(pairs)
        if exchange is None:
            exchange, cloid_factory = self._build_from_env()
        self.exchange = exchange
        self.cloid_factory = cloid_factory or (lambda s: s)

    def __repr__(self):
        return "SdkSender(<Schluessel nicht angezeigt>)"

    @staticmethod
    def _build_from_env():
        import importlib.metadata as md

        installed = md.version("hyperliquid-python-sdk")
        if installed != SDK_VERSION:
            raise SystemExit(f"hyperliquid-python-sdk {installed} installiert, festgenagelt ist {SDK_VERSION}.")
        key, address = os.environ.get("HL_AGENT_KEY", ""), os.environ.get("HL_ACCOUNT_ADDRESS", "")
        if not key or not address:
            raise SystemExit("HL_AGENT_KEY und HL_ACCOUNT_ADDRESS muessen in der Umgebung stehen.")
        import eth_account
        from hyperliquid.exchange import Exchange
        from hyperliquid.utils.types import Cloid

        account = eth_account.Account.from_key(key)
        if account.address.lower() == address.lower():
            raise SystemExit("HL_AGENT_KEY gehoert zur Hauptadresse. Erwartet wird ein Agent-Key (kann nicht abheben).")
        return Exchange(account, MAINNET, account_address=address), Cloid.from_str

    def send(self, order):
        name = self.pairs.get(order["asset"])
        if not name:
            return {"status": "error", "oid": None, "filled_sz": 0.0, "avg_px": None, "error": f"kein Spot-Paar fuer {order['asset']}"}
        try:
            resp = self.exchange.order(name, order["side"] == "buy", order["sz"], order["limit_px"], {"limit": {"tif": "Ioc"}},
                                       reduce_only=False, cloid=self.cloid_factory(order["cloid"]))
        except Exception as e:  # Netzwerk, Signatur, SDK: nie still weitermachen
            return {"status": "error", "oid": None, "filled_sz": 0.0, "avg_px": None, "error": f"{type(e).__name__}: {str(e)[:150]}"}
        return parse_order_response(resp, order["sz"])


def already_sent(post, address, cloid):
    """True, wenn Hyperliquid die cloid kennt. post(body) -> JSON. Unklare Antwort gilt als 'bekannt' (lieber nicht senden)."""
    r = post({"type": "orderStatus", "user": address, "oid": cloid})
    if isinstance(r, dict) and r.get("status") == "unknownOid":
        return False
    return True


def execute(orders, sender, post, address, log_rows, log=print):
    """Sendet Orders nacheinander. log_rows(list_of_row_dicts) protokolliert sofort. -> (ergebnisse, abgebrochen: bool)."""
    ordered = sorted(orders, key=lambda o: 0 if o["side"] == "sell" else 1)
    results, aborted = [], False
    for o in ordered:
        row = dict(o, filled_sz="", avg_px="", oid="", reason="")
        if aborted:
            row.update(status="not_sent", reason="vorherige Order fehlgeschlagen")
            log_rows([row])
            continue
        try:
            known = already_sent(post, address, o["cloid"])
        except Exception as e:
            known = None
            row.update(status="error", reason=f"orderStatus nicht lesbar ({type(e).__name__})")
        if known:
            row.update(status="duplicate", reason="cloid bei Hyperliquid bekannt, nicht erneut gesendet")
        elif known is False:
            r = sender.send(o)
            row.update(status=r["status"], reason=r["error"], filled_sz=r["filled_sz"], avg_px=r["avg_px"] or "", oid=r["oid"] or "")
            if r["status"] in ("rejected", "error", "resting"):
                aborted = True
            if r["status"] == "partial":
                log(f"  TEILFUELLUNG {o['asset']}: {r['filled_sz']} von {o['sz']}")
        else:
            aborted = True
        results.append(row)
        log_rows([row])
        log(f"  Order {o['side']} {o['sz']} {o['asset']}: {row['status']} {row['reason']}".rstrip())
    return results, aborted
