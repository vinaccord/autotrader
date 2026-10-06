"""Token-Sicherheitscheck vor jedem Kauf (fail-closed) und einfacher Regime-Filter.

Hintergrund: Studien zu neuen DEX-Tokens finden extrem hohe Honeypot-Anteile. Ein Token, das sich
nicht verkaufen laesst, zeigt im Paper-Trading Scheingewinne. Darum zaehlt: keine Daten = kein Kauf.

Hinweis: GoPlus-Feldnamen sind nach der oeffentlichen Doku geschrieben, aber nicht live getestet
(Netzwerk in der Build-Umgebung gesperrt). Beim ersten Lauf mit einem bekannten Token pruefen.
"""
import statistics

import requests

GOPLUS = "https://api.gopluslabs.io/api/v1/token_security/{chain_id}"
CHAIN_IDS = {"eth": 1, "base": 8453, "arbitrum": 42161, "bsc": 56, "polygon_pos": 137}


def _f(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def evaluate_goplus(info, max_tax=0.05, min_holders=100):
    """Bewertet einen GoPlus-Eintrag. Gibt (ok, grund) zurueck. Fehlende Felder gelten als Warnsignal."""
    if not info:
        return False, "keine Sicherheitsdaten"
    if str(info.get("is_honeypot", "")) != "0":
        return False, "Honeypot oder Status unbekannt"
    if str(info.get("cannot_sell_all", "0")) == "1":
        return False, "Verkauf des gesamten Bestands blockiert"
    if str(info.get("is_open_source", "")) != "1":
        return False, "Contract nicht verifiziert"
    for flag, label in (("hidden_owner", "versteckter Owner"), ("owner_change_balance", "Owner kann Guthaben aendern"),
                        ("transfer_pausable", "Transfers pausierbar"), ("is_blacklisted", "Blacklist-Funktion")):
        if str(info.get(flag, "0")) == "1":
            return False, label
    buy_tax, sell_tax = _f(info.get("buy_tax"), 0.0), _f(info.get("sell_tax"), None)
    if sell_tax is None:
        return False, "Sell-Tax unbekannt"
    if buy_tax > max_tax or sell_tax > max_tax:
        return False, f"Steuer zu hoch (buy {buy_tax:.2%}, sell {sell_tax:.2%})"
    holders = _f(info.get("holder_count"), 0)
    if holders < min_holders:
        return False, f"zu wenige Holder ({holders:.0f})"
    return True, "ok"


class GoPlusChecker:
    def __init__(self, network, max_tax=0.05, min_holders=100):
        self.chain_id = CHAIN_IDS[network]
        self.max_tax = max_tax
        self.min_holders = min_holders
        self.cache = {}

    def check(self, address):
        if address in self.cache:
            return self.cache[address]
        try:
            r = requests.get(
                GOPLUS.format(chain_id=self.chain_id), params={"contract_addresses": address}, timeout=20
            )
            r.raise_for_status()
            info = (r.json().get("result") or {}).get(address.lower())
            res = evaluate_goplus(info, self.max_tax, self.min_holders)
        except (requests.RequestException, ValueError) as e:
            res = (False, f"Sicherheitscheck nicht erreichbar: {e}")
        self.cache[address] = res
        return res


class FakeChecker:
    """Fuer Tests."""

    def __init__(self, verdicts=None, default=(True, "ok")):
        self.verdicts = verdicts or {}
        self.default = default

    def check(self, address):
        return self.verdicts.get(address, self.default)


class Regime:
    """Grobes Marktregime aus den entdeckten Kandidaten (Breite und Median der 24h-Aenderung).

    Heuristik ohne Validierung. Trending-Listen sind tendenziell positiv verzerrt, die Schwellen
    sind darum konservativ. Wirkung im Paper-Betrieb auswerten, nicht blind glauben.
    """

    def __init__(self, cfg):
        self.enabled = cfg.get("enabled", True)
        self.min_breadth = cfg.get("min_breadth", 0.35)
        self.min_median_24h = cfg.get("min_median_change_24h", -8.0)

    def assess(self, candidates):
        if not self.enabled or len(candidates) < 5:
            return {"risk_off": False, "breadth": None, "median_24h": None}
        breadth = sum(1 for c in candidates if c.change_24h > 0) / len(candidates)
        med = statistics.median(c.change_24h for c in candidates)
        return {"risk_off": breadth < self.min_breadth or med < self.min_median_24h, "breadth": breadth, "median_24h": med}
