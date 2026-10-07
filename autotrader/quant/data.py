"""Datenbeschaffung und Cache. Binance (lange Historie, oeffentlich) und Hyperliquid (Zielplattform).

Alle Fetcher sind nach der oeffentlichen Doku geschrieben, aber in der Build-Umgebung nicht live
getestet (Netzwerk gesperrt). Beim ersten Lauf `fetch` ausfuehren und Zeilenzahlen pruefen.
Wenn eine Quelle blockiert, eigene CSV-Dateien im Cache-Format ablegen (siehe save_*).
"""
import csv
import datetime as dt
import os
import time

import requests

DAY_MS = 86_400_000


def day_str(ts_ms):
    return dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d")


def ms(date_str):
    d = dt.datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp() * 1000)


def daily_sum(rows):
    """[(ts_ms, rate)] -> {datum: Summe der Raten dieses UTC-Tages}."""
    out = {}
    for ts, rate in rows:
        d = day_str(ts)
        out[d] = out.get(d, 0.0) + rate
    return out


# --- CSV-Cache ----------------------------------------------------------
def save_rows(path, header, rows):
    """Atomar: erst in eine Temp-Datei, dann umbenennen. Ein Abbruch hinterlaesst nie eine halbe Datei."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    os.replace(tmp, path)


def count_rows(path):
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as f:
        return max(sum(1 for _ in f) - 1, 0)


def save_if_not_shrunk(path, header, rows, log, label, tolerance=0.98):
    """Schreibt nur, wenn die neue Reihe nicht deutlich kuerzer ist als der Cache. Schuetzt vor Teil-Abrufen."""
    old = count_rows(path)
    if old and len(rows) < old * tolerance:
        log(f"{label}: neuer Abruf hat {len(rows)} statt {old} Zeilen, Cache bleibt unveraendert")
        return False
    save_rows(path, header, rows)
    return True


def load_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        next(r)
        return [row for row in r]


def load_ohlc(path):
    """-> {datum: (open, high, low, close)}; unvollstaendigen heutigen Tag verwerfen."""
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    out = {}
    for ts, o, h, l, c, *_ in load_rows(path):
        d = day_str(int(ts))
        if d < today:
            out[d] = (float(o), float(h), float(l), float(c))
    return out


def load_funding(path):
    return daily_sum([(int(ts), float(rate)) for ts, rate in load_rows(path)])


# --- HTTP mit Wiederholung ----------------------------------------------
RETRY_STATUS = {429, 500, 502, 503, 504}


def _request(s, method, url, tries=4, backoff=2.0, **kw):
    """GET/POST mit bis zu `tries` Versuchen bei Zeitueberschreitung, Verbindungsfehler, 429 oder 5xx."""
    last = None
    for k in range(tries):
        try:
            r = s.request(method, url, timeout=kw.pop("timeout", 30), **kw)
            if r.status_code in RETRY_STATUS and k < tries - 1:
                time.sleep(backoff * (2 ** k))
                continue
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
            if k < tries - 1:
                time.sleep(backoff * (2 ** k))
    raise last


# --- Binance ------------------------------------------------------------
def fetch_binance_klines(symbol, start_ms, session=None):
    s = session or requests.Session()
    rows, cur = [], start_ms
    while True:
        r = _request(s, "GET", "https://api.binance.com/api/v3/klines",
                     params={"symbol": symbol, "interval": "1d", "startTime": cur, "limit": 1000})
        data = r.json()
        if not data:
            break
        rows += [(int(k[0]), k[1], k[2], k[3], k[4], k[5]) for k in data]
        if len(data) < 1000:
            break
        cur = int(data[-1][0]) + DAY_MS
        time.sleep(0.3)
    return rows


def fetch_binance_funding(symbol, start_ms, session=None):
    s = session or requests.Session()
    rows, cur = [], start_ms
    while True:
        r = _request(s, "GET", "https://fapi.binance.com/fapi/v1/fundingRate",
                     params={"symbol": symbol, "startTime": cur, "limit": 1000})
        data = r.json()
        if not data:
            break
        rows += [(int(x["fundingTime"]), x["fundingRate"]) for x in data]
        if len(data) < 1000:
            break
        cur = int(data[-1]["fundingTime"]) + 1
        time.sleep(0.3)
    return rows


# --- Hyperliquid --------------------------------------------------------
HL = "https://api.hyperliquid.xyz/info"


def fetch_hl_candles(coin, start_ms, session=None):
    s = session or requests.Session()
    end = int(time.time() * 1000)
    r = _request(s, "POST", HL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d", "startTime": start_ms, "endTime": end}})
    return [(int(k["t"]), k["o"], k["h"], k["l"], k["c"], k["v"]) for k in r.json()]


def fetch_hl_funding(coin, start_ms, session=None):
    s = session or requests.Session()
    rows, cur, seen = [], start_ms, set()
    while True:
        r = _request(s, "POST", HL, json={"type": "fundingHistory", "coin": coin, "startTime": cur})
        data = r.json()
        new = [(int(x["time"]), x["fundingRate"]) for x in data if int(x["time"]) not in seen]
        if not new:
            break
        for t, _ in new:
            seen.add(t)
        rows += new
        cur = max(t for t, _ in new) + 1
        time.sleep(0.3)
    return rows


# --- Orchestrierung -----------------------------------------------------
def cache_path(cfg, kind, coin):
    return os.path.join(cfg["data_dir"], f"{cfg['source']}_{kind}_{coin}.csv")


def fetch_all(cfg, log=print, session=None):
    """Laedt Preise und Funding je Coin. Scheitert ein Coin, wird er uebersprungen und sein Cache bleibt unberuehrt.
    Scheitert nur das Funding, bleibt der bisherige Funding-Cache stehen (nie mit Leerem ueberschreiben)."""
    start = ms(cfg["start"])
    s = session or requests.Session()
    failed = []
    for coin in cfg["coins"]:
        fu, fu_ok = [], True
        try:
            if cfg["source"] == "binance":
                sym = f"{coin}USDT"
                px = fetch_binance_klines(sym, start, s)
                try:
                    fu = fetch_binance_funding(sym, start, s)
                except Exception as e:
                    fu_ok = False
                    log(f"{coin}: Funding-Abruf fehlgeschlagen ({type(e).__name__}), alter Funding-Cache bleibt")
            else:
                px = fetch_hl_candles(coin, start, s)
                fu = fetch_hl_funding(coin, start, s)
            if not px:
                raise ValueError("keine Kerzen")
        except Exception as e:
            failed.append(coin)
            log(f"{coin}: uebersprungen ({type(e).__name__}: {e}), alter Cache bleibt")
            continue
        save_if_not_shrunk(cache_path(cfg, "prices", coin), ["ts", "open", "high", "low", "close", "volume"], px, log, f"{coin} Preise")
        if fu_ok and fu:
            save_if_not_shrunk(cache_path(cfg, "funding", coin), ["ts", "rate"], fu, log, f"{coin} Funding")
        first = day_str(int(px[0][0]))
        log(f"{coin}: {len(px)} Tageskerzen ab {first}, {len(fu)} Funding-Eintraege")
    if failed:
        log(f"Uebersprungen: {', '.join(failed)}")
    if failed and len(failed) == len(cfg["coins"]):
        raise SystemExit("Kein Coin konnte geladen werden.")


def load_all(cfg, log=print):
    """-> (dates, ohlc{coin:{date:(o,h,l,c)}}, funding{coin:{date:rate_sum}}).

    Kalender = Tage, an denen alle Coins einen Preis haben, ab dem ersten und bis zum letzten Funding-Tag aller Coins.
    Fehlt innerhalb davon ein Funding-Tag, bleibt der Tag im Kalender und das Funding zaehlt 0 (statt zwei Tage zu einer Rendite zu verschmelzen).
    Luecken im Preis-Kalender werden gemeldet (die Rendite ueber die Luecke ist dann eine Mehrtages-Rendite)."""
    ohlc = {c: load_ohlc(cache_path(cfg, "prices", c)) for c in cfg["coins"]}
    fund = {c: dict(load_funding(cache_path(cfg, "funding", c))) for c in cfg["coins"]}
    common = None
    for c in cfg["coins"]:
        ds = set(ohlc[c])
        common = ds if common is None else common & ds
    dates = sorted(common or [])
    if not dates or any(not fund[c] for c in cfg["coins"]):
        return [], ohlc, fund
    lo = max(min(fund[c]) for c in cfg["coins"])
    hi = min(max(fund[c]) for c in cfg["coins"])
    if dates[-1] > hi:
        log(f"Funding endet {hi}, Preise bis {dates[-1]}: Kalender endet am {hi}")
    dates = [d for d in dates if lo <= d <= hi]
    for c in cfg["coins"]:
        miss = [d for d in dates if d not in fund[c]]
        if miss:
            log(f"Funding-Luecke {c}: {len(miss)} Tage (z.B. {miss[0]}) zaehlen als 0")
            for d in miss:
                fund[c][d] = 0.0
    gaps = [(a, b) for a, b in zip(dates, dates[1:]) if (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days > 1]
    if gaps:
        log(f"Preis-Luecken im Kalender: {len(gaps)} (z.B. {gaps[0][0]} bis {gaps[0][1]}), Rendite dort ueber mehrere Tage")
    return dates, ohlc, fund
