"""Steuer-Export: Handelsliste als CSV fuer den Steuerberater.

python -m autotrader.quant.tax_export --config quant_40.yaml [--source live|dryrun] [--out tax_trades.csv]

Liest orders_live.csv (echte Fills: Status filled/partial, Menge filled_sz zum Durchschnittskurs avg_px) oder orders_dryrun.csv (Papier,
nur zum Formatieren; geplante Orders, Kurs = Limit). Schreibt eine neue CSV, ueberschreibt keine Quelldatei.
Nicht enthalten: CHF-Umrechnung (Kurs je Tag setzt der Berater oder die ESTV-Kursliste ein, Spalte chf_kurs bleibt leer), Funding-Zahlungen
(Carry ist nicht gebaut), Ein-/Auszahlungen (siehe killswitch_flows.csv), Gebuehren aus echten Fills (Hyperliquid-Gebuehr pro Fill ist im Protokoll
noch nicht erfasst, Spalte fee_usd_geschaetzt = Handelswert x spot_taker laut live_plan.yaml).
"""
import argparse
import csv
import os

import yaml

FIELDS = ["zeit_utc", "wallet", "token", "seite", "menge", "kurs_usd", "wert_usd", "fee_usd_geschaetzt", "quelle", "cloid", "chf_kurs", "wert_chf"]


def rows_from(path, source, fee_bps):
    out = []
    if not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if source == "live":
                if r.get("status") not in ("filled", "partial"):
                    continue
                qty, px = float(r.get("filled_sz") or 0), float(r.get("avg_px") or 0)
            else:
                if r.get("status") != "planned":
                    continue
                qty, px = float(r["sz"]), float(r["limit_px"])
            if qty <= 0 or px <= 0 or r.get("side") not in ("buy", "sell"):
                continue
            val = qty * px
            out.append({"zeit_utc": r["ts"], "wallet": r["wallet"], "token": r["asset"], "seite": "Kauf" if r["side"] == "buy" else "Verkauf", "menge": f"{qty:.8f}",
                        "kurs_usd": f"{px:.4f}", "wert_usd": f"{val:.2f}", "fee_usd_geschaetzt": f"{val * fee_bps / 1e4:.4f}", "quelle": source,
                        "cloid": r["cloid"], "chf_kurs": "", "wert_chf": ""})
    seen, uniq = set(), []
    for r in sorted(out, key=lambda x: x["zeit_utc"]):
        if r["cloid"] in seen:
            continue
        seen.add(r["cloid"])
        uniq.append(r)
    return uniq


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tax_export")
    ap.add_argument("--config", default="quant_40.yaml")
    ap.add_argument("--plan", default="live_plan.yaml")
    ap.add_argument("--source", choices=["live", "dryrun"], default="live")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    with open(a.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    d = os.path.join(os.path.dirname(os.path.abspath(a.config)), cfg["data_dir"])
    fee = 7.0
    if os.path.exists(a.plan):
        with open(a.plan, encoding="utf-8") as f:
            fee = float((yaml.safe_load(f) or {}).get("venue", {}).get("fees_bps", {}).get("spot_taker", fee))
    src = os.path.join(d, "orders_live.csv" if a.source == "live" else "orders_dryrun.csv")
    rows = rows_from(src, a.source, fee)
    if rows is None:
        print(f"{os.path.basename(src)} nicht gefunden, nichts exportiert.")
        return 1
    out = a.out or os.path.join(d, f"tax_trades_{a.source}.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} Trades nach {out} geschrieben. CHF-Spalten sind leer (Umrechnung durch Steuerberater).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
