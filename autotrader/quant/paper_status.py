"""Papierbetrieb gegen die Go/No-Go-Kriterien A bis C auswerten (docs/STRATEGIE.md Abschnitt 8).

cd /opt/autotrader && sudo -u autotrader venv/bin/python -m autotrader.quant.paper_status --config quant_40.yaml [--start 2026-10-06] [--days 56]

Nur lesen: daily.log, ledger.csv, orders_dryrun.csv, paper_account_A.json, killswitch_A_dryrun.json. Kein Netz, keine Schreibzugriffe,
keine Aenderung an Strategie oder Signal. Fehlende Daten heissen "nicht auswertbar", es wird nichts geschaetzt.
Exit-Code 1 nur, wenn ein Kriterium verletzt ist (A) bzw. B/C klar ausserhalb der Grenze liegen.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
from collections import Counter

import yaml

from .hl_exec import UNIT

RUN_RE = re.compile(r"^=== (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) ===")
FAIL_RE = re.compile(r"^!!! Schritt fehlgeschlagen: (.+)$")
EXEC_RE = re.compile(r"Trockenlauf Wallet \w+, Signal (\d{4}-\d\d-\d\d), Kontowert ([\d,\.]+) USD")
ZIEL_RE = re.compile(r"^\s*Ziel (\w+): Exposure [\d.\-]+ -> ([\d,\.\-]+) USD (\w+)")
GRACE_HOUR_UTC = 3  # der Timer laeuft um 01:05 UTC, erst danach gilt der heutige Tag als verpasst


def _num(s):
    return float(s.replace(",", ""))


def _utc(ts):
    return dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def _csv(path):
    if not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_runs(text):
    """daily.log -> Liste von Laeufen: {ts, day, failed, fehler, lines}. Ein Lauf beginnt mit '=== <UTC-Zeit> ==='."""
    runs = []
    for line in text.splitlines():
        m = RUN_RE.match(line)
        if m:
            ts = _utc(m.group(1))
            runs.append({"ts": ts, "day": ts.date(), "failed": [], "fehler": False, "lines": []})
            continue
        if not runs:
            continue
        r = runs[-1]
        r["lines"].append(line)
        f = FAIL_RE.match(line)
        if f:
            r["failed"].append(f.group(1).strip())
        if line.startswith("FEHLER in:"):
            r["fehler"] = True
    for r in runs:
        r["clean"] = not r["failed"] and not r["fehler"]
    return runs


def evaluate_a(runs, ledger_rows, start, now, profile="quant_40", total_days=56, max_missed=1, max_gap_h=48.0):
    today = now.date()
    pending_today = now.hour < GRACE_HOUR_UTC
    days, d = [], start
    while d <= today:
        days.append(d)
        d += dt.timedelta(days=1)
    clean_days = {r["day"] for r in runs if r["clean"]}
    ran_days = {r["day"] for r in runs}
    missed = [x for x in days if x not in clean_days and not (x == today and pending_today)]
    failed_days = sorted({r["day"] for r in runs if not r["clean"] and r["day"] not in clean_days})
    ts = sorted(r["ts"] for r in runs if r["clean"])
    gap = max([(b - a).total_seconds() / 3600 for a, b in zip(ts, ts[1:])] + [(now - ts[-1]).total_seconds() / 3600 if ts else 0.0])
    issues = []
    ledger = {"signal_days": 0, "gaps": [], "dups": 0, "missing_realised": [], "available": ledger_rows is not None}
    if ledger_rows is not None:
        rows = [r for r in ledger_rows if r["profile"] == profile]
        cnt = Counter((r["kind"], r["date"], r["coin"]) for r in rows)
        ledger["dups"] = sum(1 for v in cnt.values() if v > 1)
        by_coin = {}
        for r in rows:
            if r["kind"] == "signal":
                by_coin.setdefault(r["coin"], set()).add(r["date"])
        real = {(r["date"], r["coin"]) for r in rows if r["kind"] == "realised"}
        for coin, ds in sorted(by_coin.items()):
            dd = sorted(dt.date.fromisoformat(x) for x in ds)
            ledger["signal_days"] = max(ledger["signal_days"], len(dd))
            full = {dd[0] + dt.timedelta(days=i) for i in range((dd[-1] - dd[0]).days + 1)}
            ledger["gaps"] += [f"{coin} {x}" for x in sorted(full - set(dd))]
            ledger["missing_realised"] += [f"{coin} {x}" for x in dd[:-1] if (x.isoformat(), coin) not in real]
    violated = len(missed) > max_missed or gap > max_gap_h or bool(ledger["gaps"]) or ledger["dups"] > 0 or bool(ledger["missing_realised"])
    n = len(days)
    if violated:
        verdict = "VERLETZT"
    elif n >= total_days:
        verdict = "PASS"
    else:
        verdict = "laeuft, bisher eingehalten"
    return {"n_days": n, "clean_days": len(clean_days & set(days)), "ran_days": len(ran_days & set(days)), "missed": missed, "failed_days": failed_days,
            "gap_h": gap, "ledger": ledger, "verdict": verdict, "violated": violated, "last_run": max((r["ts"] for r in runs), default=None),
            "max_missed": max_missed, "max_gap_h": max_gap_h, "total_days": total_days, "issues": issues}


def _orders(rows):
    """orders_dryrun.csv -> geplante Orders ohne Doppel (cloid), nach Zeit sortiert."""
    seen, out = set(), []
    for r in sorted(rows or [], key=lambda x: x.get("ts", "")):
        if r.get("status") != "planned" or r["cloid"] in seen:
            continue
        seen.add(r["cloid"])
        out.append(r)
    return out


def evaluate_b(runs, ledger_rows, order_rows, paper, profile="quant_40", max_dev=0.05, max_days=3):
    """Papierpositionen gegen Soll (Ziel-USD aus dem Tageslauf). Bestand je Tag aus den geplanten Orders nachgerechnet,
    bewertet mit dem Ledger-Schlusskurs. Naeherung: Ausfuehrungskurs weicht vom Schlusskurs ab."""
    if order_rows is None:
        return {"available": False, "why": "orders_dryrun.csv fehlt"}
    blocks = {}
    for r in runs:  # letzter Lauf je Signaltag gewinnt
        k, tg = None, {}
        for line in r["lines"]:
            m = EXEC_RE.search(line)
            if m:
                k = (m.group(1), _num(m.group(2)))
            z = ZIEL_RE.match(line)
            if z:
                tg[z.group(3)] = _num(z.group(2))
        if k and tg:
            blocks[k[0]] = (k[1], tg)
    if not blocks:
        return {"available": False, "why": "im daily.log keine Zeilen 'Ziel ...' gefunden"}
    close = {(r["date"], r["coin"]): float(r["close"]) for r in (ledger_rows or []) if r["profile"] == profile and r["kind"] == "signal" and r["close"]}
    coin_of = {v: k for k, v in UNIT.items()}
    orders = _orders(order_rows)
    hold, devs, nopx = {}, {}, []
    applied = set()
    for d in sorted(blocks):
        for o in orders:
            if o["date"] <= d and o["cloid"] not in applied:
                applied.add(o["cloid"])
                hold[o["asset"]] = hold.get(o["asset"], 0.0) + (1 if o["side"] == "buy" else -1) * float(o["sz"])
        eq, tg = blocks[d]
        dev = []
        for tok, usd in tg.items():
            px = close.get((d, coin_of.get(tok, "")))
            if px is None or eq <= 0:
                nopx.append(d)
                continue
            dev.append(abs(hold.get(tok, 0.0) * px - usd) / eq)
        if dev:
            devs[d] = max(dev)
    cross = None
    if paper is not None:
        cross = all(abs(hold.get(t, 0.0) - q) <= 1e-6 + 1e-6 * abs(q) for t, q in {**{t: 0.0 for t in hold}, **paper.get("holdings", {})}.items())
    over = sorted(d for d, v in devs.items() if v > max_dev)
    return {"available": bool(devs), "why": "kein Schlusskurs im Ledger" if not devs else "", "days": len(devs), "over": over, "max_dev": max(devs.values(), default=0.0),
            "cross": cross, "ok": len(over) <= max_days, "max_days": max_days, "max_dev_limit": max_dev, "nopx": len(set(nopx))}


def evaluate_c(order_rows, fee_bps, backtest_bps, ratio_limit=2.0):
    if order_rows is None:
        return {"available": False, "why": "orders_dryrun.csv fehlt"}
    orders = _orders(order_rows)
    turnover = sum(float(o["usd"]) for o in orders)
    ratio = fee_bps / backtest_bps if backtest_bps else float("inf")
    return {"available": True, "n": len(orders), "turnover": turnover, "cost": turnover * fee_bps / 1e4, "fee_bps": fee_bps, "backtest_bps": backtest_bps,
            "ratio": ratio, "ok": ratio <= ratio_limit, "limit": ratio_limit}


def evaluate_ks(path, runs):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        st = json.load(f)
    eq = None
    for r in reversed(runs):
        for line in r["lines"]:
            m = EXEC_RE.search(line)
            if m:
                eq = _num(m.group(2))
        if eq is not None:
            break
    hwm = st.get("hwm")
    dd = (1 - eq / hwm) if (eq is not None and hwm) else None
    return {"level": st.get("level"), "hwm": hwm, "equity": eq, "dd": dd}


def render(a, b, c, ks, now):
    L = []
    tag = {True: "PASS", False: "FAIL"}
    L.append(f"Papierstatus {now:%Y-%m-%d %H:%M} UTC, letzter Lauf {a['last_run']:%Y-%m-%d %H:%M} UTC" if a["last_run"] else "Papierstatus: kein Lauf im daily.log")
    L.append(f"A Betrieb: {a['verdict']} (Tag {a['n_days']} von {a['total_days']})")
    L.append(f"  Tage mit sauberem Lauf {a['clean_days']} von {a['n_days']}; verpasst {len(a['missed'])} (erlaubt {a['max_missed']}): {', '.join(map(str, a['missed'])) or '-'}")
    if a["failed_days"]:
        L.append(f"  Tage nur mit fehlgeschlagenen Schritten: {', '.join(map(str, a['failed_days']))}")
    L.append(f"  laengste Luecke {a['gap_h']:.0f} h (Grenze {a['max_gap_h']:.0f} h)")
    lg = a["ledger"]
    if lg["available"]:
        L.append(f"  Ledger: {lg['signal_days']} Signaltage, Luecken {', '.join(lg['gaps']) or '-'}, Doppelte {lg['dups']}, Folgetag-Rendite fehlt {', '.join(lg['missing_realised']) or '-'}")
    else:
        L.append("  Ledger: ledger.csv nicht gefunden")
    if not b["available"]:
        L.append(f"B Positionen: nicht auswertbar ({b['why']})")
    else:
        st = "PASS bisher" if b["ok"] else "FAIL"
        L.append(f"B Positionen: {st} (Naeherung mit Ledger-Schlusskurs)")
        L.append(f"  {b['days']} Tage ausgewertet, groesste Abweichung {b['max_dev']:.1%} (Grenze {b['max_dev_limit']:.0%}), Tage darueber {len(b['over'])} (erlaubt {b['max_days']}): {', '.join(b['over']) or '-'}")
        if b["cross"] is False:
            L.append("  ACHTUNG: aus den Orders nachgerechneter Bestand weicht vom Papierkonto ab, Ergebnis B unsicher")
        elif b["cross"] is None:
            L.append("  Papierkonto nicht gefunden, Bestandsabgleich nicht moeglich")
    if not c["available"]:
        L.append(f"C Kosten: nicht auswertbar ({c['why']})")
    else:
        L.append(f"C Kosten: {tag[c['ok']]} Papier-Gebuehr {c['fee_bps']:g} bps gegen Backtest {c['backtest_bps']:g} bps = {c['ratio']:.2f}x (Grenze {c['limit']:g}x)")
        L.append(f"  {c['n']} Orders, Umsatz {c['turnover']:,.0f} USD, Gebuehren {c['cost']:,.2f} USD. Papier kennt keine Slippage: echte Pruefung erst im Kleinstbetrag-Test (E).")
    if ks:
        dd = f", Verlust ab Hoechststand {ks['dd']:.1%}" if ks["dd"] is not None else ""
        L.append(f"Kill-Switch Papier: {ks['level']}, Hoechststand {ks['hwm']:,.0f} USD{dd}")
    else:
        L.append("Kill-Switch Papier: killswitch_A_dryrun.json nicht gefunden")
    return "\n".join(L)


def main(argv=None, now=None):
    ap = argparse.ArgumentParser(prog="paper_status")
    ap.add_argument("--config", default="quant_40.yaml")
    ap.add_argument("--plan", default="live_plan.yaml")
    ap.add_argument("--start", default="2026-10-06")
    ap.add_argument("--days", type=int, default=56)
    ap.add_argument("--profile", default="quant_40")
    ap.add_argument("--today", default=None, help="JJJJ-MM-TT, nur fuer Tests")
    a = ap.parse_args(argv)
    with open(a.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    d = os.path.join(os.path.dirname(os.path.abspath(a.config)), cfg["data_dir"])
    fee = 7.0
    if os.path.exists(a.plan):
        with open(a.plan, encoding="utf-8") as f:
            fee = float((yaml.safe_load(f) or {}).get("venue", {}).get("fees_bps", {}).get("spot_taker", fee))
    if a.today:
        now = dt.datetime.fromisoformat(a.today).replace(hour=12, tzinfo=dt.timezone.utc)
    now = now or dt.datetime.now(dt.timezone.utc)
    log = os.path.join(d, "daily.log")
    text = ""
    if os.path.exists(log):
        with open(log, encoding="utf-8", errors="replace") as f:
            text = f.read()
    runs = parse_runs(text)
    ledger = _csv(os.path.join(d, "ledger.csv"))
    orders = _csv(os.path.join(d, "orders_dryrun.csv"))
    pp = os.path.join(d, "paper_account_A.json")
    paper = None
    if os.path.exists(pp):
        with open(pp, encoding="utf-8") as f:
            paper = json.load(f)
    res_a = evaluate_a(runs, ledger, dt.date.fromisoformat(a.start), now, a.profile, a.days)
    res_b = evaluate_b(runs, ledger, orders, paper, a.profile)
    res_c = evaluate_c(orders, fee, float(cfg.get("costs", {}).get("trend_bps", 10)))
    ks = evaluate_ks(os.path.join(d, "killswitch_A_dryrun.json"), runs)
    print(render(res_a, res_b, res_c, ks, now))
    bad = res_a["violated"] or (res_b["available"] and not res_b["ok"]) or (res_c["available"] and not res_c["ok"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
