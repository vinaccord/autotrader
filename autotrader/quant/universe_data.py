"""Phase 2, Schritt 3: Tageskerzen aller USDT-Spot-Paare aus Binance Data Vision, inklusive ausgelisteter Paare.

python -m autotrader.quant.universe_data [--out data/quant_universe] [--workers 6] [--symbols A,B] [--limit N]

Je Symbol: Monats-ZIPs (1d) plus Tages-ZIPs fuer die Monate nach dem letzten Monats-ZIP (der letzte, unvollstaendige Monat steht
nur als Tagesdatei im Archiv, bei ausgelisteten Coins sind das oft die Crash-Tage vor dem Delisting). Jede ZIP wird gegen die
.CHECKSUM-Datei (SHA-256) geprueft. Ergebnis: <out>/<SYMBOL>.csv mit date,open,high,low,close,volume,quote_volume,trades.
Fortsetzbar: <out>/manifest.json merkt sich verarbeitete Dateien, ein erneuter Lauf laedt nur Neues (z.B. neue Tage).
Ausgeschlossen: gehebelte Token (UP/DOWN/BULL/BEAR) und bekannte Stablecoins als Basiswaehrung. Weitere Stablecoin-Erkennung per Kurs
passiert spaeter beim Bau des Universums.
Hinweis zu Umbenennungen: Binance benennt Symbole um oder vergibt sie neu (z.B. LUNA/LUNC, MATIC/POL). Der Verlauf eines Symbols
kann darum Spruenge enthalten. Das Universum muss das beachten.
Server-Lauf als einmaliger Dienst:  sudo systemd-run --uid=autotrader --working-directory=/opt/autotrader --unit=universe-fetch \
  /opt/autotrader/venv/bin/python -m autotrader.quant.universe_data
"""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
import re
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor

import requests

from . import data, vision_probe

FILES = "https://data.binance.vision/"
MONTHLY = "data/spot/monthly/klines/"
DAILY = "data/spot/daily/klines/"
STABLE_BASES = {"USDC", "BUSD", "TUSD", "USDP", "DAI", "FDUSD", "USDD", "UST", "USTC", "AEUR", "EUR", "EURI", "PAXG", "XUSD", "USD1", "PYUSD", "SUSD", "GUSD", "BFUSD"}
FIELDS = ["date", "open", "high", "low", "close", "volume", "quote_volume", "trades"]
_lock = threading.Lock()


def eligible(symbol, quote="USDT"):
    if not symbol.endswith(quote):
        return False
    base = symbol[: -len(quote)]
    if re.search(r"(UP|DOWN|BULL|BEAR)$", base) and len(base) > 4:
        return False
    return base not in STABLE_BASES


def to_day(ts):
    """Zeitstempel in ms oder (ab 2025) Mikrosekunden -> YYYY-MM-DD (UTC)."""
    t = int(ts)
    if t > 10**14:
        t //= 1000
    return data.day_str(t)


def parse_csv(text):
    """Binance-Kline-CSV -> Liste (date, o, h, l, c, volume, quote_volume, trades). Kopfzeilen werden uebersprungen."""
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 9 or not row[0].strip().isdigit():
            continue
        out.append((to_day(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]), float(row[7]), int(float(row[8]))))
    return out


def verify_and_read(zip_bytes, checksum_text):
    """Prueft SHA-256 gegen den Inhalt der .CHECKSUM-Datei ('<hash>  <name>') und gibt den CSV-Text zurueck. ValueError bei Abweichung."""
    want = checksum_text.split()[0].strip().lower()
    got = hashlib.sha256(zip_bytes).hexdigest()
    if want != got:
        raise ValueError(f"Pruefsumme falsch (erwartet {want[:12]}, erhalten {got[:12]})")
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        return z.read(z.namelist()[0]).decode("utf-8")


def _month_of(key):
    m = re.search(r"-(\d{4}-\d{2})(?:-\d{2})?\.zip$", key)
    return m.group(1) if m else None


