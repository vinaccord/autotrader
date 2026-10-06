"""Lernen ohne Zukunftswissen: Walk-Forward-Parameterwahl und adaptiver Allokator.

Prinzip: Alle Parameterkombinationen laufen als kausale Renditereihen mit. In jedem Fenster waehlt das System die
Kombination mit dem besten Sharpe der letzten `train` Tage und folgt ihr fuer die naechsten `step` Tage
(Out-of-Sample). Die gemeldete Rendite besteht nur aus solchen Out-of-Sample-Fenstern.
"""
import itertools
import math

from .metrics import mean, sharpe, stdev


def make_grid(spec):
    keys = list(spec)
    return [dict(zip(keys, vals)) for vals in itertools.product(*(spec[k] for k in keys))]


def walk_forward(candidates, train, step, switch_cost=0.0):
    """candidates: Liste (params, rets). Gibt (oos_rets, start_index, chosen) zurueck.

    chosen: Liste (index, params) je Fenster. switch_cost ist ein pauschaler Abzug bei Parameterwechsel.
    """
    n = len(candidates[0][1])
    oos = []
    chosen = []
    prev = None
    t = train
    while t < n:
        end = min(t + step, n)
        best_i = max(range(len(candidates)), key=lambda k: (sharpe(candidates[k][1][t - train : t]), -k))
        params, rets = candidates[best_i]
        window = list(rets[t:end])
        if prev is not None and prev != best_i and window:
            window[0] -= switch_cost
        oos += window
        chosen.append((t, params))
        prev = best_i
        t = end
    return oos, train, chosen


def _clip_normalize(w, lo, hi):
    for _ in range(10):
        w = [min(max(x, lo), hi) for x in w]
        s = sum(w)
        w = [x / s for x in w]
        if all(lo - 1e-9 <= x <= hi + 1e-9 for x in w):
            break
    return w


def allocate(series, vol_window=90, perf_window=180, rebalance=30, tilt=0.5, w_min=0.1, w_max=0.9, vol_floor=5e-4):
    """Gewichte zwischen Strategien: Inverse Volatilitaet, getiltet nach trailing Sharpe, mit Grenzen.

    Gewichte am Index i nutzen nur Daten vor i. Gibt (rets, weights_history) zurueck.
    """
    names = list(series)
    n = len(series[names[0]])
    k = len(names)
    w = [1.0 / k] * k
    out = [0.0] * n
    history = []
    for i in range(n):
        if i >= max(vol_window, perf_window) and (i - max(vol_window, perf_window)) % rebalance == 0:
            inv = []
            for nm in names:
                sd = max(stdev(series[nm][i - vol_window : i]), vol_floor)
                inv.append(1.0 / sd)
            s = sum(inv)
            base = [x / s for x in inv]
            tilted = []
            for b, nm in zip(base, names):
                sh = max(-2.0, min(2.0, sharpe(series[nm][i - perf_window : i])))
                tilted.append(b * math.exp(tilt * sh))
            s = sum(tilted)
            w = _clip_normalize([x / s for x in tilted], w_min, w_max)
            history.append((i, dict(zip(names, [round(x, 3) for x in w]))))
        out[i] = sum(wi * series[nm][i] for wi, nm in zip(w, names))
    return out, history
