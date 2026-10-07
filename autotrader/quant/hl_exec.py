"""Ausfuehrungsplanung fuer Hyperliquid (Spot, Trend-Teil). NUR TROCKENLAUF: sendet keine Orders, braucht keinen Schluessel.

python -m autotrader.quant.hl_exec --config quant_40.yaml --plan live_plan.yaml

Ablauf: Signal (Profil 40 mit Spill) -> Zielwerte je Unit-Token (UBTC/UETH) -> Kill-Switch-Faktor -> Sicherungen (safety.py)
-> Orderplan mit Mengen-Rundung, Mindestwert, Limitpreis und fester Client-Order-ID -> Protokoll in data/quant/orders_dryrun.csv.
Kontowert: oeffentliche Adresse aus HL_ACCOUNT_ADDRESS (nur Lesen). Ohne Adresse fuehrt der Lauf ein Papierkonto (paper_account_A.json, Start dry_run.paper_equity_usdc):
Orders gelten als zum Mid plus Taker-Gebuehr gefuellt, so entsteht ein fortlaufendes Ausfuehrungs-Protokoll mit echtem Kill-Switch-Verlauf.
Carry-Ausfuehrung (Spot long + Perp short) ist noch nicht gebaut: der Carry-Anteil bleibt im Plan USDC und wird als Hinweis gemeldet.
Live-Modus ist absichtlich gesperrt, bis Patrick im Chat freigibt, das offizielle SDK geprueft und die Version festgenagelt ist.
"""
import argparse
import csv
import datetime as dt
import hashlib
import math
import os

import requests
import yaml

from . import data, hl_liquidity, killswitch, pipeline, safety, spill

UNIT = {"BTC": "UBTC", "ETH": "UETH"}
LOG_FIELDS = ["ts", "date", "wallet", "asset", "side", "sz", "limit_px", "usd", "cloid", "status", "reason"]


def floor_to(x, decimals):
    f = 10 ** decimals
    return math.floor(x * f + 1e-9) / f


def sig_figs(x, n=5):
    if x == 0:
        return 0.0
    return round(x, n - 1 - int(math.floor(math.log10(abs(x)))))


def cloid(wallet, date, asset, side, sz):
    h = hashlib.sha256(f"{wallet}|{date}|{asset}|{side}|{sz}".encode()).hexdigest()
    return "0x" + h[:32]


def targets_usd(ew, exposures, equity, mult, coins):
    """Zielwert je Coin in USD: Trend-Gewicht / Anzahl Coins * Exposure * Kill-Switch-Faktor * Kontowert."""
    n = len(coins)
    return {c: equity * ew["trend"] / n * min(1.0, max(0.0, exposures.get(c, 0.0))) * mult for c in coins}


def plan_orders(target_by_coin, holdings, prices, sz_decimals, equity, wallet, date, min_order_usd=10.0, min_trade_frac=0.02, max_slip_bps=30.0, max_order_frac=0.25):
    """Orderplan fuer Unit-Token. holdings: Token -> Menge, prices: Token -> Mid, sz_decimals: Token -> int.
    Gibt (orders, skipped) zurueck. Orders unter min_trade_frac des Kontowerts werden nicht gehandelt (spart Gebuehren).
    Grosse Aenderungen werden in Teilorders zu hoechstens 90% von max_order_frac des Kontowerts zerlegt (Einzelorder-Grenze der Sicherungen)."""
    orders, skipped = [], []
    for coin, tgt in target_by_coin.items():
        tok = UNIT.get(coin)
        if not tok or tok not in prices or tok not in sz_decimals:
            skipped.append((coin, "kein Spot-Token oder Preis"))
            continue
        px = prices[tok]
        delta = tgt / px - holdings.get(tok, 0.0)
        sz = floor_to(abs(delta), sz_decimals[tok])
        usd = sz * px
        if tgt == 0 and holdings.get(tok, 0.0) > 0:
            pass  # vollstaendig verkaufen ist immer erlaubt, auch unter der Handelsschwelle
        elif usd < min_trade_frac * equity:
            skipped.append((tok, f"Aenderung {usd:,.0f} USD unter {min_trade_frac:.0%} des Kontowerts"))
            continue
        if sz <= 0 or usd < min_order_usd:
            skipped.append((tok, f"Order {usd:,.2f} USD unter Mindestwert {min_order_usd:.0f}"))
            continue
        side = "buy" if delta > 0 else "sell"
        lim = sig_figs(px * (1 + max_slip_bps / 1e4) if side == "buy" else px * (1 - max_slip_bps / 1e4))
        max_sz = floor_to(0.9 * max_order_frac * equity / px, sz_decimals[tok]) if equity > 0 else sz
        parts = max(1, math.ceil(sz / max_sz)) if max_sz > 0 else 1
        left = sz
        for k in range(parts):
            part = left if k == parts - 1 else max_sz
            part = floor_to(part, sz_decimals[tok])
            if part <= 0:
                continue
            left = floor_to(left - part, sz_decimals[tok])
            orders.append({"asset": tok, "side": side, "sz": part, "limit_px": lim, "usd": part * px, "cloid": cloid(wallet, date, tok, side, f"{sz}#{k}")})
    return orders, skipped