def keys_for(session, symbol):
    """Monats-ZIPs plus Tages-ZIPs fuer Monate nach dem letzten Monats-ZIP, aelteste zuerst."""
    _, mk = vision_probe.list_all(session, f"{MONTHLY}{symbol}/1d/")
    monthly = sorted(k for k in mk if k.endswith(".zip"))
    last = _month_of(monthly[-1]) if monthly else None
    _, dk = vision_probe.list_all(session, f"{DAILY}{symbol}/1d/")
    daily = sorted(k for k in dk if k.endswith(".zip") and (last is None or _month_of(k) > last))
    return monthly + daily


def load_manifest(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_manifest(path, m):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_symbol_csv(path):
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        next(r, None)
        return {row[0]: tuple([row[0]] + [float(x) for x in row[1:7]] + [int(float(row[7]))]) for row in r}


def fetch_symbol(session, symbol, out_dir, done_keys, log=print):
    """Laedt neue Dateien eines Symbols. -> (neue_keys, Fehlerliste). Schreibt die Symbol-CSV atomar."""
    keys = keys_for(session, symbol)
    new = [k for k in keys if k not in done_keys]
    if not new:
        return [], []
    path = os.path.join(out_dir, f"{symbol}.csv")
    rows = read_symbol_csv(path)
    ok, bad = [], []
    for k in new:
        try:
            z = data._request(session, "GET", FILES + k).content
            c = data._request(session, "GET", FILES + k + ".CHECKSUM").text
            for r in parse_csv(verify_and_read(z, c)):
                rows[r[0]] = r
            ok.append(k)
        except Exception as e:  # einzelne Datei darf das Symbol nicht killen; wird gemeldet und beim naechsten Lauf erneut versucht
            bad.append(f"{k}: {type(e).__name__} {e}")
    if ok:
        data.save_rows(path, FIELDS, [rows[d][0:8] for d in sorted(rows)])
    return ok, bad


def run(out_dir, workers=6, symbols=None, limit=None, session_factory=requests.Session, log=print):
    os.makedirs(out_dir, exist_ok=True)
    mpath = os.path.join(out_dir, "manifest.json")
    manifest = load_manifest(mpath)
    s0 = session_factory()
    prefixes, _ = vision_probe.list_all(s0, MONTHLY)
    allsyms = [s for s in vision_probe.symbols_from_prefixes(prefixes) if eligible(s)]
    todo = list(symbols) if symbols else allsyms
    if limit:
        todo = todo[:limit]
    log(f"{len(allsyms)} USDT-Symbole im Archiv, {len(todo)} im Lauf, {workers} Arbeiter")
    stats = {"files": 0, "symbols_new": 0, "failed": []}
    count = [0]

    def work(sym):
        s = session_factory()
        try:
            ok, bad = fetch_symbol(s, sym, out_dir, set(manifest.get(sym, [])), log)
        except Exception as e:
            ok, bad = [], [f"{sym}: Liste/Abruf {type(e).__name__} {e}"]
        with _lock:
            if ok:
                manifest[sym] = sorted(set(manifest.get(sym, [])) | set(ok))
                save_manifest(mpath, manifest)
                stats["symbols_new"] += 1
            stats["files"] += len(ok)
            stats["failed"] += bad
            count[0] += 1
            if count[0] % 25 == 0 or count[0] == len(todo):
                log(f"  {count[0]}/{len(todo)} Symbole, {stats['files']} Dateien, {len(stats['failed'])} Fehler")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, todo))
    rep = [f"Lauf {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC: {len(todo)} Symbole, {stats['files']} neue Dateien, {len(stats['failed'])} Fehler"] + stats["failed"][:200]
    with open(os.path.join(out_dir, "universe_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(rep) + "\n")
    log(rep[0])
    for line in stats["failed"][:10]:
        log("  FEHLER " + line)
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(prog="universe_data")
    ap.add_argument("--out", default="data/quant_universe")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)
    run(a.out, a.workers, [x for x in a.symbols.split(",") if x] or None, a.limit or None)


if __name__ == "__main__":
    main()
