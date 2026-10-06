"""Makro-Ebene (Beobachtungsmodus): Fear-&-Greed-Index (mit Historie, backtestbar) und GDELT-Tonalitaet (nur vorwaerts geloggt).

Befehle:  python -m autotrader.quant.macro --config quant_40.yaml fetch|backtest

Annahmen und Grenzen:
- Fear & Greed: oeffentliche API von alternative.me, nach Doku geschrieben, in der Build-Umgebung nicht live getestet.
- GDELT DOC 2.0 durchsucht laut Ankuendigung ein rollendes 3-Monats-Fenster. Fuer einen langen Backtest taugt es nicht;
  wir loggen deshalb taeglich und bauen eine eigene Historie auf.
- Die Regeln aendern die Positionen NICHT. Sie werden nur gegen den Trend-Teil gerechnet und im Bericht angezeigt.
"""
import argparse
import datetime as dt
import os
import urllib.parse

import requests
import yaml

from . import data
from .metrics import stats, yearly

FNG_URL = "https://api.alternative.me/fng/"
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Regeln: Name -> Funktion(fng_wert) -> Multiplikator der Trend-Position. Bewusst wenige, um Zufallstreffer zu begrenzen.
RULES = {
    "greed_cut": lambda v: 0.5 if v >= 75 else 1.0,   # extreme Gier: halbe Position
    "fear_cut": lambda v: 0.5 if v <= 20 else 1.0,    # extreme Angst: halbe Position
}


def parse_fng(payload):
    """alternative.me-Antwort -> {datum: wert}. Erwartet {'data': [{'value': '47', 'timestamp': '1700000000'}, ...]}."""
    out = {}
    for row in payload.get("data", []):
        d = dt.datetime.fromtimestamp(int(row["timestamp"]), tz=dt.timezone.utc).strftime("%Y-%m-%d")
        out[d] = float(row["value"])
    return out


def fetch_fng(session=None):
    s = session or requests.Session()
    r = s.get(FNG_URL, params={"limit": 0, "format": "json"}, timeout=30)
    r.raise_for_status()
    return parse_fng(r.json())


def parse_gdelt_tone(payload):
    """GDELT TimelineTone-Antwort -> Mittelwert der Tonalitaet (oder None)."""
    vals = []
    for series in payload.get("timeline", []):
        for pt in series.get("data", []):
            try:
                vals.append(float(pt["value"]))
            except (KeyError, TypeError, ValueError):
                continue
    return sum(vals) / len(vals) if vals else None


def fetch_gdelt_tone(query, session=None, timespan="24h"):
    s = session or requests.Session()
    r = s.get(GDELT_URL, params={"query": query, "mode": "TimelineTone", "format": "json", "timespan": timespan}, timeout=45)
    r.raise_for_status()
    return parse_gdelt_tone(r.json())


def fng_path(cfg):
    return os.path.join(cfg["data_dir"], "fng.csv")


def tone_path(cfg):
    return os.path.join(cfg["data_dir"], "gdelt_tone.csv")


def load_fng(cfg):
    p = fng_path(cfg)
    if not os.path.exists(p):
        return {}
    return {d: float(v) for d, v in data.load_rows(p)}


def append_tone(cfg, today, tones):
    """Haengt eine Zeile pro Tag an (ueberschreibt nicht)."""
    p = tone_path(cfg)
    names = list(tones)
    header = ["date"] + names
    rows = data.load_rows(p) if os.path.exists(p) else []
    if any(r[0] == today for r in rows):
        return False
    rows.append([today] + ["" if tones[n] is None else f"{tones[n]:.3f}" for n in names])
    data.save_rows(p, header, rows)
    return True


def apply_rule(rule, dates, fng, trend_rets, cost_bps=10, lag=1):
    """Multiplikator je Tag aus dem F&G-Wert von `lag` Tagen davor. Fehlt ein Wert, gilt 1.0. Wechselkosten auf die Aenderung."""
    out, prev = [], 1.0
    for i, (d, r) in enumerate(zip(dates, trend_rets)):
        j = i - lag
        v = fng.get(dates[j]) if j >= 0 else None
        m = RULES[rule](v) if v is not None else 1.0
        cost = abs(m - prev) * cost_bps / 1e4 * (1.0 if r != 0 else 0.0)
        out.append(m * r - cost)
        prev = m
    return out


