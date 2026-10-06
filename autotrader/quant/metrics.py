import math

PPY = 365  # Krypto handelt jeden Tag


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def stdev(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def sharpe(rets, ppy=PPY):
    sd = stdev(rets)
    return mean(rets) / sd * math.sqrt(ppy) if sd > 1e-12 else 0.0


def stats(rets, ppy=PPY):
    n = len(rets)
    if n < 2:
        return {"n": n, "cagr": 0.0, "vol": 0.0, "sharpe": 0.0, "max_dd": 0.0, "calmar": None, "total": 0.0}
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    cagr = eq ** (ppy / n) - 1 if eq > 0 else -1.0
    return {
        "n": n,
        "cagr": cagr,
        "vol": stdev(rets) * math.sqrt(ppy),
        "sharpe": sharpe(rets, ppy),
        "max_dd": mdd,
        "calmar": cagr / abs(mdd) if mdd < -1e-9 else None,
        "total": eq - 1,
    }


def yearly(dates, rets):
    """Kennzahlen pro Kalenderjahr, zeigt Regimeabhaengigkeit."""
    by_year = {}
    for d, r in zip(dates, rets):
        by_year.setdefault(d[:4], []).append(r)
    return {y: stats(v) for y, v in sorted(by_year.items())}
