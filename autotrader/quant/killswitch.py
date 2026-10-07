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
