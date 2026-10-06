from dataclasses import dataclass, asdict


@dataclass
class Candidate:
    symbol: str
    address: str
    price_usd: float
    liquidity_usd: float
    volume_24h_usd: float
    change_1h: float
    change_24h: float
    age_hours: float
    fdv_usd: float = 0.0
    pool: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class Decision:
    action: str  # buy | sell | hold
    address: str
    symbol: str = ""
    size_usd: float = 0.0
    thesis: str = ""
    confidence: float = 0.0
