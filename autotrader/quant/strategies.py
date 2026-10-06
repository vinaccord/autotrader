"""Kausale Tagesstrategien. Signal am Tagesende i, Position wirkt ab Tag i+1 (kein Lookahead).

Annahmen, die Ergebnisse beschoenigen koennen: Ausfuehrung zum Schlusskurs, keine Teilfuellungen,
keine Ausfaelle der Plattform. Kosten werden pauschal in Basispunkten angesetzt.
"""
import math

from .metrics import mean, stdev


def carry_returns(dates, fund, ohlc, lookback, entry_apr, exit_apr, lev, costs):
    """Delta-neutraler Funding-Carry: Spot long, Perp short, mit Hysterese.

    Rendite pro Tag = eff * Funding des Tages, eff = lev/(lev+1) (Kapital teilt sich in Spot-Bein und Perp-Margin).
    Gibt (rets, info) zurueck. info["position"] ist der Zielzustand nach dem Signal des letzten Tages (fuer Live-Signale).
    liq_flags zaehlt Tage, an denen der Tageshoechstkurs ueber der Liquidationsschwelle des Short-Beins lag.
    Das wird nur gezaehlt, nicht als Verlust verbucht.
    """
    n = len(dates)
    eff = lev / (lev + 1)
    round_trip = eff * (costs["spot_fee_bps"] + costs["perp_fee_bps"] + 2 * costs["slippage_bps"]) / 1e4
    rets = [0.0] * n
    pos, entries, liq, days_in = 0, 0, 0, 0
    last_apr = None
    for i in range(n):
        new = pos
        if i + 1 >= lookback:
            last_apr = mean([fund.get(dates[j], 0.0) for j in range(i + 1 - lookback, i + 1)]) * 365
            if pos == 0 and last_apr >= entry_apr:
                new = 1
            elif pos == 1 and last_apr < exit_apr:
                new = 0
        if i < n - 1:
            r = 0.0
            if new != pos:
                r -= round_trip  # Eintritt oder Austritt: beide Beine handeln
                entries += 1 if new == 1 else 0
            if new == 1:
                r += eff * fund.get(dates[i + 1], 0.0)
                days_in += 1
                prev_close = ohlc[dates[i]][3]
                if ohlc[dates[i + 1]][1] / prev_close - 1 >= 0.9 / lev:
                    liq += 1
            rets[i + 1] = r
        pos = new
    return rets, {"entries": entries, "liq_flags": liq, "days_in": days_in, "position": pos, "trailing_apr": last_apr}


def asset_returns(dates, ohlc):
    closes = [ohlc[d][3] for d in dates]
    return [0.0] + [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]


def trend_returns(dates, ohlc, sma_n, vol_window, target_vol, max_lev, band, cost_bps):
    """Long/Flat auf SMA-Filter, Positionsgroesse per Ziel-Volatilitaet. Nur Long, Hebel hoechstens max_lev.

    Gibt (rets, last_target) zurueck. last_target ist die Zielposition nach dem Signal des letzten Tages.
    """
    n = len(dates)
    closes = [ohlc[d][3] for d in dates]
    ar = asset_returns(dates, ohlc)
    out = [0.0] * n
    pos = 0.0
    warm = max(sma_n, vol_window + 1)
    for i in range(n):
        target = 0.0
        if i + 1 >= warm:
            is_long = closes[i] > mean(closes[i + 1 - sma_n : i + 1])
            vol = stdev(ar[i + 1 - vol_window : i + 1]) * math.sqrt(365)
            if is_long and vol > 0:
                target = min(max_lev, target_vol / vol)
        if target == 0.0 or abs(target - pos) > band:
            new = target
        else:
            new = pos  # kleine Anpassungen unterdruecken, spart Kosten
        if i < n - 1:
            out[i + 1] = new * ar[i + 1] - abs(new - pos) * cost_bps / 1e4
        pos = new
    return out, pos


def basket(series_list):
    """Gleichgewichteter Korb mehrerer Renditereihen gleicher Laenge."""
    n = len(series_list[0])
    return [sum(s[i] for s in series_list) / len(series_list) for i in range(n)]
