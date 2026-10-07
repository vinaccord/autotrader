"""Kill-Switch nach docs/HANDOFF.md 7.2, Werte aus live_plan.yaml (kill_switch).

Stufen (gemessen ab Hoechststand des Kontowerts, High-Water-Mark):
  normal -> warn (-20%) -> brake (-30%, Exposure x0.5, Rueckkehr erst unter -20%) -> stop (-40% oder Kontowert < 60% der Einzahlungen)
Stop ist klebrig: nur ein bewusster Reset durch Patrick (`reset(state)`) hebt ihn auf.
Ein- und Auszahlungen verschieben den Hoechststand (record_flow), sonst wuerde eine Auszahlung wie ein Verlust aussehen.
Reine Funktionen ohne Netzwerk. Die Statusdatei wird atomar geschrieben.
"""
import json
import os

LEVELS = ("normal", "warn", "brake", "stop")
MULT = {"normal": 1.0, "warn": 1.0, "brake": 0.5, "stop": 0.0}


def new_state(equity, deposits=None):
    return {"hwm": float(equity), "level": "normal", "deposits": float(deposits if deposits is not None else equity)}


def record_flow(state, equity_before, amount):
    """Einzahlung (amount > 0) oder Auszahlung (amount < 0) verbuchen. equity_before = Kontowert unmittelbar vorher."""
    s = dict(state)
    if amount >= 0:
        s["hwm"] = s["hwm"] + amount
    else:
        if equity_before <= 0 or -amount >= equity_before:
            raise ValueError("Auszahlung groesser als Kontowert")
        s["hwm"] = s["hwm"] * (equity_before + amount) / equity_before
    s["deposits"] = max(0.0, s["deposits"] + amount)
    return s


def evaluate(state, equity, ks):
    """-> (neuer_state, info). info: level, dd, exposure_mult, changed, reasons. ks = kill_switch-Abschnitt der Config."""
    s = dict(state)
    prev = s["level"]
    s["hwm"] = max(s["hwm"], float(equity))
    dd = 1 - equity / s["hwm"] if s["hwm"] > 0 else 1.0
    reasons = []
    if prev == "stop":
        level = "stop"
        reasons.append("Stopp aktiv, Neustart nur durch Patrick")
    elif dd >= ks["stop_dd"]:
        level = "stop"
        reasons.append(f"Verlust {dd:.1%} ab Hoechststand (Stopp ab {ks['stop_dd']:.0%})")
    elif s["deposits"] > 0 and equity < ks["stop_below_deposits"] * s["deposits"]:
        level = "stop"
        reasons.append(f"Kontowert {equity:,.0f} unter {ks['stop_below_deposits']:.0%} der Einzahlungen {s['deposits']:,.0f}")
    elif prev == "brake" and dd >= ks["brake_release_dd"]:
        level = "brake"
        reasons.append(f"Bremse bleibt, bis der Verlust unter {ks['brake_release_dd']:.0%} liegt (jetzt {dd:.1%})")
    elif dd >= ks["brake_dd"]:
        level = "brake"
        reasons.append(f"Verlust {dd:.1%} ab Hoechststand (Bremse ab {ks['brake_dd']:.0%})")
    elif dd >= ks["warn_dd"]:
        level = "warn"
        reasons.append(f"Verlust {dd:.1%} ab Hoechststand (Warnung ab {ks['warn_dd']:.0%})")
    else:
        level = "normal"
    s["level"] = level
    return s, {"level": level, "dd": dd, "exposure_mult": MULT[level], "changed": level != prev, "previous": prev, "reasons": reasons}


def global_check(total_equity, global_hwm, ks):
    """Gemeinsamer Stopp ueber alle Wallets. -> (neuer_global_hwm, stop: bool, dd)."""
    hwm = max(global_hwm, float(total_equity))
    dd = 1 - total_equity / hwm if hwm > 0 else 1.0
    return hwm, dd >= ks["global_stop_dd"], dd


def reset(state, equity):
    """Bewusster Neustart nach Stopp (nur auf Patricks ausdruecklichen Befehl): Hoechststand = aktueller Kontowert."""
    s = dict(state)
    s["hwm"] = float(equity)
    s["level"] = "normal"
    return s


def load(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# --- Kommandozeile: Status, Ein-/Auszahlung verbuchen, Neustart nach Stopp -------------------------------------------
FLOW_FIELDS = ["ts", "wallet", "mode", "kind", "amount", "equity_before", "hwm_before", "hwm_after", "deposits_after"]


def _flow_log(path, row):
    import csv

    first = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FLOW_FIELDS)
        if first:
            w.writeheader()
        w.writerow(row)
        f.flush()
        os.fsync(f.fileno())


