"""Append-only Ledger: das feste Papier-Protokoll fuer die Live-Entscheidung.

Zeilen werden nur angehaengt, nie geaendert. Pro Tag und Coin zwei Arten:
  signal   : Zielzustand nach Tagesschluss `date` (Trend-Exposure, Carry ja/nein, Schlusskurs, Gewichte)
  realised : Rendite des Folgetags (Schlusskurs Tag+1 gegen Tag), erst geschrieben, wenn der Folgetag in den Daten ist
Ein (kind, date, coin) wird nie doppelt geschrieben. Wer das Ledger spaeter ansieht, sieht, was am Signaltag
bekannt war, nicht was ein neu gerechneter Backtest heute behaupten wuerde.
"""
import csv
import datetime as dt
import os

FIELDS = ["written_at", "profile", "kind", "date", "coin", "trend_exposure", "carry_in", "close", "next_day_ret", "w_trend", "w_carry"]


def _read(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _append(path, rows):
    if not rows:
        return 0
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
        f.flush()
        os.fsync(f.fileno())
    return len(rows)


def update(path, profile, sig, dates, ohlc, now=None):
    """Haengt Signal des letzten Tages und fehlende Folgetag-Renditen an. Gibt (n_signal, n_realised) zurueck."""
    now = now or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    have = {(r["profile"], r["kind"], r["date"], r["coin"]) for r in _read(path)}
    idx = {d: i for i, d in enumerate(dates)}
    close = lambda coin, d: ohlc[coin][d][3]
    out = []
    asof = sig["as_of"]
    w = sig.get("weights", {})
    for coin, t in sig["trend"].items():
        if (profile, "signal", asof, coin) in have:
            continue
        out.append({"written_at": now, "profile": profile, "kind": "signal", "date": asof, "coin": coin,
                    "trend_exposure": round(t["target_exposure"], 4),
                    "carry_in": int(bool(sig["carry"].get(coin, {}).get("in_position"))),
                    "close": close(coin, asof), "w_trend": w.get("trend", ""), "w_carry": w.get("carry", "")})
    n_sig = len(out)
    # Folgetag-Renditen fuer alle frueheren Signaltage, deren Folgetag jetzt vorliegt
    pend = sorted({(r["date"], r["coin"]) for r in _read(path) if r["profile"] == profile and r["kind"] == "signal"})
    for d, coin in pend:
        if (profile, "realised", d, coin) in have or d not in idx or idx[d] + 1 >= len(dates) or coin not in ohlc:
            continue
        nd = dates[idx[d] + 1]
        c0, c1 = close(coin, d), close(coin, nd)
        out.append({"written_at": now, "profile": profile, "kind": "realised", "date": d, "coin": coin,
                    "close": c1, "next_day_ret": round(c1 / c0 - 1, 6)})
    _append(path, out)
    return n_sig, len(out) - n_sig
