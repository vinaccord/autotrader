"""Vorab festgelegter Carry-Test auf Hyperliquid-Funding (Regeln: docs/CARRY_HL_TEST.md).

python -m autotrader.quant.carry_hl --config quant_40.yaml [--fetch]

Liest nur Cache-Dateien (HL-Funding aus fundcmp, Binance-Funding und Preise aus dem Tageslauf). Aendert nichts an Strategie oder Papierbetrieb.
Exit-Code 0 immer, das Ergebnis steht in der Ausgabe (Entscheidungsregel am Ende).
"""
import argparse
import os

import yaml

from . import data, fundcmp
from .metrics import stats
from .strategies import basket, carry_returns
from .walkforward import make_grid, walk_forward

HL_FRAC = 23 / 24
MIN_DAYS_AFTER_TRAIN = 120


def doubled(costs):
    return {k: v * 2 for k, v in costs.items()}


def load_inputs(cfg, log=print):
    """-> None, wenn eine Cache-Datei fehlt, sonst (dates, ohlc, bn, hl, n_missing). Nur Tage zwischen erstem und letztem gemeinsamen vollen HL-Tag; fehlendes Funding zaehlt 0."""
    coins = cfg["coins"]
    needed = [fundcmp.hl_path(cfg, c) for c in coins] + [data.cache_path(cfg, k, c) for c in coins for k in ("prices", "funding")]
    if not all(os.path.exists(x) for x in needed):
        return None
    ohlc = {c: data.load_ohlc(data.cache_path(cfg, "prices", c)) for c in coins}
    bn_all = {c: dict(data.load_funding(data.cache_path(cfg, "funding", c))) for c in coins}
    hl_all = {}
    for c in coins:
        rows = [(int(t), float(r)) for t, r in data.load_rows(fundcmp.hl_path(cfg, c))]
        hl_all[c], _ = fundcmp.hl_full_days(rows)
    if any(not hl_all[c] for c in coins):
        return None
    lo = max(min(hl_all[c]) for c in coins)
    hi = min(max(hl_all[c]) for c in coins)
    dates = sorted(set.intersection(*[set(ohlc[c]) for c in coins]))
    dates = [d for d in dates if lo <= d <= hi]
    missing = sum(1 for c in coins for d in dates if d not in hl_all[c])
    bn = {c: {d: bn_all[c].get(d, 0.0) for d in dates} for c in coins}
    hl = {c: {d: hl_all[c].get(d, 0.0) for d in dates} for c in coins}
    return dates, ohlc, bn, hl, missing


def _fixed(cfg, dates, ohlc, fund, costs, frac):
    cc = cfg["carry"]
    d = cc["default"]
    per = [carry_returns(dates, fund[c], ohlc[c], d["lookback"], d["entry_apr"], d["exit_apr"], cc["lev"], costs, entry_day_frac=frac) for c in cfg["coins"]]
    return basket([p[0] for p in per]), {"liq": sum(p[1]["liq_flags"] for p in per), "entries": sum(p[1]["entries"] for p in per),
                                         "days_in": sum(p[1]["days_in"] for p in per), "rebalances": sum(p[1]["rebalances"] for p in per)}


def _walk(cfg, dates, ohlc, fund, costs, frac):
    cc, wf = cfg["carry"], cfg["walkforward"]
    cands = []
    for p in make_grid(cc["grid"]):
        if p["exit_apr"] >= p["entry_apr"]:
            continue
        per = [carry_returns(dates, fund[c], ohlc[c], p["lookback"], p["entry_apr"], p["exit_apr"], cc["lev"], costs, entry_day_frac=frac)[0] for c in cfg["coins"]]
        cands.append((p, basket(per)))
    oos, off, _ = walk_forward(cands, wf["train_days"], wf["step_days"], wf["switch_cost_bps"] / 1e4)
    return oos, off, len(cands)


def summarize(rets):
    st = stats(rets)
    h = len(rets) // 2
    return {"total": st["total"], "cagr": st["cagr"], "max_dd": st["max_dd"], "sharpe": st["sharpe"], "n": st["n"],
            "half1": stats(rets[:h])["total"], "half2": stats(rets[h:])["total"]}


