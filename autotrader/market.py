"""Marktdaten. GeckoTerminal (oeffentliche API, kein Key) plus Fake fuer Tests.

Hinweis: Der Provider ist nach der dokumentierten API-Struktur geschrieben, aber in der
Build-Umgebung nicht live getestet (Netzwerk gesperrt). Beim ersten Lauf Antwortformat pruefen.
"""
import time
from datetime import datetime, timezone

import requests

from .models import Candidate

BASE = "https://api.geckoterminal.com/api/v2"
IGNORE_SYMBOLS = {"WETH", "ETH", "USDC", "USDT", "DAI", "USDBC", "CBBTC", "WBTC", "EURC", "USDS"}


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


class GeckoTerminalProvider:
    def __init__(self, network="base", pause_s=2.5):
        self.network = network
        self.pause_s = pause_s  # Free-Tier ca. 30 Calls/Min
        self.s = requests.Session()
        self.s.headers["accept"] = "application/json"

    def _get(self, path):
        r = self.s.get(f"{BASE}{path}", timeout=20)
        r.raise_for_status()
        time.sleep(self.pause_s)
        return r.json()

    def discover(self, now=None):
        now = now or time.time()
        seen, out = set(), []
        for path in (f"/networks/{self.network}/trending_pools", f"/networks/{self.network}/new_pools"):
            try:
                data = self._get(path)
            except requests.RequestException:
                continue
            for pool in data.get("data", []):
                c = self._parse_pool(pool, now)
                if c and c.address not in seen and c.symbol.upper() not in IGNORE_SYMBOLS:
                    seen.add(c.address)
                    out.append(c)
        return out

    def _parse_pool(self, pool, now):
        a = pool.get("attributes", {})
        rel = pool.get("relationships", {}).get("base_token", {}).get("data", {})
        token_id = rel.get("id", "")  # Format: "<network>_<address>"
        if "_" not in token_id:
            return None
        address = token_id.split("_", 1)[1].lower()
        name = a.get("name", "")
        symbol = name.split("/")[0].strip() or "?"
        created = a.get("pool_created_at")
        age_h = 0.0
        if created:
            try:
                ts = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
                age_h = max(0.0, (now - ts) / 3600)
            except ValueError:
                pass
        pc = a.get("price_change_percentage", {}) or {}
        vol = a.get("volume_usd", {}) or {}
        return Candidate(
            symbol=symbol,
            address=address,
            price_usd=_f(a.get("base_token_price_usd")),
            liquidity_usd=_f(a.get("reserve_in_usd")),
            volume_24h_usd=_f(vol.get("h24")),
            change_1h=_f(pc.get("h1")),
            change_24h=_f(pc.get("h24")),
            age_hours=age_h,
            fdv_usd=_f(a.get("fdv_usd")),
            pool=a.get("address", ""),
        )

    def price(self, address):
        data = self._get(f"/networks/{self.network}/tokens/{address}")
        return _f(data["data"]["attributes"].get("price_usd"))


class FakeProvider:
    """Fuer Tests und Trockenlaeufe."""

    def __init__(self, candidates):
        self.candidates = {c.address: c for c in candidates}

    def discover(self, now=None):
        return list(self.candidates.values())

    def price(self, address):
        return self.candidates[address].price_usd

    def set_price(self, address, price):
        self.candidates[address].price_usd = price