def log_orders(path, rows, fields=None):
    """Haengt an. Eine cloid wird nie zweimal protokolliert (idempotent)."""
    seen = set()
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            seen = {r["cloid"] for r in csv.DictReader(f)}
    new = [r for r in rows if r["cloid"] not in seen]
    if not new:
        return 0
    first = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields or LOG_FIELDS)
        if first:
            w.writeheader()
        for r in new:
            w.writerow({k: r.get(k, "") for k in (fields or LOG_FIELDS)})
        f.flush()
        os.fsync(f.fileno())
    return len(new)


def paper_load(path, start_usdc):
    import json
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"usdc": float(start_usdc), "holdings": {}, "fills": 0}


def paper_save(path, st):
    import json
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def paper_fill(st, orders, prices, fee_bps):
    """Papier-Fill: alle Orders zum Mid plus Gebuehr (optimistisch: keine Slippage, kein Teil-Fill)."""
    st = {"usdc": st["usdc"], "holdings": dict(st["holdings"]), "fills": st.get("fills", 0)}
    for o in orders:
        usd = o["sz"] * prices[o["asset"]]
        fee = usd * fee_bps / 1e4
        if o["side"] == "buy":
            if usd + fee > st["usdc"] + 1e-9:
                continue  # nicht genug USDC: Order verfaellt
            st["usdc"] -= usd + fee
            st["holdings"][o["asset"]] = st["holdings"].get(o["asset"], 0.0) + o["sz"]
        else:
            have = st["holdings"].get(o["asset"], 0.0)
            sz = min(o["sz"], have)
            st["usdc"] += sz * prices[o["asset"]] - fee
            st["holdings"][o["asset"]] = have - sz
        st["fills"] += 1
    return st


# --- Lesen von Hyperliquid und CoinGecko (Netzwerk, nur mit Fakes getestet) ---

def fetch_market(session):
    """-> (prices Token->Mid, sz_decimals Token->int, perp_mid Coin->Mid)."""
    meta, _ = hl_liquidity._post(session, {"type": "spotMetaAndAssetCtxs"})
    mids = hl_liquidity._post(session, {"type": "allMids"})
    sz = {t["name"]: int(t["szDecimals"]) for t in meta["tokens"]}
    prices = {}
    for tok in UNIT.values():
        found = hl_liquidity.find_spot(meta, tok)
        if found and found[1] in mids:
            prices[tok] = float(mids[found[1]])
    perp = {c: float(mids[c]) for c in UNIT if c in mids}
    return prices, sz, perp


def fetch_account(session, address):
    """-> (usdc, holdings Token->Menge) aus spotClearinghouseState (oeffentlich, nur Lesen)."""
    st = hl_liquidity._post(session, {"type": "spotClearinghouseState", "user": address})
    bal = {b["coin"]: float(b["total"]) for b in st.get("balances", [])}
    return bal.get("USDC", 0.0), {k: v for k, v in bal.items() if k != "USDC"}


def fetch_perp_value(session, address):
    """Kontowert im Perp-Konto (clearinghouseState, marginSummary.accountValue). Hyperliquid fuehrt USDC getrennt fuer Spot und Perp:
    eine Einzahlung ueber Arbitrum landet je nach Kontomodus im Perp-Konto, der Bot liest aber nur das Spot-Konto."""
    st = hl_liquidity._post(session, {"type": "clearinghouseState", "user": address})
    return float(((st or {}).get("marginSummary") or {}).get("accountValue", 0.0))


def fetch_hl_closes(session, coins, date):
    out = {}
    start = data.ms(date)
    for c in coins:
        for t, o, h, l, cl, v in data.fetch_hl_candles(c, start, session):
            if data.day_str(t) == date:
                out[c] = float(cl)
    return out


def fetch_usdc_price(session):
    r = data._request(session, "GET", "https://api.coingecko.com/api/v3/simple/price", params={"ids": "usd-coin", "vs_currencies": "usd"})
    return float(r.json()["usd-coin"]["usd"])


