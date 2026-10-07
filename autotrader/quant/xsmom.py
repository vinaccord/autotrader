"""Phase 2, Schritte 4 und 5: Universum zeitpunktgenau und Querschnitts-Momentum auf ueberlebensfreien Daten.

python -m autotrader.quant.xsmom [--dir data/quant_universe]

Daten: <dir>/<SYMBOL>.csv aus universe_data.py (alle USDT-Spot-Paare inkl. ausgelistete).
Universum am Tag i (nur Daten bis i): Alter mindestens MIN_AGE Tage, an mindestens 25 der letzten 30 Tage ein Kurs, Kerze am Tag i vorhanden,
dann die TOP_N Coins nach durchschnittlichem Quote-Volumen (30 Tage).
Momentum: Rendite ueber L Tage, die K besten (gleichgewichtet), woechentliches Rebalancing, optional nur Coins ueber ihrem SMA 100.
Kausal: Signal am Schluss von Tag i, Rendite ab Tag i+1. Kosten pro Handelsseite auf den Umsatz. Ausgelistet waehrend der Haltezeit:
Verkauf zum letzten Kurs mit Abschlag DELIST_PENALTY (Annahme, nicht gemessen), danach Cash.
Vorab festgelegt (kein Nachbessern nach Ansicht der Zahlen): 6 Varianten (L in 30/60/90 x Filter keiner/SMA100), K=5, TOP_N=30, Kosten 20 bps
(Alts: Gebuehr + breitere Spreads) und 40 bps als Stress. Vergleich: Trend BTC/ETH (Profil-40-Trend) auf denselben Daten, BTC Buy-and-Hold,
alle Universum-Coins gleichgewichtet. Rest-Verzerrung: Coins, die Binance nie gelistet hat, fehlen; Umbenennungen koennen Spruenge erzeugen.
"""
import argparse
import csv
import os

from .metrics import stats, yearly
from .strategies import basket, trend_returns

MIN_AGE = 90
TOP_N = 30
K = 5
REBALANCE = 7
DELIST_PENALTY = 0.05
VARIANTS = [(L, f) for L in (30, 60, 90) for f in (False, True)]


def load_dir(path, symbols=None):
    """-> {symbol: {date: (o, h, l, c, quote_volume)}}"""
    out = {}
    for fn in sorted(os.listdir(path)):
        if not fn.endswith(".csv"):
            continue
        sym = fn[:-4]
        if symbols and sym not in symbols:
            continue
        with open(os.path.join(path, fn), newline="", encoding="utf-8") as f:
            r = csv.reader(f)
            next(r, None)
            out[sym] = {row[0]: (float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[6])) for row in r}
    return out


def is_stable(closes):
    """Preisband um 1: fast immer zwischen 0.97 und 1.03."""
    v = [c for c in closes if c is not None]
    return len(v) > 30 and sum(1 for c in v if 0.97 <= c <= 1.03) / len(v) > 0.95


def build_panel(raw):
    """-> dict mit dates, close{sym:[..]}, qvol{sym:[..]}, first{sym}, last{sym}. Stablecoins (Preisband) entfernt."""
    import datetime as dt

    alld = sorted({d for s in raw.values() for d in s})
    d0, d1 = dt.date.fromisoformat(alld[0]), dt.date.fromisoformat(alld[-1])
    dates = [(d0 + dt.timedelta(days=k)).isoformat() for k in range((d1 - d0).days + 1)]
    close, qvol, first, last = {}, {}, {}, {}
    for sym, rows in raw.items():
        c = [rows[d][3] if d in rows else None for d in dates]
        if is_stable(c):
            continue
        idx = [i for i, x in enumerate(c) if x is not None]
        if not idx:
            continue
        close[sym] = c
        qvol[sym] = [rows[d][4] if d in rows else None for d in dates]
        first[sym], last[sym] = idx[0], idx[-1]
    return {"dates": dates, "close": close, "qvol": qvol, "first": first, "last": last}


def universe_at(p, i, min_age=MIN_AGE, top_n=TOP_N):
    """Handelbare Coins am Tag i (nur Daten bis i), die top_n nach 30-Tage-Volumen. Ergebnis wird je Panel zwischengespeichert."""
    cache = p.setdefault("_uni", {})
    key = (i, min_age, top_n)
    if key in cache:
        return cache[key]
    cands = []
    for s, c in p["close"].items():
        if p["first"][s] > i - min_age or p["last"][s] < i or c[i] is None:
            continue
        win = [p["qvol"][s][j] for j in range(max(0, i - 29), i + 1) if p["qvol"][s][j] is not None]
        if len(win) < 25:
            continue
        cands.append((sum(win) / len(win), s))
    cands.sort(reverse=True)
    cache[key] = [s for _, s in cands[:top_n]]
    return cache[key]


def pick(p, i, lookback, sma_filter, k=K, mode="mom"):
    """Zielgewichte am Schluss von Tag i. mode 'ew': alle Universum-Coins gleichgewichtet (Vergleich)."""
    ck = (i, lookback, sma_filter, k, mode)
    pc = p.setdefault("_pick", {})
    if ck in pc:
        return dict(pc[ck])
    out = _pick(p, i, lookback, sma_filter, k, mode)
    pc[ck] = out
    return dict(out)