def run_backtest(trend_rets, dates, fng, cost_bps=10):
    res = {"Trend ohne Makro": trend_rets}
    for name in RULES:
        res[f"Trend + {name}"] = apply_rule(name, dates, fng, trend_rets, cost_bps)
    return res


def cmd_backtest(cfg, log=print):
    from . import pipeline

    fng = load_fng(cfg)
    if not fng:
        raise SystemExit("Keine Fear-&-Greed-Daten. Zuerst `fetch` ausfuehren.")
    dates, ohlc, fund = data.load_all(cfg)
    res = pipeline.run(cfg, dates, ohlc, fund)
    d = res["dates"]
    covered = sum(1 for x in d if x in fng)
    log(f"Out-of-Sample {d[0]} bis {d[-1]} ({len(d)} Tage), F&G-Abdeckung {covered}/{len(d)} Tage, Regeln getestet: {len(RULES)}")
    out = run_backtest(res["trend"], d, fng, cfg["costs"]["trend_bps"])
    log(f"{'Variante':<26}{'CAGR':>9}{'Vol':>8}{'Sharpe':>8}{'MaxDD':>9}")
    for name, rets in out.items():
        s = stats(rets)
        log(f"{name:<26}{s['cagr'] * 100:>+8.1f}%{s['vol'] * 100:>7.1f}%{s['sharpe']:>8.2f}{s['max_dd'] * 100:>+8.1f}%")
    base = stats(out["Trend ohne Makro"])
    for name, rets in out.items():
        if name == "Trend ohne Makro":
            continue
        s = stats(rets)
        better = s["sharpe"] > base["sharpe"] + 0.1 and s["max_dd"] >= base["max_dd"]
        log(f"  {name}: Sharpe {s['sharpe'] - base['sharpe']:+.2f}, MaxDD {(s['max_dd'] - base['max_dd']) * 100:+.1f} Pp -> {'Hinweis auf Nutzen, weiter beobachten' if better else 'kein klarer Nutzen'}")
    log("\nJahre (Sharpe je Variante):")
    ys = {n: yearly(d, r) for n, r in out.items()}
    for y in ys["Trend ohne Makro"]:
        log(f"  {y}: " + ", ".join(f"{n.replace('Trend + ', '').replace('Trend ohne Makro', 'ohne')} {ys[n][y]['sharpe']:.2f}" for n in out))
    log("\nHinweis: Zwei feste Regeln, kein Parameter-Suchlauf. Ein Vorteil ueber einen Zyklus ist ein Indiz, kein Beleg. Positionen werden nicht veraendert.")


def cmd_fetch(cfg, log=print, session=None):
    fng = fetch_fng(session)
    data.save_rows(fng_path(cfg), ["date", "value"], sorted(fng.items()))
    log(f"Fear & Greed: {len(fng)} Tage ({min(fng)} bis {max(fng)})")
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    tones = {}
    for name, q in (cfg.get("macro", {}).get("queries") or {}).items():
        try:
            tones[name] = fetch_gdelt_tone(q, session)
        except (requests.RequestException, ValueError) as e:
            tones[name] = None
            log(f"GDELT {name}: Fehler {type(e).__name__}")
    if tones:
        added = append_tone(cfg, today, tones)
        log(f"GDELT-Tonalitaet {today}: " + ", ".join(f"{k} {v:.2f}" if v is not None else f"{k} -" for k, v in tones.items()) + ("" if added else " (Tag schon vorhanden)"))


def latest_line(cfg):
    """Eine Zeile fuer den Tagesbericht."""
    fng = load_fng(cfg)
    if not fng:
        return None
    d = max(fng)
    v = fng[d]
    states = [n for n, f in RULES.items() if f(v) < 1.0]
    return f"Stimmung (Beobachtung): Fear & Greed {v:.0f} am {d}" + (f", Regel {', '.join(states)} wuerde die Trend-Position halbieren" if states else ", keine Regel aktiv")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="macro")
    ap.add_argument("--config", default="quant_40.yaml")
    ap.add_argument("cmd", choices=["fetch", "backtest"])
    a = ap.parse_args(argv)
    with open(a.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["data_dir"] = os.path.join(os.path.dirname(os.path.abspath(a.config)), cfg["data_dir"])
    (cmd_fetch if a.cmd == "fetch" else cmd_backtest)(cfg)


if __name__ == "__main__":
    main()
