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

    Margin-Pflege (seit 7.10.): Referenzpreis ref = Schlusskurs bei Eintritt bzw. beim letzten Margin-Ausgleich. Bewegt sich der
    Schlusskurs um mindestens 0.5/lev gegen ref (bei Hebel 2: 25%), wird ausgeglichen (Spot-Gewinn in die Perp-Margin schieben oder umgekehrt):
    Kosten eff * Bewegung * (Spot-Gebuehr + Slippage), ref wird neu gesetzt (info["rebalances"]).
    Liegt das Tageshoch ueber ref * (1 + 0.9/lev), wird das Short-Bein liquidiert: Verlust der Margin (1/(lev+1) des Kapitals, ohne
    Gutschrift des Spot-Gewinns, bewusst konservativ) plus Ausstiegskosten, Position danach flat (info["liq_flags"]).
    """
    n = len(dates)
    eff = lev / (lev + 1)
    round_trip = eff * (costs["spot_fee_bps"] + costs["perp_fee_bps"] + 2 * costs["slippage_bps"]) / 1e4
    rebal_cost = eff * (costs["spot_fee_bps"] + costs["slippage_bps"]) / 1e4
    rets = [0.0] * n
    flags = [0] * n  # 1 an Tagen, an denen die Carry-Position gehalten wird
    pos, entries, liq, days_in, rebalances = 0, 0, 0, 0, 0
    ref = None
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
                    ref = ohlc[dates[i]][3]
            if new == 1:
                r += eff * fund.get(dates[i + 1], 0.0)
                days_in += 1
                if ohlc[dates[i + 1]][1] / ref - 1 >= 0.9 / lev:
                    liq += 1
                    r -= 1.0 / (lev + 1) + round_trip
                    flags[i + 1] = 1
                    rets[i + 1] = r
                    pos = 0
                    continue
                close = ohlc[dates[i + 1]][3]
                mv = close / ref - 1
                if abs(mv) >= 0.5 / lev:
                    r -= abs(mv) * rebal_cost
                    ref = close
                    rebalances += 1
            rets[i + 1] = r
            flags[i + 1] = new
        pos = new
    return rets, {"flags": flags, "entries": entries, "liq_flags": liq, "days_in": days_in, "rebalances": rebalances, "position": pos, "trailing_apr": last_apr}


def asset_returns(dates, ohlc):
    closes = [ohlc[d][3] for d in dates]
    return [0.0] + [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]


def trend_returns(dates, ohlc, sma_n, vol_window, target_vol, max_lev, band, cost_bps, crash=None, event_days=None, delay=0, funding=None, pos_out=None):
    """Long/Flat auf SMA-Filter, Positionsgroesse per Ziel-Volatilitaet. Nur Long, Hebel hoechstens max_lev.

    sma_n: eine Laenge (int) oder eine Liste. Bei einer Liste ist die Position der Anteil der Laengen, bei denen der Kurs
    darueber liegt (Mix aus mehreren Durchschnitten, weniger abhaengig von einem einzelnen Parameter).
    crash: {"days": n, "pct": x, "mult": m}. Faellt der Kurs in n Tagen um mindestens x, wird die Ziel-Position mit m multipliziert.
    event_days: Menge von Datums-Strings. Fuer diese Tage wird die Position mit crash["mult"] (oder 0.5) multipliziert;
    der Kalender ist vorab bekannt, es wird nichts aus der Zukunft abgeleitet.

    delay: Ausfuehrungsverzoegerung in Tagen. 0 = Fill zum Schlusskurs des Signaltags (Standard), 1 = Fill erst zum Schlusskurs
    des Folgetags (konservative Obergrenze; der echte Job laeuft rund 65 Minuten nach Tagesschluss).
    pos_out: optionale Liste, bekommt je Tag die geplante Position nach dem Signal (fuer Universum-Tests).
    funding: Liste (gleiche Laenge wie dates) mit Tages-Funding je Tag; eine Long-Position zahlt es (Perp-Variante). None = Spot.

    Gibt (rets, last_target) zurueck. last_target ist die Zielposition nach dem Signal des letzten Tages (geplant, nicht ausgefuehrt).
    """
    n = len(dates)
    closes = [ohlc[d][3] for d in dates]
    ar = asset_returns(dates, ohlc)
    out = [0.0] * n
    pos = 0.0
    lens = list(sma_n) if isinstance(sma_n, (list, tuple)) else [sma_n]
    warm = max(max(lens), vol_window + 1)
    ev_mult = (crash or {}).get("event_mult", 0.5)
    plan = []
    held = 0.0  # tatsaechlich gehaltene Position (bei delay=0 identisch mit pos)
    for i in range(n):
        target = 0.0
        if i + 1 >= warm:
            frac = sum(1 for L in lens if closes[i] > mean(closes[i + 1 - L : i + 1])) / len(lens)
            vol = stdev(ar[i + 1 - vol_window : i + 1]) * math.sqrt(365)
            if frac > 0 and vol > 0:
                target = frac * min(max_lev, target_vol / vol)
            if target > 0 and crash and "days" in crash and i >= crash["days"]:
                if closes[i] / closes[i - crash["days"]] - 1 <= -crash["pct"]:
                    target *= crash["mult"]
            if target > 0 and event_days and i < n - 1 and dates[i + 1] in event_days:
                target *= ev_mult
        if target == 0.0 or abs(target - pos) > band:
            new = target
        else:
            new = pos  # kleine Anpassungen unterdruecken, spart Kosten
        plan.append(new)
        if pos_out is not None:
            pos_out.append(new)
        if i < n - 1:
            ex = plan[i - delay] if i - delay >= 0 else 0.0
            out[i + 1] = ex * ar[i + 1] - abs(ex - held) * cost_bps / 1e4 - (ex * funding[i + 1] if funding else 0.0)
            held = ex
        pos = new
    return out, pos


def basket(series_list):
    """Gleichgewichteter Korb mehrerer Renditereihen gleicher Laenge."""
    n = len(series_list[0])
    return [sum(s[i] for s in series_list) / len(series_list) for i in range(n)]
