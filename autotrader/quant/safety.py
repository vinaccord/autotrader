"""Technische Sicherungen nach docs/HANDOFF.md 7.2 (live_plan.yaml, Abschnitt safety). Reine Funktionen, keine Netzwerkzugriffe.
Jede Pruefung gibt eine Liste von Verstoessen zurueck (leer = in Ordnung). Ein Verstoss heisst: kein Handel, Alarm per ntfy.
Fehlende Eingaben gelten als Verstoss (fail-closed).
"""
import datetime as dt


def data_age(last_date, now, max_hours):
    """last_date: letzter Kerzentag (YYYY-MM-DD). Die Tageskerze ist um 00:00 UTC des Folgetags abgeschlossen."""
    if not last_date:
        return ["Datenalter unbekannt"]
    closed = dt.datetime.fromisoformat(last_date).replace(tzinfo=dt.timezone.utc) + dt.timedelta(days=1)
    age = (now - closed).total_seconds() / 3600
    return [f"Daten {age:.0f} h alt (max. {max_hours} h)"] if age > max_hours else []


def source_divergence(a, b, max_div):
    """a, b: dict Coin -> Schlusskurs gleicher Tag aus zwei Quellen."""
    out = []
    for c in a:
        if c not in b or not b[c] or not a[c]:
            out.append(f"{c}: zweite Quelle fehlt")
            continue
        d = abs(a[c] / b[c] - 1)
        if d > max_div:
            out.append(f"{c}: Quellen weichen {d:.1%} ab (max. {max_div:.0%})")
    return out


def usdc_peg(price, floor):
    if price is None:
        return ["USDC-Kurs unbekannt"]
    return [f"USDC bei {price:.4f} (unter {floor})"] if price < floor else []


def unit_deviation(unit_px, ref_px, max_dev):
    """unit_px/ref_px: dict Token -> Preis (Spot-Unit-Token gegen Referenz, z.B. Perp-Mid)."""
    out = []
    for t, p in unit_px.items():
        r = ref_px.get(t)
        if not p or not r:
            out.append(f"{t}: Referenzkurs fehlt")
        elif abs(p / r - 1) > max_dev:
            out.append(f"{t}: Abweichung {abs(p / r - 1):.1%} vom Referenzkurs (max. {max_dev:.0%}), nicht kaufen")
    return out


def orders(order_usd, equity, turnover_today, max_order_frac, max_daily_turnover_frac):
    """order_usd: Liste der Orderwerte (USD, positiv) dieses Laufs; turnover_today: bereits gehandelter Umsatz heute."""
    out = []
    if equity <= 0:
        return ["Kontowert unbekannt oder null"]
    for v in order_usd:
        if v > max_order_frac * equity:
            out.append(f"Einzelorder {v:,.0f} USD ueber {max_order_frac:.0%} des Kontowerts")
    if turnover_today + sum(order_usd) > max_daily_turnover_frac * equity:
        out.append(f"Tagesumsatz ueber {max_daily_turnover_frac:.0%} des Kontowerts")
    return out


def position_mismatch(target_usd, actual_usd, equity, max_frac):
    out = []
    if equity <= 0:
        return ["Kontowert unbekannt oder null"]
    for k in set(target_usd) | set(actual_usd):
        d = abs(target_usd.get(k, 0.0) - actual_usd.get(k, 0.0)) / equity
        if d > max_frac:
            out.append(f"{k}: Soll/Ist-Abweichung {d:.1%} des Kontowerts (max. {max_frac:.0%})")
    return out
