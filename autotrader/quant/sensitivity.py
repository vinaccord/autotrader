"""Sensitivitaet des Trend-Teils: Spot-Kosten, duenne Orderbuecher, Ausfuehrungsverzoegerung, Perp mit echtem Funding.

python -m autotrader.quant.sensitivity --config quant_40.yaml

Feste Parameter aus der Config (kein Suchlauf). Alle Szenarien auf demselben Zeitraum wie der Backtest (ab train_days).
Szenarien (7 Stueck, vorab festgelegt, kein Nachbessern nach Ansicht der Zahlen):
  spot 10 bps          Basis, entspricht trend_bps der Config (7 bps Taker + Slippage)
  spot 20 / 40 bps     Kosten x2 und x4 (duenne Spot-Buecher UBTC/UETH)
  spot 10/20 + 1 Tag   Fill erst zum Schlusskurs des Folgetags (konservative Obergrenze, echt ca. 65 Minuten)
  perp 7 bps + Funding Long zahlt das echte Binance-Funding (Naeherung fuer Hyperliquid, gleicher Basiszins 0.01% pro 8 h)
Profil-40-Spalte: 30% Carry (unveraendert aus dem Backtest) + 70% Trend-Variante, ohne Spill.
"""
import argparse
import os

import yaml

from . import data, pipeline
from .metrics import stats
from .strategies import basket, trend_returns

SCENARIOS = [
    ("Spot 10 bps (Basis)", dict(cost=10, delay=0, perp=False)),
    ("Spot 20 bps", dict(cost=20, delay=0, perp=False)),
    ("Spot 40 bps", dict(cost=40, delay=0, perp=False)),
    ("Spot 10 bps, 1 Tag spaeter", dict(cost=10, delay=1, perp=False)),
    ("Spot 20 bps, 1 Tag spaeter", dict(cost=20, delay=1, perp=False)),
    ("Perp 7 bps + Funding", dict(cost=7, delay=0, perp=True)),
    ("Perp 7 bps + Funding, 1 Tag spaeter", dict(cost=7, delay=1, perp=True)),
]


def trend_basket(cfg, dates, ohlc, fund, cost, delay, perp):
    t, d = cfg["trend"], cfg["trend"]["default"]
    per_coin = []
    for c in cfg["coins"]:
        f = [fund[c].get(x, 0.0) for x in dates] if perp else None
        r, _ = trend_returns(dates, ohlc[c], d["sma_n"], d["vol_window"], d["target_vol"], t["max_lev"], t["band"], cost, delay=delay, funding=f)
        per_coin.append(r)
    return basket(per_coin)


def run(cfg, dates, ohlc, fund, res=None):
    res = res or pipeline.run(cfg, dates, ohlc, fund)
    off = res["offset"]
    wc, wt = cfg["allocator"]["fixed"]["carry"], cfg["allocator"]["fixed"]["trend"]
    rows = []
    for name, p in SCENARIOS:
        tr = trend_basket(cfg, dates, ohlc, fund, p["cost"], p["delay"], p["perp"])[off:]
        comb = [wc * a + wt * b for a, b in zip(res["carry"], tr)]
        rows.append((name, stats(tr), stats(comb), tr))
    base_dev = max(abs(a - b) for a, b in zip(rows[0][3], res["trend"]))
    return rows, base_dev, res


def fmt(x):
    return f"{x * 100:+.1f}%"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sensitivity")
    ap.add_argument("--config", default="quant_40.yaml")
    a = ap.parse_args(argv)
    with open(a.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["data_dir"] = os.path.join(os.path.dirname(os.path.abspath(a.config)), cfg["data_dir"])
    dates, ohlc, fund = data.load_all(cfg)
    rows, dev, res = run(cfg, dates, ohlc, fund)
    print(f"Trend-Sensitivitaet {res['dates'][0]} bis {res['dates'][-1]} ({len(res['dates'])} Tage), {len(SCENARIOS)} Szenarien")
    print(f"{'Szenario':<38}{'Trend CAGR':>11}{'Sharpe':>8}{'MaxDD':>9}   {'Profil40 CAGR':>14}{'Sharpe':>8}{'MaxDD':>9}")
    for name, st, sc, _ in rows:
        print(f"{name:<38}{fmt(st['cagr']):>11}{st['sharpe']:>8.2f}{fmt(st['max_dd']):>9}   {fmt(sc['cagr']):>14}{sc['sharpe']:>8.2f}{fmt(sc['max_dd']):>9}")
    print(f"\nKontrolle: Basis gegen Pipeline-Trend, groesste Tagesabweichung {dev:.2e} (soll ~0 sein)")
    print("Hinweise: Perp-Zeile nutzt Binance-Funding als Naeherung fuer Hyperliquid. Verzoegerung 1 Tag ist eine strenge Obergrenze.")


if __name__ == "__main__":
    main()