def _pick(p, i, lookback, sma_filter, k, mode):
    uni = universe_at(p, i)
    if mode == "ew":
        return {s: 1.0 / len(uni) for s in uni} if uni else {}
    scored = []
    for s in uni:
        c = p["close"][s]
        if i - lookback < 0 or c[i - lookback] is None:
            continue
        if sma_filter:
            w = [x for x in c[max(0, i - 99): i + 1] if x is not None]
            if len(w) < 80 or c[i] <= sum(w) / len(w):
                continue
        scored.append((c[i] / c[i - lookback] - 1, s))
    scored.sort(reverse=True)
    top = [s for sc, s in scored[:k] if sc > 0]
    return {s: 1.0 / k for s in top}


def backtest(p, start, lookback, sma_filter, cost_bps, mode="mom", delist_penalty=DELIST_PENALTY, rebalance=REBALANCE):
    """-> (rets ueber p['dates'], info). rets[i+1] = Rendite von Tag i nach i+1 mit den am Schluss von i gewaehlten Gewichten."""
    n = len(p["dates"])
    rets = [0.0] * n
    w = {}
    delisted = 0
    held_days = 0
    for i in range(start, n - 1):
        cost = 0.0
        if (i - start) % rebalance == 0:
            tgt = pick(p, i, lookback, sma_filter, mode=mode)
            turn = sum(abs(tgt.get(s, 0.0) - w.get(s, 0.0)) for s in set(tgt) | set(w))
            cost = turn * cost_bps / 1e4
            w = tgt
        R, neww = 0.0, {}
        for s, ws in w.items():
            c = p["close"][s]
            if c[i + 1] is None and p["last"][s] < i + 1:  # ausgelistet: Verkauf zum letzten Kurs mit Abschlag
                r = -delist_penalty
                delisted += 1
                R += ws * r
                continue
            r = 0.0 if (c[i + 1] is None or c[i] is None) else c[i + 1] / c[i] - 1
            R += ws * r
            neww[s] = ws * (1 + r)
        rets[i + 1] = R - cost
        eq = 1 + R
        w = {s: x / eq for s, x in neww.items()}
        held_days += len(w)
    return rets, {"delisted_events": delisted, "avg_positions": held_days / max(1, n - 1 - start)}


def trend_benchmark(p, dates_index, cost_bps=10):
    """Trend BTC/ETH wie im Profil 40 (SMA 200, Vola 30, Ziel 0.45, Band 0.1) auf denselben Daten."""
    per = []
    ds = p["dates"]
    for s in ("BTCUSDT", "ETHUSDT"):
        ohlc = {d: (c, c, c, c) for d, c in zip(ds, p["close"][s]) if c is not None}
        dd = [d for d in ds if d in ohlc]
        r, _ = trend_returns(dd, ohlc, 200, 30, 0.45, 1.0, 0.1, cost_bps)
        m = dict(zip(dd, r))
        per.append([m.get(d, 0.0) for d in ds])
    return basket(per)


def buyhold(p, sym="BTCUSDT"):
    c = p["close"][sym]
    out = [0.0] * len(c)
    for i in range(1, len(c)):
        if c[i] is not None and c[i - 1] is not None:
            out[i] = c[i] / c[i - 1] - 1
    return out


def fmt(s):
    return f"{s['cagr'] * 100:+7.1f}% {s['sharpe']:>6.2f} {s['max_dd'] * 100:+8.1f}%"


def report(p, since, log=print):
    ds = p["dates"]
    start = next(i for i, d in enumerate(ds) if d >= since)
    sl = slice(start + 1, None)
    rows = []
    for L, f in VARIANTS:
        for cost in (20, 40):
            r, info = backtest(p, start, L, f, cost)
            rows.append((f"Momentum L={L}, {'SMA100' if f else 'ohne Filter'}, Kosten {cost}", stats(r[sl]), info, r))
    ew, _ = backtest(p, start, 0, False, 20, mode="ew")
    bench = [("Trend BTC/ETH (Profil-40-Trend)", stats(trend_benchmark(p, None)[sl])), ("BTC Buy-and-Hold", stats(buyhold(p)[sl])), ("Top-30 gleichgewichtet, 20", stats(ew[sl]))]
    log(f"\nZeitraum {ds[start + 1]} bis {ds[-1]} ({len(ds) - start - 1} Tage), Universum Top {TOP_N}, K={K}, woechentlich, {len(VARIANTS)} Varianten x 2 Kostenstufen")
    log(f"{'Strategie':<44}{'CAGR':>8} {'Sharpe':>6} {'MaxDD':>9}   Ausl./Pos.")
    for name, st, info, _ in rows:
        log(f"{name:<44}{fmt(st)}   {info['delisted_events']:>3} / {info['avg_positions']:.1f}")
    for name, st in bench:
        log(f"{name:<44}{fmt(st)}")
    return rows, bench


def main(argv=None):
    ap = argparse.ArgumentParser(prog="xsmom")
    ap.add_argument("--dir", default="data/quant_universe")
    a = ap.parse_args(argv)
    raw = load_dir(a.dir)
    p = build_panel(raw)
    print(f"{len(raw)} Symbole geladen, {len(p['close'])} nach Entfernen von Stablecoins, {p['dates'][0]} bis {p['dates'][-1]}")
    n_gone = sum(1 for s in p["last"] if p["last"][s] < len(p["dates"]) - 3)
    print(f"davon mit Datenende vor heute (ausgelistet oder eingestellt): {n_gone}")
    report(p, "2020-11-30")
    report(p, "2019-07-01")
    print("\nHinweise: Parameter vorab festgelegt, 12 Laeufe pro Zeitraum. Ausgelistet-Abschlag 5% ist eine Annahme. Fehlende Coins (nie auf Binance) und Umbenennungen bleiben Rest-Verzerrung.")


if __name__ == "__main__":
    main()
