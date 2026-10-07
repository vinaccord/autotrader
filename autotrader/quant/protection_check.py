"""Kriterium D: Schutzmechanismen mit Testdaten ausloesen und das Ergebnis ausgeben.

python -m autotrader.quant.protection_check [--plan live_plan.yaml]

Nimmt die Schwellen aus live_plan.yaml (kill_switch, safety) und spielt feste Szenarien durch. Zeigt je Szenario erwartet gegen tatsaechlich
und beendet mit Exit-Code 1, wenn eines abweicht. Kein Netzwerk, keine Dateien, keine Orders. Aenderst du eine Schwelle in live_plan.yaml,
zeigt dieser Lauf sofort, ob die Szenarien noch greifen. Dokumentation und Stand: docs/KRITERIUM_D.md.
"""
import argparse
import datetime as dt
import os
import sys

import yaml

from . import killswitch as k
from . import safety as sf


def kill_switch_path(ks):
    """Gleitender Kontowert: Hoechststand 1100. Gibt Liste (Beschreibung, erwartete Stufe, tatsaechliche Stufe, Detail) zurueck."""
    out = []
    s = k.new_state(1000)

    def step(desc, equity, expect, mult=None):
        nonlocal s
        s, info = k.evaluate(s, equity, ks)
        ok = info["level"] == expect and (mult is None or info["exposure_mult"] == mult)
        out.append((desc, expect, info["level"], f"Verlust {info['dd']:.1%}, Exposure x{info['exposure_mult']}", ok))

    step("Kontowert steigt auf 1100 (neuer Hoechststand)", 1100, "normal", 1.0)
    step("Verlust ueber Warnschwelle (-21%)", 1100 * (1 - ks["warn_dd"] - 0.01), "warn", 1.0)
    step("Verlust ueber Bremsschwelle (-31%): Exposure halbiert", 1100 * (1 - ks["brake_dd"] - 0.01), "brake", 0.5)
    step("Erholung auf -25%: Bremse bleibt (Hysterese)", 1100 * 0.75, "brake", 0.5)
    step("Erholung auf -15%: Bremse loest sich", 1100 * (1 - ks["brake_release_dd"] + 0.05), "normal", 1.0)
    step("Absturz ueber Stoppschwelle (-41%): alles USDC", 1100 * (1 - ks["stop_dd"] - 0.01), "stop", 0.0)
    step("Kontowert erholt sich auf 1100: Stopp klebt", 1100, "stop", 0.0)
    s = k.reset(s, 900)
    step("Reset durch Patrick, Kontowert 900", 900, "normal", 1.0)
    # Stopp unter Einzahlungen
    s2 = k.new_state(600, deposits=1000)
    s2, info = k.evaluate(s2, 590, ks)
    out.append(("Kontowert 590 bei Einzahlungen 1000 (unter 60%): Stopp", "stop", info["level"], f"Verlust {info['dd']:.1%}", info["level"] == "stop"))
    # Auszahlung ist kein Verlust
    s3 = k.new_state(1000)
    s3 = k.record_flow(s3, 1000, -300)
    s3, info = k.evaluate(s3, 700, ks)
    out.append(("Auszahlung 300 von 1000 verbucht: kein Alarm", "normal", info["level"], f"Verlust {info['dd']:.1%}", info["level"] == "normal"))
    # Auszahlung nicht verbucht: wirkt wie Verlust (zeigt, warum Verbuchen noetig ist)
    s4 = k.new_state(1000)
    s4, info = k.evaluate(s4, 700, ks)
    out.append(("Auszahlung NICHT verbucht: wirkt wie -30% Verlust (Bremse)", "brake", info["level"], f"Verlust {info['dd']:.1%}", info["level"] == "brake"))
    return out