def run(cfg, plan, session=None, now=None, log=print, address=None, sender=None):
    """Ein Planlauf. Gibt dict mit orders, skipped, violations, ks, equity zurueck.

    Ohne sender: Trockenlauf (Papierkonto, nichts wird gesendet). Mit sender (nur ueber hl_live.py, mehrfach gesperrt): echte Orders,
    echtes Konto (address Pflicht), eigener Kill-Switch-Zustand und eigenes Protokoll."""
    live = sender is not None
    mode = plan.get("mode", "dry-run")
    if live and mode != "live":
        raise SystemExit("Sender uebergeben, aber live_plan.yaml steht nicht auf mode: live.")
    if not live and mode != "dry-run":
        raise SystemExit("mode: live nur ueber hl_live.py. Dieser Lauf ist nur dry-run.")
    if live and not address:
        raise SystemExit("Live braucht HL_ACCOUNT_ADDRESS (echtes Konto).")
    s = session or requests.Session()
    now = now or dt.datetime.now(dt.timezone.utc)
    dates, ohlc, fund = data.load_all(cfg)
    res = pipeline.run(cfg, dates, ohlc, fund)
    sig = pipeline.signal(cfg, dates, ohlc, fund, res)
    ew = spill.effective_weights(cfg, dates, ohlc, fund, "spill", res=res)
    coins = cfg["coins"]
    exposures = {c: v["target_exposure"] for c, v in sig["trend"].items()}
    prices, sz, perp = fetch_market(s)
    paper_path = os.path.join(cfg["data_dir"], "paper_account_A.json")
    pst = None
    if address:
        usdc_free, holdings = fetch_account(s, address)
    else:
        pst = paper_load(paper_path, plan.get("dry_run", {}).get("paper_equity_usdc", 10000.0))
        usdc_free, holdings = pst["usdc"], pst["holdings"]
    equity = usdc_free + sum(q * prices.get(t, 0.0) for t, q in holdings.items())

    wid = "A"
    ks_path = os.path.join(cfg["data_dir"], f"killswitch_{wid}_{'live' if live else 'dryrun'}.json")
    state = killswitch.load(ks_path) or killswitch.new_state(equity)
    state, ks = killswitch.evaluate(state, equity, plan["kill_switch"])
    killswitch.save(ks_path, state)

    sf = plan["safety"]
    viol = []
    viol += safety.data_age(sig["as_of"], now, sf["max_data_age_hours"])
    try:
        viol += safety.source_divergence({c: ohlc[c][sig["as_of"]][3] for c in coins}, fetch_hl_closes(s, coins, sig["as_of"]), sf["max_source_divergence"])
    except Exception as e:
        viol.append(f"Zweite Datenquelle nicht lesbar ({type(e).__name__})")
    viol += safety.unit_deviation({UNIT[c]: prices.get(UNIT[c]) for c in coins if c in UNIT}, {UNIT[c]: perp.get(c) for c in coins if c in UNIT}, sf["unit_token_max_deviation"])
    try:
        viol += safety.usdc_peg(fetch_usdc_price(s), sf["usdc_depeg_floor"])
    except Exception as e:
        viol.append(f"USDC-Kurs nicht lesbar ({type(e).__name__})")

    tgt = targets_usd(ew, exposures, equity, ks["exposure_mult"], coins)
    orders, skipped = plan_orders(tgt, holdings, prices, sz, equity, wid, sig["as_of"], plan.get("dry_run", {}).get("min_order_usd", 10.0),
                                  plan.get("dry_run", {}).get("min_trade_frac", 0.02), sf["max_slippage_bps"], sf["max_order_frac"])
    viol += safety.orders([o["usd"] for o in orders], equity, 0.0, sf["max_order_frac"], sf["max_daily_turnover_frac"])
    # Stopp: Verkaeufe (Ziel 0) laufen trotz Sicherungs-Verstoessen, weil der Kontowert aus dem Konto kommt, nicht aus Marktdaten.
    blocked = bool(viol) and ks["level"] != "stop"
    notes = []
    if ew["carry_aktiv"]:
        notes.append(f"Carry aktiv fuer {', '.join(ew['carry_aktiv'])}, Ausfuehrung noch nicht gebaut: Anteil bleibt USDC im Plan")

    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [dict(o, ts=ts, date=sig["as_of"], wallet=wid, status="blocked" if blocked else "planned", reason="; ".join(viol)) for o in orders]
    rows += [{"ts": ts, "date": sig["as_of"], "wallet": wid, "asset": a, "side": "", "status": "skipped", "reason": r, "cloid": cloid(wid, sig["as_of"], a, "skip", r)} for a, r in skipped]
    if live:
        try:
            perp = fetch_perp_value(s, address)
            if perp > 5.0 and equity < 0.5 * perp:
                viol.append(f"{perp:,.2f} USD liegen im Perp-Konto, der Bot sieht im Spot-Konto nur {equity:,.2f} USD. Von Hand nach Spot umbuchen (Hyperliquid: Transfer Perps zu Spot).")
                blocked = blocked or ks["level"] != "stop"
        except Exception as e:
            viol.append(f"Perp-Konto nicht lesbar ({type(e).__name__})")
            blocked = blocked or ks["level"] != "stop"
        cap = plan.get("live", {}).get("max_equity_usdc")
        if cap is not None and equity > cap:
            viol.append(f"Kontowert {equity:,.0f} USD ueber Obergrenze {cap:,.0f} (nicht freigegebene Aufstockung?)")
            blocked = blocked or ks["level"] != "stop"
        for r in rows:
            if r["status"] == "planned" and blocked:
                r["status"] = "blocked"
    live_result = None
    if live:
        from . import hl_sender

        live_log = os.path.join(cfg["data_dir"], "orders_live.csv")
        plan_rows = [r for r in rows if r["status"] == "blocked" or r["status"] == "skipped"]
        log_orders(live_log, plan_rows, hl_sender.SEND_FIELDS)
        if not blocked and orders:
            post = lambda body: hl_liquidity._post(s, body)
            res, aborted = hl_sender.execute(
                [dict(o, ts=ts, date=sig["as_of"], wallet=wid) for o in orders], sender, post, address,
                lambda rr: log_orders(live_log, [dict(r, ts=ts, date=sig["as_of"], wallet=wid) for r in rr], hl_sender.SEND_FIELDS), log)
            usdc2, hold2 = fetch_account(s, address)
            equity2 = usdc2 + sum(q * prices.get(t, 0.0) for t, q in hold2.items())
            target_tok = {UNIT[c]: tgt[c] for c in coins if c in UNIT}
            actual_tok = {t: q * prices.get(t, 0.0) for t, q in hold2.items() if t in target_tok}
            mism = safety.position_mismatch(target_tok, actual_tok, equity2, sf["max_position_mismatch"])
            live_result = {"results": res, "aborted": aborted, "mismatch": mism, "equity_after": equity2}
            for m in mism:
                log(f"  ABGLEICH: {m}")
            if aborted:
                log("  ABBRUCH: Order fehlgeschlagen, restliche Orders nicht gesendet.")
    else:
        log_orders(os.path.join(cfg["data_dir"], "orders_dryrun.csv"), rows)
    if pst is not None and not blocked and orders:
        paper_save(paper_path, paper_fill(pst, orders, prices, plan.get("venue", {}).get("fees_bps", {}).get("spot_taker", 7.0)))

    log(f"Trockenlauf Wallet {wid}, Signal {sig['as_of']}, Kontowert {equity:,.2f} USD ({'Adresse' if address else 'Papier'})")
    log(f"Kill-Switch: {ks['level']} (Verlust ab Hoechststand {ks['dd']:.1%}, Exposure x{ks['exposure_mult']})")
    log(f"Gewichte mit Spill: Trend {ew['trend']:.0%}, Carry {ew['carry']:.0%}, Cash {ew['cash']:.0%}")
    for c in coins:
        log(f"  Ziel {c}: Exposure {exposures[c]:.2f} -> {tgt[c]:,.0f} USD {UNIT.get(c, '?')}")
    for o in orders:
        log(f"  {'BLOCKIERT ' if blocked else ''}Order {o['side']} {o['sz']} {o['asset']} limit {o['limit_px']} (~{o['usd']:,.0f} USD) {o['cloid'][:10]}")
    for a, r in skipped:
        log(f"  uebersprungen {a}: {r}")
    for n in notes:
        log(f"  Hinweis: {n}")
    for v in viol:
        log(f"  SICHERUNG: {v}")
    return {"orders": orders, "skipped": skipped, "violations": viol, "blocked": blocked, "ks": ks, "equity": equity, "targets": tgt, "notes": notes, "live": live_result}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hl_exec")
    ap.add_argument("--config", default="quant_40.yaml")
    ap.add_argument("--plan", default="live_plan.yaml")
    a = ap.parse_args(argv)
    with open(a.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["data_dir"] = os.path.join(os.path.dirname(os.path.abspath(a.config)), cfg["data_dir"])
    with open(a.plan, encoding="utf-8") as f:
        plan = yaml.safe_load(f)
    run(cfg, plan, address=os.environ.get("HL_ACCOUNT_ADDRESS"))


if __name__ == "__main__":
    main()
