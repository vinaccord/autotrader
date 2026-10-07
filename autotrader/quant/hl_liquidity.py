"""Liquiditaets-Check Hyperliquid: Spot (UBTC/UETH gegen USDC) gegen Perp (BTC/ETH).

python -m autotrader.quant.hl_liquidity [--sizes 1000,10000,50000]

Nur Lesen (oeffentliche /info-Abfragen), keine Schluessel, keine Orders. Zeigt je Markt: Mid, Spread, 24h-Volumen und die
Kosten (Abweichung vom Mid in bps), um mit einer Marktorder die angegebene USD-Summe zu kaufen oder zu verkaufen.
Dazu die Abweichung Spot-Mid gegen Perp-Mid (Basis). Ein dauerhaft grosser Abstand waere ein Warnsignal fuer die Bridge.
"""
import argparse

import requests

from . import data

HL = "https://api.hyperliquid.xyz/info"
PAIRS = [("UBTC", "BTC"), ("UETH", "ETH")]


def walk_book(levels, usd):
    """Kauft/verkauft `usd` Notional durch die Ebenen [(px, sz), ...] (beste zuerst).
    Gibt (durchschnittlicher Preis, gefuellter Notional) zurueck. Reicht das Buch nicht, ist der Fill kleiner als usd."""
    left, cost, qty = float(usd), 0.0, 0.0
    for px, sz in levels:
        px, sz = float(px), float(sz)
        take = min(left, px * sz)
        if take <= 0:
            break
        cost += take
        qty += take / px
        left -= take
        if left <= 1e-9:
            break
    return (cost / qty if qty else None), cost


def impact_bps(book, usd):
    """-> dict mit mid, spread_bps, buy_bps, sell_bps, buy_fill, sell_fill (Abweichung vom Mid in bps, positiv = teurer)."""
    bids = [(l["px"], l["sz"]) for l in book["levels"][0]]
    asks = [(l["px"], l["sz"]) for l in book["levels"][1]]
    bb, ba = float(bids[0][0]), float(asks[0][0])
    mid = (bb + ba) / 2
    pb, fb = walk_book(asks, usd)
    ps, fs = walk_book(bids, usd)
    return {
        "mid": mid,
        "spread_bps": (ba - bb) / mid * 1e4,
        "buy_bps": (pb / mid - 1) * 1e4 if pb else None,
        "sell_bps": (1 - ps / mid) * 1e4 if ps else None,
        "buy_fill": fb,
        "sell_fill": fs,
    }


def find_spot(meta, base_name):
    """Index und Name (z.B. '@142') des Paares base/USDC in spotMeta. None, wenn nicht vorhanden."""
    toks = meta["tokens"]
    idx = {t["name"]: t["index"] for t in toks}
    if base_name not in idx or "USDC" not in idx:
        return None
    for u in meta["universe"]:
        if u["tokens"] == [idx[base_name], idx["USDC"]]:
            return u["index"], u["name"]
    return None


def _post(s, body):
    return data._request(s, "POST", HL, json=body).json()


def check(sizes, session=None, log=print):
    s = session or requests.Session()
    meta, ctxs = _post(s, {"type": "spotMetaAndAssetCtxs"})
    perp_meta, perp_ctxs = _post(s, {"type": "metaAndAssetCtxs"})
    perp_names = [u["name"] for u in perp_meta["universe"]]
    out = {}
    names = [t["name"] for t in meta["tokens"] if t["name"].startswith("U")]
    log(f"Spot-Token mit U-Praefix auf Hyperliquid: {', '.join(sorted(names)) or '-'}")
    for spot_base, perp_coin in PAIRS:
        found = find_spot(meta, spot_base)
        if not found:
            log(f"\n{spot_base}/USDC: Paar nicht gefunden")
            continue
        i, name = found
        sb = _post(s, {"type": "l2Book", "coin": name})
        pb = _post(s, {"type": "l2Book", "coin": perp_coin})
        sv = float(ctxs[i]["dayNtlVlm"])
        pv = float(perp_ctxs[perp_names.index(perp_coin)]["dayNtlVlm"])
        log(f"\n{spot_base}/USDC (Buch {name}): 24h-Volumen {sv:,.0f} USD   |   Perp {perp_coin}: 24h-Volumen {pv:,.0f} USD")
        res = {}
        for label, book in (("Spot", sb), ("Perp", pb)):
            res[label] = {n: impact_bps(book, n) for n in sizes}
            r0 = res[label][sizes[0]]
            log(f"  {label}: Mid {r0['mid']:,.2f}, Spread {r0['spread_bps']:.1f} bps")
            for n in sizes:
                r = res[label][n]
                buy = f"{r['buy_bps']:.1f}" if r["buy_bps"] is not None else "-"
                sell = f"{r['sell_bps']:.1f}" if r["sell_bps"] is not None else "-"
                warn = "" if min(r["buy_fill"], r["sell_fill"]) >= n * 0.999 else "  (Buch zu duenn: nicht voll gefuellt)"
                log(f"    {n:>9,} USD: kaufen {buy:>6} bps, verkaufen {sell:>6} bps{warn}")
        basis = (res["Spot"][sizes[0]]["mid"] / res["Perp"][sizes[0]]["mid"] - 1) * 1e4
        log(f"  Basis Spot-Mid gegen Perp-Mid: {basis:+.1f} bps")
        out[spot_base] = res
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hl_liquidity")
    ap.add_argument("--sizes", default="1000,10000,50000")
    a = ap.parse_args(argv)
    check([int(x) for x in a.sizes.split(",")])
    print("\nRichtwert: Das Backtest-Modell nimmt 10 bps pro Seite (7 bps Taker-Gebuehr + Slippage). Gebuehr kommt zu den Zahlen oben dazu.")


if __name__ == "__main__":
    main()
