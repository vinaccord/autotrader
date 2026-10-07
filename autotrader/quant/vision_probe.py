"""Phase 2, Schritt 1: Enthaelt Binance Data Vision auch Coins, die heute nicht mehr gehandelt werden (ausgelistet)?

python -m autotrader.quant.vision_probe

Vergleicht die Symbole im Data-Vision-Archiv (Spot, Monatsdaten, Tageskerzen) mit den Symbolen, die Binance heute handelt
(api.binance.com/api/v3/exchangeInfo). Symbole im Archiv, die heute nicht TRADING sind, sind Kandidaten fuer ausgelistete Coins.
Fuer einige Kandidaten wird gezeigt, von wann bis wann Tageskerzen vorliegen.
Nur Lesen, keine Schluessel. Die Listen-URL (S3-Bucket-Listing) stammt aus dem Gedaechtnis und ist in der Binance-Doku nicht beschrieben:
Fehlermeldungen darum genau ansehen. Fallback: auf data.binance.vision im Browser die Ordner durchklicken.
"""
import re
import xml.etree.ElementTree as ET

import requests

from . import data

BUCKET = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
BASE = "data/spot/monthly/klines/"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
WATCH = ["LUNAUSDT", "LUNCUSDT", "FTTUSDT", "SRMUSDT", "BTCUSDT", "ETHUSDT"]


def parse_listing(xml_text):
    """-> (prefixes, keys, next_marker, truncated). Funktioniert mit und ohne Namespace."""
    root = ET.fromstring(xml_text)

    def find(tag):
        return [e for e in root.iter() if e.tag.split("}")[-1] == tag]

    prefixes = [p.text for cp in find("CommonPrefixes") for p in cp if p.tag.split("}")[-1] == "Prefix"]
    keys = [k.text for c in find("Contents") for k in c if k.tag.split("}")[-1] == "Key"]
    truncated = any((e.text or "").strip().lower() == "true" for e in find("IsTruncated"))
    nm = [e.text for e in find("NextMarker")]
    return prefixes, keys, (nm[0] if nm else None), truncated


def list_all(session, prefix, delimiter="/", max_pages=200):
    """Alle Praefixe und Schluessel unter prefix (mit Seitenwechsel)."""
    prefixes, keys, marker = [], [], None
    for _ in range(max_pages):
        params = {"delimiter": delimiter, "prefix": prefix}
        if marker:
            params["marker"] = marker
        r = data._request(session, "GET", BUCKET, params=params)
        p, k, nm, trunc = parse_listing(r.text)
        prefixes += p
        keys += k
        if not trunc:
            break
        marker = nm or (p[-1] if p else (k[-1] if k else None))
        if not marker:
            break
    return prefixes, keys


def symbols_from_prefixes(prefixes):
    return sorted({p.rstrip("/").split("/")[-1] for p in prefixes})


def classify(vision_syms, trading_syms, quote="USDT"):
    """-> (aktuell_im_archiv, nicht_mehr_gehandelt). Nur Paare mit der Quote-Waehrung; gehebelte Token (UP/DOWN/BULL/BEAR) raus."""
    lev = re.compile(r"(UP|DOWN|BULL|BEAR)" + quote + "$")
    base = [s for s in vision_syms if s.endswith(quote) and not lev.search(s)]
    now = sorted(s for s in base if s in trading_syms)
    gone = sorted(s for s in base if s not in trading_syms)
    return now, gone


def month_range(keys):
    """Aus Dateinamen wie 'XYZUSDT-1d-2021-05.zip' -> (erster, letzter) Monat."""
    ms = sorted(m.group(1) for k in keys for m in [re.search(r"-(\d{4}-\d{2})\.zip$", k)] if m)
    return (ms[0], ms[-1]) if ms else (None, None)


def trading_symbols(session):
    r = data._request(session, "GET", "https://api.binance.com/api/v3/exchangeInfo")
    return {s["symbol"] for s in r.json()["symbols"] if s.get("status") == "TRADING"}


def probe(session=None, log=print, sample=8):
    s = session or requests.Session()
    prefixes, _ = list_all(s, BASE)
    vision = symbols_from_prefixes(prefixes)
    log(f"Data Vision, Spot monatlich: {len(vision)} Symbole im Archiv")
    now, gone = classify(vision, trading_symbols(s))
    log(f"USDT-Paare im Archiv: {len(now) + len(gone)}, davon heute gehandelt {len(now)}, nicht mehr gehandelt {len(gone)}")
    log(f"Beispiele nicht mehr gehandelt: {', '.join(gone[:30]) or '-'}")
    for w in WATCH:
        log(f"  {w}: {'im Archiv' if w in vision else 'FEHLT im Archiv'}, {'gehandelt' if w in now else 'nicht gehandelt'}")
    shown = [g for g in gone if g in WATCH] + [g for g in gone if g not in WATCH]
    for g in shown[:sample]:
        _, keys = list_all(s, f"{BASE}{g}/1d/")
        first, last = month_range(keys)
        log(f"  {g}: Tageskerzen {first} bis {last} ({len([k for k in keys if k.endswith('.zip')])} Monate)")
    return {"vision": vision, "now": now, "gone": gone}


def main():
    probe()
    print("\nLesart: Stehen ausgelistete Coins (gone) mit Kerzen bis zum Ende ihrer Handelszeit im Archiv, taugt Data Vision fuer ein ueberlebensfreies Universum.")
    print("Sind es kaum Symbole oder fehlen bekannte Faelle, bleibt jedes Mehr-Coin-Ergebnis ueberlebensverzerrt und muss so beschriftet werden.")


if __name__ == "__main__":
    main()
