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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


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


# --- Binance ------------------------------------------------------------
def fetch_binance_klines(symbol, start_ms, session=None):
    s = session or requests.Session()
    rows, cur = [], start_ms
    while True:
        r = s.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": "1d", "startTime": cur, "limit": 1000},
            timeout=30,
        )
        r.raise_for_status()
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
        r = s.get(
            "https://fapi.binance.com/fapi/v1/fundingRate",
            params={"symbol": symbol, "startTime": cur, "limit": 1000},
            timeout=30,
        )
        r.raise_for_status()
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
    r = s.post(HL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d", "startTime": start_ms, "endTime": end}}, timeout=30)
    r.raise_for_status()
    return [(int(k["t"]), k["o"], k["h"], k["l"], k["c"], k["v"]) for k in r.json()]


def fetch_hl_funding(coin, start_ms, session=None):
    s = session or requests.Session()
    rows, cur, seen = [], start_ms, set()
    while True:
        r = s.post(HL, json={"type": "fundingHistory", "coin": coin, "startTime": cur}, timeout=30)
        r.raise_for_status()
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


def fetch_all(cfg, log=print):
    """Laedt Preise und Funding je Coin. Scheitert ein Coin (Symbol existiert nicht, gesperrt), wird er uebersprungen."""
    start = ms(cfg["start"])
    failed = []
    for coin in cfg["coins"]:
        try:
            if cfg["source"] == "binance":
                sym = f"{coin}USDT"
                px = fetch_binance_klines(sym, start)
                try:
                    fu = fetch_binance_funding(sym, start)
                except Exception as e:  # Funding ist fuer reine Trend-Profile nicht noetig
                    fu = []
                    log(f"{coin}: Funding nicht verfuegbar ({type(e).__name__})")
            else:
                px = fetch_hl_candles(coin, start)
                fu = fetch_hl_funding(coin, start)
            if not px:
                raise ValueError("keine Kerzen")
        except Exception as e:
            failed.append(coin)
            log(f"{coin}: uebersprungen ({type(e).__name__}: {e})")
            continue
        save_rows(cache_path(cfg, "prices", coin), ["ts", "open", "high", "low", "close", "volume"], px)
        save_rows(cache_path(cfg, "funding", coin), ["ts", "rate"], fu)
        first = day_str(int(px[0][0]))
        log(f"{coin}: {len(px)} Tageskerzen ab {first}, {len(fu)} Funding-Eintraege")
    if failed:
        log(f"Uebersprungen: {', '.join(failed)}")
    if failed and len(failed) == len(cfg["coins"]):
        raise SystemExit("Kein Coin konnte geladen werden.")


def load_all(cfg):
    """-> (dates, ohlc{coin:{date:(o,h,l,c)}}, funding{coin:{date:rate_sum}}) auf gemeinsamem Kalender."""
    ohlc = {c: load_ohlc(cache_path(cfg, "prices", c)) for c in cfg["coins"]}
    fund = {c: load_funding(cache_path(cfg, "funding", c)) for c in cfg["coins"]}
    common = None
    for c in cfg["coins"]:
        ds = set(ohlc[c]) & set(fund[c])
        common = ds if common is None else common & ds
    dates = sorted(common or [])
    return dates, ohlc, fund
