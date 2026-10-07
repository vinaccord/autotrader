"""Einziger Einstieg fuer echte Orders. NICHT im Tages-Timer, NICHT freigegeben. Nur nach Patricks ausdruecklicher Freigabe im Chat.

python -m autotrader.quant.hl_live --config quant_40.yaml --plan live_plan.yaml --confirm-real-money

Alle Sperren muessen gleichzeitig offen sein, sonst Abbruch ohne Order:
1. live_plan.yaml: mode: live
2. live_plan.yaml: live.armed_until >= heutiges UTC-Datum (Patrick setzt das kurz im Voraus, z.B. auf den Testtag)
3. Umgebung: HL_AGENT_KEY (Agent-Key, kann nicht abheben) und HL_ACCOUNT_ADDRESS (Hauptadresse), nie im Chat oder Repo
4. Kommandozeile: --confirm-real-money
5. SDK in genau der festgenagelten Version installiert (deploy/requirements-live.txt)
Dazu die Sicherungen aus hl_exec.run (Kill-Switch, Datenalter, Abweichungen, Einzelorder-Grenze, Kontowert-Obergrenze live.max_equity_usdc).
Ausfuehrung: Trend ueber Spot (UBTC/UETH). Carry wird nicht ausgefuehrt.
"""
import argparse
import datetime as dt
import os

import requests
import yaml

from . import hl_exec, hl_liquidity


def check_gates(plan, args_confirm, env, today=None):
    """-> Liste der offenen Hindernisse (leer = alles frei). Reine Funktion, damit testbar."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    out = []
    if plan.get("mode") != "live":
        out.append("live_plan.yaml: mode ist nicht 'live'")
    armed = (plan.get("live") or {}).get("armed_until")
    try:
        armed_date = dt.date.fromisoformat(str(armed))
        if armed_date < today:
            out.append(f"live.armed_until {armed} ist abgelaufen")
    except ValueError:
        out.append("live.armed_until fehlt oder ist kein Datum (JJJJ-MM-TT)")
    if not env.get("HL_AGENT_KEY"):
        out.append("HL_AGENT_KEY fehlt in der Umgebung")
    if not env.get("HL_ACCOUNT_ADDRESS"):
        out.append("HL_ACCOUNT_ADDRESS fehlt in der Umgebung")
    if not args_confirm:
        out.append("--confirm-real-money fehlt")
    return out


def main(argv=None, env=None):
    ap = argparse.ArgumentParser(prog="hl_live")
    ap.add_argument("--config", default="quant_40.yaml")
    ap.add_argument("--plan", default="live_plan.yaml")
    ap.add_argument("--confirm-real-money", action="store_true")
    a = ap.parse_args(argv)
    env = os.environ if env is None else env
    with open(a.plan, encoding="utf-8") as f:
        plan = yaml.safe_load(f)
    block = check_gates(plan, a.confirm_real_money, env)
    if block:
        raise SystemExit("Keine Orders. Gesperrt durch:\n  - " + "\n  - ".join(block))
    with open(a.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["data_dir"] = os.path.join(os.path.dirname(os.path.abspath(a.config)), cfg["data_dir"])
    from . import hl_sender

    s = requests.Session()
    meta, _ = hl_liquidity._post(s, {"type": "spotMetaAndAssetCtxs"})
    pairs = {}
    for tok in hl_exec.UNIT.values():
        found = hl_liquidity.find_spot(meta, tok)
        if found:
            pairs[tok] = found[1]
    sender = hl_sender.SdkSender(pairs)
    res = hl_exec.run(cfg, plan, session=s, address=env["HL_ACCOUNT_ADDRESS"], sender=sender)
    live = res.get("live") or {}
    if live.get("aborted") or live.get("mismatch") or (res["blocked"] and res["orders"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