def cli(argv=None, out=print):
    """python -m autotrader.quant.killswitch status|flow|reset --config quant_40.yaml [--mode live|dryrun] [--wallet A]

    flow: Einzahlung (--amount 500) oder Auszahlung (--amount -200 --equity-before KONTOWERT). Ohne --confirm nur Vorschau.
    Reihenfolge: ERST verbuchen, DANN einzahlen/auszahlen und keinen Live-Lauf dazwischen. Sonst zaehlt eine Einzahlung doppelt.
    reset: nur nach Stopp und nur auf Patricks ausdruecklichen Befehl (--equity AKTUELLER KONTOWERT --confirm).
    """
    import argparse
    import datetime as dt

    import yaml

    ap = argparse.ArgumentParser(prog="killswitch")
    ap.add_argument("action", choices=["status", "flow", "reset"])
    ap.add_argument("--config", default="quant_40.yaml")
    ap.add_argument("--mode", choices=["live", "dryrun"], default="live")
    ap.add_argument("--wallet", default="A")
    ap.add_argument("--amount", type=float)
    ap.add_argument("--equity-before", type=float)
    ap.add_argument("--equity", type=float)
    ap.add_argument("--confirm", action="store_true")
    a = ap.parse_args(argv)
    with open(a.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    d = os.path.join(os.path.dirname(os.path.abspath(a.config)), cfg["data_dir"])
    path = os.path.join(d, f"killswitch_{a.wallet}_{a.mode}.json")
    st = load(path)
    if st is None:
        raise SystemExit(f"Kein Zustand unter {path}. Er entsteht beim ersten Lauf mit diesem Modus.")
    out(f"Zustand {a.wallet}/{a.mode}: Stufe {st['level']}, Hoechststand {st['hwm']:,.2f}, Einzahlungen {st['deposits']:,.2f}")
    if a.action == "status":
        return 0
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if a.action == "flow":
        if a.amount is None or a.amount == 0:
            raise SystemExit("--amount fehlt (positiv = Einzahlung, negativ = Auszahlung).")
        if a.amount < 0 and a.equity_before is None:
            raise SystemExit("Auszahlung braucht --equity-before (Kontowert unmittelbar vor der Auszahlung).")
        try:
            new = record_flow(st, a.equity_before if a.equity_before is not None else 0.0, a.amount)
        except ValueError as e:
            raise SystemExit(str(e))
        kind = "Einzahlung" if a.amount > 0 else "Auszahlung"
        out(f"{kind} {abs(a.amount):,.2f}: Hoechststand {st['hwm']:,.2f} -> {new['hwm']:,.2f}, Einzahlungen {st['deposits']:,.2f} -> {new['deposits']:,.2f}")
        if not a.confirm:
            out("Nur Vorschau. Mit --confirm verbuchen (vor der echten Ueberweisung, kein Live-Lauf dazwischen).")
            return 0
        save(path, new)
        _flow_log(os.path.join(d, "killswitch_flows.csv"), {"ts": ts, "wallet": a.wallet, "mode": a.mode, "kind": kind, "amount": a.amount,
                                                            "equity_before": a.equity_before if a.equity_before is not None else "", "hwm_before": st["hwm"],
                                                            "hwm_after": new["hwm"], "deposits_after": new["deposits"]})
        out("Verbucht.")
        return 0
    # reset
    if st["level"] != "stop":
        raise SystemExit("Reset nur nach Stopp. Aktuelle Stufe ist nicht 'stop'.")
    if a.equity is None or a.equity <= 0:
        raise SystemExit("--equity (aktueller Kontowert, positiv) fehlt.")
    new = reset(st, a.equity)
    out(f"Neustart: Hoechststand {st['hwm']:,.2f} -> {new['hwm']:,.2f}, Stufe stop -> normal")
    if not a.confirm:
        out("Nur Vorschau. Mit --confirm ausfuehren, nur auf Patricks ausdruecklichen Befehl.")
        return 0
    save(path, new)
    _flow_log(os.path.join(d, "killswitch_flows.csv"), {"ts": ts, "wallet": a.wallet, "mode": a.mode, "kind": "Reset", "amount": "", "equity_before": a.equity,
                                                        "hwm_before": st["hwm"], "hwm_after": new["hwm"], "deposits_after": new["deposits"]})
    out("Neustart verbucht.")
    return 0


if __name__ == "__main__":
    cli()
