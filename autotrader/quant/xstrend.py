"""Phase 2, Zusatztest: Trendfilter (wie Profil 40) auf den jeweils umsatzstaerksten N Coins statt fest auf BTC/ETH.

python -m autotrader.quant.xstrend [--dir data/quant_universe]

Je Coin dieselbe Trendlogik wie im Profil 40 (SMA 200, Vola-Fenster 30, Ziel-Vola 0.45, Hebel max. 1, Band 0.1, nur Long), auf der eigenen
Kurshistorie. Das Universum am Tag i sind die N Coins mit dem hoechsten 30-Tage-Volumen (nur Daten bis i, Mindestalter 230 Tage fuer die Einlaufzeit
des SMA 200). Jeder Platz hat Gewicht 1/N, Rest ist Cash. Kosten auf dem Umsatz der Gewichte (inkl. Universumswechsel). Ausgelistet waehrend der
Haltezeit: Abschlag 5% (Annahme). Vorab festgelegt: N = 3, 5, 10, Kosten 20 und 40 bps, Vergleich BTC/ETH fix bei 10 und 20 bps.
Kein Nachbessern nach Ansicht der Zahlen. 6 Laeufe plus 2 Vergleichslaeufe pro Zeitraum.
"""
import argparse

from . import xsmom
from .metrics import stats, yearly
from .strategies import trend_returns

MIN_HISTORY = 230
NS = (3, 5, 10)
FIXED = ["BTCUSDT", "ETHUSDT"]


def positions(p, sym, params=(200, 30, 0.45, 1.0, 0.1)):
    """Geplante Trend-Position je Tag (volle Kalenderlaenge, 0 wo keine Kerze), Kosten 0."""
    c = p["close"][sym]
    idx = [i for i, x in enumerate(c) if x is not None]
    dd = [p["dates"][i] for i in idx]
    ohlc = {d: (c[i], c[i], c[i], c[i]) for d, i in zip(dd, idx)}
    pos = []
    trend_returns(dd, ohlc, params[0], params[1], params[2], params[3], params[4], 0.0, pos_out=pos)
    full = [0.0] * len(c)
    for i, v in zip(idx, pos):
        full[i] = v
    return full


def sleeve(p, start, n_slots, cost_bps, members_fn=None, delist_penalty=xsmom.DELIST_PENALTY, cache=None):
    """-> (rets, info). members_fn(i) -> Liste Symbole; Standard: Top-n_slots nach Volumen."""
    cache = cache if cache is not None else {}
    n = len(p["dates"])
    rets = [0.0] * n
    wprev = {}
    held, days_in = 0.0, 0
    for i in range(start, n - 1):
        mem = members_fn(i) if members_fn else xsmom.universe_at(p, i, MIN_HISTORY, n_slots)
        w = {}
        for s in mem:
            if s not in cache:
                cache[s] = positions(p, s)
            if cache[s][i] > 0:
                w[s] = cache[s][i] / n_slots
        turn = sum(abs(w.get(s, 0.0) - wprev.get(s, 0.0)) for s in set(w) | set(wprev))
        R = 0.0
        for s, ws in w.items():
            c = p["close"][s]
            if c[i + 1] is None and p["last"][s] < i + 1:
                R -= ws * delist_penalty
            elif c[i + 1] is not None and c[i] is not None:
                R += ws * (c[i + 1] / c[i] - 1)
        rets[i + 1] = R - turn * cost_bps / 1e4
        wprev = w
        held += sum(w.values())
        days_in += 1 if w else 0
    return rets, {"avg_invested": held / max(1, n - 1 - start), "days_in": days_in}


def report(p, since, log=print):
    ds = p["dates"]
    start = next(i for i, d in enumerate(ds) if d >= since)
    sl = slice(start + 1, None)
    cache = {}
    log(f"\nZeitraum {ds[start + 1]} bis {ds[-1]} ({len(ds) - start - 1} Tage)")
    log(f"{'Strategie':<40}{'CAGR':>8} {'Sharpe':>6} {'MaxDD':>9}   investiert")
    out = []
    base = {}
    for cost in (10, 20):
        r, info = sleeve(p, start, 2, cost, members_fn=lambda i: [s for s in FIXED if p["close"][s][i] is not None], cache=cache)
        base[cost] = r
        st = stats(r[sl])
        out.append((f"BTC/ETH fix, Kosten {cost}", st, info, r))
    for n in NS:
        for cost in (20, 40):
            r, info = sleeve(p, start, n, cost, cache=cache)
            out.append((f"Trend Top-{n} nach Volumen, Kosten {cost}", stats(r[sl]), info, r))
    for name, st, info, _ in out:
        log(f"{name:<40}{xsmom.fmt(st)}   {info['avg_invested'] * 100:>5.0f}%")
    bh = stats(xsmom.buyhold(p)[sl])
    log(f"{'BTC Buy-and-Hold':<40}{xsmom.fmt(bh)}")
    log("Rendite je Kalenderjahr (Kosten 20):")
    for name, _, _, r in out:
        if name.endswith("20"):
            ys = yearly(ds[start + 1:], r[start + 1:])
            log(f"  {name[:-10]:<26}" + " ".join(f"{y}:{v['total'] * 100:+4.0f}%" for y, v in ys.items()))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="xstrend")
    ap.add_argument("--dir", default="data/quant_universe")
    a = ap.parse_args(argv)
    p = xsmom.build_panel(xsmom.load_dir(a.dir))
    print(f"{len(p['close'])} Symbole, {p['dates'][0]} bis {p['dates'][-1]}")
    report(p, "2020-11-30")
    report(p, "2019-07-01")
    print("\nHinweise: 6 Laeufe plus 2 Vergleichslaeufe je Zeitraum, vorab festgelegt. Abschlag 5% bei Delisting ist eine Annahme. Coins, die nie auf Binance waren, fehlen.")


if __name__ == "__main__":
    main()
