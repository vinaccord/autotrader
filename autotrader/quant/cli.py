"""Kommandozeile: python -m autotrader.quant.cli --config quant.yaml <fetch|backtest|signal>"""
import argparse
import os

import yaml

from . import data, pipeline
from .metrics import stats, yearly


def pct(x):
    return f"{x * 100:+.1f}%" if x is not None else "-"


def pct_plain(x):
    return f"{x * 100:.1f}%"


def print_summary(res):
    print(f"\nOut-of-Sample ab {res['dates'][0]} bis {res['dates'][-1]} ({len(res['dates'])} Tage), Parameter-Varianten getestet: {res['trials']}")
    print(f"{'Strategie':<36}{'CAGR':>9}{'Vol':>8}{'Sharpe':>8}{'MaxDD':>9}{'Calmar':>8}")
    for label, s in pipeline.summary(res):
        cal = f"{s['calmar']:.2f}" if s["calmar"] is not None else "-"
        print(f"{label:<36}{pct(s['cagr']):>9}{pct_plain(s['vol']):>8}{s['sharpe']:>8.2f}{pct(s['max_dd']):>9}{cal:>8}")
    print("\nJahre (adaptiv kombiniert):")
    for y, s in yearly(res["dates"], res["combined"]).items():
        print(f"  {y}: Rendite {pct(s['total'])}, Sharpe {s['sharpe']:.2f}, MaxDD {pct(s['max_dd'])}")
    print("\nGewaehlte Parameter (letzte 3 Fenster):")
    for name in ("carry_chosen", "trend_chosen"):
        for t, p in res[name][-3:]:
            print(f"  {name[:5]} ab Tag {t}: {p}")
    if res["weights"]:
        print(f"Aktuelle Gewichte: {res['weights'][-1][1]}")
    print(
        "\nHinweise: Ergebnisse sind ein Backtest mit Annahmen zu Kosten und Ausfuehrung. Je mehr Varianten getestet wurden,"
        "\nje eher ist ein gutes Ergebnis Zufall. Nur Out-of-Sample-Zahlen zaehlen."
        "\nCarry-Modell ignoriert Basis-Schwankungen zwischen Spot und Perp, Plattformausfall und Kapitalkosten des Transfers"
        "\n(Margin-Ausgleich und Liquidation des Short-Beins sind grob abgebildet). Ein sehr hoher Carry-Sharpe ist darum ein Warnsignal und kein Beleg."
    )


def main(argv=None):
    ap = argparse.ArgumentParser(prog="quant")
    ap.add_argument("--config", default="quant.yaml")
    ap.add_argument("cmd", choices=["fetch", "backtest", "signal"])
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    base = os.path.dirname(os.path.abspath(args.config))
    cfg["data_dir"] = os.path.join(base, cfg["data_dir"])

    if args.cmd == "fetch":
        data.fetch_all(cfg)
        return
    dates, ohlc, fund = data.load_all(cfg)
    need = cfg["walkforward"]["train_days"] + 365
    if len(dates) < need:
        raise SystemExit(f"Zu wenig Daten ({len(dates)} Tage, benoetigt mindestens {need}). Zuerst `fetch` ausfuehren oder start frueher setzen.")
    res = pipeline.run(cfg, dates, ohlc, fund)
    if args.cmd == "backtest":
        print_summary(res)
    else:
        sig = pipeline.signal(cfg, dates, ohlc, fund, res)
        print(f"Signal Stand {sig['as_of']} (Parameter: Carry {sig['carry_params']}, Trend {sig['trend_params']})")
        print(f"Gewichte: {sig['weights']}")
        for c, v in sig["carry"].items():
            apr = f"{v['trailing_apr'] * 100:.1f}%" if v["trailing_apr"] is not None else "-"
            print(f"  Carry {c}: {'IN POSITION (Spot long, Perp short)' if v['in_position'] else 'flat'}, Funding trailing {apr} p.a.")
        for c, v in sig["trend"].items():
            print(f"  Trend {c}: Ziel-Exposure {v['target_exposure']:.2f}")


if __name__ == "__main__":
    main()
