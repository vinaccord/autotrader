"""Vergleich von Trend-Varianten mit festen Parametern (kein Parameter-Suchlauf):
Basis (SMA 200), Mix aus mehreren SMA-Laengen, Crash-Regel, FOMC-Tage, mehr Coins.

python -m autotrader.quant.variants --config quant_variants.yaml fetch|compare [--cost-mult 2]

Alle Varianten laufen auf demselben Zeitraum (ab eval_start). Coins mit spaeterem Start kommen erst nach der Einlaufzeit in den Korb.
Achtung Ueberlebens-Verzerrung: die Coin-Liste besteht aus Coins, die es heute noch gibt. Gescheiterte Coins (z.B. LUNA, FTT) fehlen, der Mehr-Coin-Vorteil ist darum eher zu optimistisch. Die Zahl der Varianten steht im Bericht, weil jede
zusaetzliche Variante die Chance auf einen Zufallstreffer erhoeht. FOMC-Daten: federalreserve.gov (Kalender), Stand Okt 2026.
"""
import argparse
import datetime as dt
import os

import yaml

from . import data
from .metrics import stats, yearly
from .strategies import asset_returns, trend_returns


def event_set(dates_list, extra_days=1):
    out = set()
    for d in dates_list:
        base = dt.date.fromisoformat(str(d))
        for k in range(extra_days + 1):
            out.add((base + dt.timedelta(days=k)).isoformat())
    return out


def coin_series(cfg, coin, v, cost_bps, events):
    od = data.load_ohlc(data.cache_path(cfg, "prices", coin))
    dates = sorted(od)
    t = cfg["trend"]
    crash = dict(v["crash"]) if v.get("crash") else None
    ev = None
    if v.get("fomc"):
        ev = events
        crash = crash or {}
        crash["event_mult"] = v["fomc"]
    rets, _ = trend_returns(dates, od, v["sma_n"], t["vol_window"], t["target_vol"], t["max_lev"], t["band"], cost_bps, crash=crash, event_days=ev)
    warm = max(v["sma_n"]) if isinstance(v["sma_n"], (list, tuple)) else v["sma_n"]
    elig = dates[min(warm, len(dates) - 1)]  # erst nach der Einlaufzeit zaehlt der Coin im Korb
    return dict(zip(dates, rets)), elig


def buyhold_series(cfg, coin):
    od = data.load_ohlc(data.cache_path(cfg, "prices", coin))
    dates = sorted(od)
    return dict(zip(dates, asset_returns(dates, od))), dates[1] if len(dates) > 1 else dates[0]


def basket_on(series_by_coin, coins, dates):
    """Gleichgewichteter Korb der Coins, die am Tag schon zugelassen sind (Einlaufzeit vorbei) und Daten haben."""
    out = []
    for d in dates:
        vals = []
        for c in coins:
            ser, elig = series_by_coin[c]
            if d >= elig and d in ser:
                vals.append(ser[d])
        out.append(sum(vals) / len(vals) if vals else 0.0)
    return out


def cached(cfg, coin):
    return os.path.exists(data.cache_path(cfg, "prices", coin))


def compare(cfg, cost_mult=1.0, log=print):
    cost = cfg["costs"]["trend_bps"] * cost_mult
    events = event_set(cfg.get("events", {}).get("fomc", []))
    variants = {}
    missing = set()
    for name, v in cfg["variants"].items():
        have = [c for c in v["coins"] if cached(cfg, c)]
        missing |= set(v["coins"]) - set(have)
        if have:
            variants[name] = {**v, "coins": have}
    if missing:
        log(f"Ohne Daten (uebersprungen): {', '.join(sorted(missing))}")
    start = cfg["eval_start"]
    all_coins = sorted({c for v in variants.values() for c in v["coins"]})
    bh = {c: buyhold_series(cfg, c) for c in all_coins}
    dates = sorted({d for c in all_coins for d in bh[c][0] if d >= start})
    results = {}
    for name, v in variants.items():
        per = {c: coin_series(cfg, c, v, cost, events) for c in v["coins"]}
        results[name] = basket_on(per, v["coins"], dates)
    refs = {"Buy-and-Hold BTC/ETH": basket_on(bh, ["BTC", "ETH"], dates)}
    for name, v in variants.items():
        if len(v["coins"]) > 2:
            refs[f"Buy-and-Hold {name.split('_', 1)[-1]}"] = basket_on(bh, v["coins"], dates)
    log(f"Zeitraum {dates[0]} bis {dates[-1]} ({len(dates)} Tage), Varianten: {len(variants)}, Kosten x{cost_mult:g}")
    for name, v in variants.items():
        if len(v["coins"]) > 2:
            log(f"  {name}: {len(v['coins'])} Coins ({', '.join(v['coins'])})")
    log(f"{'Variante':<26}{'CAGR':>9}{'Vol':>8}{'Sharpe':>8}{'MaxDD':>9}{'Calmar':>8}")
    for name, rets in {**results, **refs}.items():
        s = stats(rets)
        cal = f"{s['calmar']:.2f}" if s["calmar"] is not None else "-"
        log(f"{name:<26}{s['cagr'] * 100:>+8.1f}%{s['vol'] * 100:>7.1f}%{s['sharpe']:>8.2f}{s['max_dd'] * 100:>+8.1f}%{cal:>8}")
    base = next(iter(variants))
    bs = stats(results[base])
    log(f"\nGegen {base}:")
    for name, rets in results.items():
        if name == base:
            continue
        s = stats(rets)
        log(f"  {name}: Sharpe {s['sharpe'] - bs['sharpe']:+.2f}, CAGR {(s['cagr'] - bs['cagr']) * 100:+.1f} Pp, MaxDD {(s['max_dd'] - bs['max_dd']) * 100:+.1f} Pp")
    log("\nJahre (Rendite je Variante):")
    ys = {n: yearly(dates, r) for n, r in results.items()}
    for y in ys[base]:
        log(f"  {y}: " + ", ".join(f"{n} {ys[n][y]['total'] * 100:+.0f}%" for n in results))
    log("\nHinweis: feste Parameter, aber die Auswahl der Varianten stammt von mir. Ein Vorteil in einem Zyklus ist ein Indiz, kein Beleg.")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(prog="variants")
    ap.add_argument("--config", default="quant_variants.yaml")
    ap.add_argument("cmd", choices=["fetch", "compare"])
    ap.add_argument("--cost-mult", type=float, default=1.0)
    a = ap.parse_args(argv)
    with open(a.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["data_dir"] = os.path.join(os.path.dirname(os.path.abspath(a.config)), cfg["data_dir"])
    if a.cmd == "fetch":
        data.fetch_all(cfg)
    else:
        compare(cfg, a.cost_mult)


if __name__ == "__main__":
    main()
