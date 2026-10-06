"""Verbindet Strategien, Walk-Forward und Allokator zu einem Lauf."""
from .metrics import stats
from .strategies import asset_returns, basket, carry_returns, trend_returns
from .walkforward import allocate, make_grid, walk_forward


def with_default(grid, default):
    """Stellt sicher, dass die Standardwerte Teil der Kandidaten sind (Vergleich fest vs. adaptiv)."""
    return grid if default in grid else grid + [default]


def carry_candidates(cfg, dates, ohlc, fund):
    c = cfg["carry"]
    out = []
    for p in with_default(make_grid(c["grid"]), c["default"]):
        if p["exit_apr"] >= p["entry_apr"]:
            continue
        per_coin = [
            carry_returns(dates, fund[x], ohlc[x], p["lookback"], p["entry_apr"], p["exit_apr"], c["lev"], cfg["costs"])[0]
            for x in cfg["coins"]
        ]
        out.append((p, basket(per_coin)))
    return out


def trend_candidates(cfg, dates, ohlc):
    t = cfg["trend"]
    out = []
    for p in with_default(make_grid(t["grid"]), t["default"]):
        per_coin = [
            trend_returns(dates, ohlc[x], p["sma_n"], p["vol_window"], p["target_vol"], t["max_lev"], t["band"], cfg["costs"]["trend_bps"])[0]
            for x in cfg["coins"]
        ]
        out.append((p, basket(per_coin)))
    return out


def find(cands, params):
    for p, r in cands:
        if all(p.get(k) == v for k, v in params.items()):
            return r
    return None


def run(cfg, dates, ohlc, fund):
    wf = cfg["walkforward"]
    carry_c = carry_candidates(cfg, dates, ohlc, fund)
    trend_c = trend_candidates(cfg, dates, ohlc)
    if not cfg["trend"].get("adapt", True):
        trend_c = [c for c in trend_c if c[0] == cfg["trend"]["default"]]
    switch = wf["switch_cost_bps"] / 1e4
    carry_oos, off, carry_chosen = walk_forward(carry_c, wf["train_days"], wf["step_days"], switch)
    trend_oos, _, trend_chosen = walk_forward(trend_c, wf["train_days"], wf["step_days"], switch)
    acfg = dict(cfg["allocator"])
    fixed = acfg.pop("fixed", None)
    if fixed:
        wc, wt = fixed["carry"], fixed["trend"]
        combined = [wc * a + wt * b for a, b in zip(carry_oos, trend_oos)]
        weights = [(0, {"carry": wc, "trend": wt})]
    else:
        combined, weights = allocate({"carry": carry_oos, "trend": trend_oos}, **acfg)

    carry_fixed = find(carry_c, cfg["carry"]["default"])[off:]
    trend_fixed = find(trend_c, cfg["trend"]["default"])[off:]
    fixed_5050 = [(a + b) / 2 for a, b in zip(carry_fixed, trend_fixed)]
    bh = basket([asset_returns(dates, ohlc[x]) for x in cfg["coins"]])[off:]
    return {
        "dates": dates[off:],
        "carry": carry_oos,
        "trend": trend_oos,
        "combined": combined,
        "carry_fixed": carry_fixed,
        "trend_fixed": trend_fixed,
        "fixed_5050": fixed_5050,
        "buyhold": bh,
        "carry_chosen": carry_chosen,
        "trend_chosen": trend_chosen,
        "weights": weights,
        "trials": len(carry_c) + len(trend_c),
        "offset": off,
    }


def signal(cfg, dates, ohlc, fund, res):
    """Zielzustand nach dem letzten Tag, mit den zuletzt gewaehlten Parametern."""
    out = {"as_of": dates[-1], "carry": {}, "trend": {}}
    cp = res["carry_chosen"][-1][1]
    tp = res["trend_chosen"][-1][1]
    for x in cfg["coins"]:
        _, info = carry_returns(dates, fund[x], ohlc[x], cp["lookback"], cp["entry_apr"], cp["exit_apr"], cfg["carry"]["lev"], cfg["costs"])
        out["carry"][x] = {"in_position": bool(info["position"]), "trailing_apr": info["trailing_apr"]}
        _, tgt = trend_returns(dates, ohlc[x], tp["sma_n"], tp["vol_window"], tp["target_vol"], cfg["trend"]["max_lev"], cfg["trend"]["band"], cfg["costs"]["trend_bps"])
        out["trend"][x] = {"target_exposure": tgt}
    out["carry_params"], out["trend_params"] = cp, tp
    out["weights"] = res["weights"][-1][1] if res["weights"] else {"carry": 0.5, "trend": 0.5}
    return out


def summary(res):
    names = [
        ("Adaptiv kombiniert (Carry+Trend)", "combined"),
        ("Carry adaptiv (Walk-Forward)", "carry"),
        ("Trend adaptiv (Walk-Forward)", "trend"),
        ("Carry feste Standardwerte", "carry_fixed"),
        ("Trend feste Standardwerte", "trend_fixed"),
        ("Fest 50/50 Standardwerte", "fixed_5050"),
        ("Buy-and-Hold Korb", "buyhold"),
    ]
    return [(label, stats(res[key])) for label, key in names]