def run_variants(cfg, dates, ohlc, bn, hl):
    costs = cfg["costs"]
    c2 = doubled(costs)
    off = cfg["walkforward"]["train_days"]
    if len(dates) < off + MIN_DAYS_AFTER_TRAIN:
        return None
    out, info = {}, {}
    r, i = _fixed(cfg, dates, ohlc, bn, costs, 1.0)
    out["V0 Binance, Standard"], info["V0"] = summarize(r[off:]), i
    r, i = _fixed(cfg, dates, ohlc, hl, costs, HL_FRAC)
    out["V1 HL, Standard"], info["V1"] = summarize(r[off:]), i
    r, i = _fixed(cfg, dates, ohlc, hl, c2, HL_FRAC)
    out["V1x2 HL, Standard, Kosten x2"], info["V1x2"] = summarize(r[off:]), i
    r, o, n = _walk(cfg, dates, ohlc, hl, costs, HL_FRAC)
    out["V2 HL, Walk-Forward"] = summarize(r)
    r, o, n = _walk(cfg, dates, ohlc, hl, c2, HL_FRAC)
    out["V2x2 HL, Walk-Forward, Kosten x2"] = summarize(r)
    r, o, n = _walk(cfg, dates, ohlc, bn, costs, 1.0)
    out["V3 Binance, Walk-Forward"] = summarize(r)
    return {"res": out, "info": info, "candidates": n, "window": (dates[off], dates[-1])}


def decide(res, info, min_cagr=0.04, max_dd=-0.10):
    d = res["V2x2 HL, Walk-Forward, Kosten x2"]
    checks = [
        (f"Gesamtertrag > 0 und CAGR >= {min_cagr:.0%}", d["total"] > 0 and d["cagr"] >= min_cagr, f"Total {d['total']:+.1%}, CAGR {d['cagr']:+.1%}"),
        (f"Max. Verlust nicht schlechter als {max_dd:.0%}", d["max_dd"] >= max_dd, f"{d['max_dd']:+.1%}"),
        ("Beide Haelften > 0", d["half1"] > 0 and d["half2"] > 0, f"{d['half1']:+.1%} / {d['half2']:+.1%}"),
        ("Keine Liquidation (V1x2)", info["V1x2"]["liq"] == 0, f"{info['V1x2']['liq']} Liquidationen"),
    ]
    return all(c[1] for c in checks), checks


def report(v, missing, ndays, log=print):
    res = v["res"]
    log(f"Carry-Test auf HL-Funding: {ndays} Tage, Fenster {v['window'][0]} bis {v['window'][1]}, fehlende HL-Tage (als 0 gezaehlt): {missing}")
    log(f"{'Lauf':<36}{'Total':>8}{'CAGR':>8}{'MaxDD':>8}{'Sharpe':>8}{'Haelfte 1':>11}{'Haelfte 2':>11}")
    for k, s in res.items():
        log(f"{k:<36}{s['total']:>+8.1%}{s['cagr']:>+8.1%}{s['max_dd']:>+8.1%}{s['sharpe']:>8.2f}{s['half1']:>+11.1%}{s['half2']:>+11.1%}")
    i = v["info"]["V1"]
    log(f"V1: {i['entries']} Einstiege, {i['days_in']} Coin-Tage in Position, {i['rebalances']} Margin-Ausgleiche")
    ok, checks = decide(res, v["info"])
    log("Entscheidungsregel (V2x2, vorab festgelegt):")
    for name, passed, detail in checks:
        log(f"  {'ERFUELLT' if passed else 'VERFEHLT '} {name}: {detail}")
    log("ERGEBNIS: " + ("alle Kriterien erfuellt, Carry-Ausfuehrung kann gebaut werden (Entscheid Patrick)." if ok else "mindestens ein Kriterium verfehlt, Carry nicht bauen."))
    log(f"Hinweise: {v['candidates']} Kandidaten im Raster, 6 Laeufe, ein Marktregime, Basisrisiko nur modelliert. Binance-Zeilen sind Kontrollen.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="carry_hl")
    ap.add_argument("--config", default="quant_40.yaml")
    ap.add_argument("--fetch", action="store_true", help="HL-Funding-Historie vorher nachladen (Netzwerk)")
    a = ap.parse_args(argv)
    with open(a.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["data_dir"] = os.path.join(os.path.dirname(os.path.abspath(a.config)), cfg["data_dir"])
    if a.fetch:
        fundcmp.fetch(cfg)
    inp = load_inputs(cfg)
    if inp is None:
        print("Keine HL-Funding-Daten (oder Preis-/Funding-Cache) gefunden. Zuerst fundcmp laufen lassen oder --fetch.")
        return 1
    dates, ohlc, bn, hl, missing = inp
    v = run_variants(cfg, dates, ohlc, bn, hl)
    if v is None:
        print(f"Nur {len(dates)} Tage, fuer {cfg['walkforward']['train_days']} Tage Training plus Fenster zu wenig.")
        return 1
    report(v, missing, len(dates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
