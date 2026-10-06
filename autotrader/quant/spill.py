"""Test: Was passiert, wenn ungenutztes Carry-Kapital dem Trend zugeschlagen wird?

Im Hauptprofil liegen 30% fuer Carry bereit. Ist Carry "flat" (Funding unter der Einstiegsschwelle), liegt dieser Teil in Cash.
Varianten:
  idle        wie bisher: flacher Carry-Anteil bleibt Cash
  spill_half  die Haelfte des flachen Anteils geht in den Trend
  spill       der ganze flache Anteil geht in den Trend
  trend_only  100% Trend, kein Carry
Carry wird hier mit den Standardparametern aus der Config gerechnet (ohne Walk-Forward), der Trend ist die Out-of-Sample-Reihe des Profils.
Aufruf: python -m autotrader.quant.spill --config quant_40.yaml
"""
import argparse
import os

import yaml

from . import data, pipeline
from .metrics import stats, yearly
from .strategies import carry_returns


def combine(carry_rets, carry_flags, trend_rets, w_carry, mode):
    """carry_rets/carry_flags: {coin: Liste}. w_carry: Gesamtgewicht des Carry-Topfs, gleich auf Coins verteilt."""
    coins = list(carry_rets)
    n = len(trend_rets)
    slice_w = w_carry / len(coins)
    share = {"idle": 0.0, "spill_half": 0.5, "spill": 1.0, "trend_only": 1.0}[mode]
    out = []
    for i in range(n):
        carry_part, idle = 0.0, 0.0
        for c in coins:
            if mode == "trend_only":
                idle += slice_w
            elif carry_flags[c][i]:
                carry_part += slice_w * carry_rets[c][i]
            else:
                carry_part += slice_w * carry_rets[c][i]  # Ein-/Austrittskosten fallen auch an Tagen mit flag 0 an
                idle += slice_w
        trend_w = (1 - w_carry) + idle * share
        out.append(carry_part + trend_w * trend_rets[i])
    return out


def carry_parts(cfg, dates, ohlc, fund):
    """Carry je Coin mit den Standardparametern: (rets, flags, positionen_nach_letztem_signal)."""
    c = cfg["carry"]
    p = c["default"]
    cr, cf, pos = {}, {}, {}
    for coin in cfg["coins"]:
        r, info = carry_returns(dates, fund[coin], ohlc[coin], p["lookback"], p["entry_apr"], p["exit_apr"], c["lev"], cfg["costs"])
        cr[coin], cf[coin], pos[coin] = r, info["flags"], info["position"]
    return cr, cf, pos


def carry_weight(cfg):
    return cfg["allocator"]["fixed"]["carry"] if cfg["allocator"].get("fixed") else 0.3


def spill_series(cfg, dates, ohlc, fund, res, mode="spill"):
    """Renditen des Profils mit Spill, ausgerichtet auf res['dates']."""
    cr, cf, _ = carry_parts(cfg, dates, ohlc, fund)
    off = res["offset"]
    return combine({k: v[off:] for k, v in cr.items()}, {k: v[off:] for k, v in cf.items()}, res["trend"], carry_weight(cfg), mode)


def effective_weights(cfg, dates, ohlc, fund, mode="spill"):
    """Gewichte nach dem letzten Signal: aktive Carry-Teile bleiben Carry, flache gehen (je nach Modus) an den Trend."""
    _, _, pos = carry_parts(cfg, dates, ohlc, fund)
    w = carry_weight(cfg)
    slice_w = w / len(pos)
    active = [c for c, v in pos.items() if v]
    flat = [c for c, v in pos.items() if not v]
    share = {"idle": 0.0, "spill_half": 0.5, "spill": 1.0}[mode]
    carry = slice_w * len(active)
    trend = (1 - w) + slice_w * len(flat) * share
    return {"trend": trend, "carry": carry, "cash": 1 - trend - carry, "carry_aktiv": active, "carry_flat": flat}


def run(cfg, log=print):
    dates, ohlc, fund = data.load_all(cfg)
    res = pipeline.run(cfg, dates, ohlc, fund)
    off = res["offset"]
    c = cfg["carry"]
    p = c["default"]
    cr, cf = {}, {}
    for coin in cfg["coins"]:
        r, info = carry_returns(dates, fund[coin], ohlc[coin], p["lookback"], p["entry_apr"], p["exit_apr"], c["lev"], cfg["costs"])
        cr[coin], cf[coin] = r[off:], info["flags"][off:]
    w_carry = cfg["allocator"]["fixed"]["carry"] if cfg["allocator"].get("fixed") else 0.3
    d = res["dates"]
    active = sum(sum(cf[k]) for k in cf) / (len(cf) * len(d))
    log(f"Out-of-Sample {d[0]} bis {d[-1]} ({len(d)} Tage). Carry-Topf {w_carry:.0%}, Carry war an {active:.0%} der Tage in Position.")
    log(f"{'Variante':<14}{'CAGR':>9}{'Vol':>8}{'Sharpe':>8}{'MaxDD':>9}{'Calmar':>8}")
    modes = ["idle", "spill_half", "spill", "trend_only"]
    out = {m: combine(cr, cf, res["trend"], w_carry, m) for m in modes}
    for m, rets in out.items():
        s = stats(rets)
        cal = f"{s['calmar']:.2f}" if s["calmar"] is not None else "-"
        log(f"{m:<14}{s['cagr'] * 100:>+8.1f}%{s['vol'] * 100:>7.1f}%{s['sharpe']:>8.2f}{s['max_dd'] * 100:>+8.1f}%{cal:>8}")
    log("\nJahre (Rendite):")
    ys = {m: yearly(d, r) for m, r in out.items()}
    for y in ys["idle"]:
        log(f"  {y}: " + ", ".join(f"{m} {ys[m][y]['total'] * 100:+.0f}%" for m in modes))
    worst = min(stats(r)["max_dd"] for r in out.values())
    log(f"\nSchlechtester Max-Verlust im Backtest: {worst * 100:+.1f}% (deine Toleranz: -40%). Reale Verluste koennen groesser sein, der Backtest bildet Ausfaelle und Luecken nicht ab.")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="spill")
    ap.add_argument("--config", default="quant_40.yaml")
    a = ap.parse_args(argv)
    with open(a.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["data_dir"] = os.path.join(os.path.dirname(os.path.abspath(a.config)), cfg["data_dir"])
    run(cfg)


if __name__ == "__main__":
    main()