def safety_checks(c):
    now = dt.datetime(2026, 12, 1, 1, 5, tzinfo=dt.timezone.utc)
    rows = []

    def chk(desc, viol, expect_hit):
        rows.append((desc, "Verstoss" if expect_hit else "kein Verstoss", "Verstoss" if viol else "kein Verstoss", "; ".join(viol)[:70], bool(viol) == expect_hit))

    chk("Daten frisch (Tag gestern, Lauf 01:05)", sf.data_age("2026-11-30", now, c["max_data_age_hours"]), False)
    chk("Daten zu alt (letzter Tag vor 4 Tagen)", sf.data_age("2026-11-27", now, c["max_data_age_hours"]), True)
    chk("Datenalter unbekannt (fail-closed)", sf.data_age(None, now, c["max_data_age_hours"]), True)
    chk("Zweite Datenquelle stimmt", sf.source_divergence({"BTC": 100000.0}, {"BTC": 100500.0}, c["max_source_divergence"]), False)
    chk("Quellen weichen 5% ab", sf.source_divergence({"BTC": 100000.0}, {"BTC": 105000.0}, c["max_source_divergence"]), True)
    chk("Zweite Quelle fehlt (fail-closed)", sf.source_divergence({"BTC": 100000.0}, {}, c["max_source_divergence"]), True)
    chk("USDC bei 1.0000", sf.usdc_peg(1.0, c["usdc_depeg_floor"]), False)
    chk("USDC-Entkopplung (0.97)", sf.usdc_peg(0.97, c["usdc_depeg_floor"]), True)
    chk("USDC-Kurs unbekannt (fail-closed)", sf.usdc_peg(None, c["usdc_depeg_floor"]), True)
    chk("Unit-Token nahe am Referenzkurs", sf.unit_deviation({"UBTC": 100100.0}, {"UBTC": 100000.0}, c["unit_token_max_deviation"]), False)
    chk("Unit-Token 5% unter Referenz (Bridge-Problem)", sf.unit_deviation({"UBTC": 95000.0}, {"UBTC": 100000.0}, c["unit_token_max_deviation"]), True)
    chk("Einzelorder 20% des Kontowerts", sf.orders([200.0], 1000.0, 0.0, c["max_order_frac"], c["max_daily_turnover_frac"]), False)
    chk("Einzelorder 40% des Kontowerts", sf.orders([400.0], 1000.0, 0.0, c["max_order_frac"], c["max_daily_turnover_frac"]), True)
    chk("Tagesumsatz ueber Grenze", sf.orders([200.0, 200.0, 200.0, 200.0, 200.0, 200.0], 1000.0, 0.0, c["max_order_frac"], c["max_daily_turnover_frac"]), True)
    chk("Kontowert unbekannt (fail-closed)", sf.orders([10.0], 0.0, 0.0, c["max_order_frac"], c["max_daily_turnover_frac"]), True)
    chk("Soll/Ist nach Ausfuehrung innerhalb 5%", sf.position_mismatch({"UBTC": 500.0}, {"UBTC": 480.0}, 1000.0, c["max_position_mismatch"]), False)
    chk("Soll/Ist weicht 20% ab (Fill fehlt)", sf.position_mismatch({"UBTC": 500.0}, {"UBTC": 300.0}, 1000.0, c["max_position_mismatch"]), True)
    return rows


def main(argv=None, out=print):
    ap = argparse.ArgumentParser(prog="protection_check")
    ap.add_argument("--plan", default="live_plan.yaml")
    a = ap.parse_args(argv)
    with open(a.plan, encoding="utf-8") as f:
        plan = yaml.safe_load(f)
    bad = 0
    for title, rows in (("Kill-Switch (Schwellen aus live_plan.yaml)", kill_switch_path(plan["kill_switch"])), ("Sicherungen (Schwellen aus live_plan.yaml)", safety_checks(plan["safety"]))):
        out(f"\n{title}")
        for desc, expect, got, detail, ok in rows:
            out(f"  {'PASS' if ok else 'FAIL'}  {desc}  [erwartet {expect}, erhalten {got}{'; ' + detail if detail else ''}]")
            bad += 0 if ok else 1
    out(f"\n{'Alle Szenarien wie erwartet.' if not bad else str(bad) + ' Szenario(en) weichen ab, nicht live gehen.'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
