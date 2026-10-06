import argparse
import os
import sys
import time
from datetime import datetime

import yaml

from . import adapt
from .agent import Agent
from .db import Ledger
from .executor import LiveExecutor, PaperExecutor
from .market import GeckoTerminalProvider
from .research import ClaudeResearcher, RuleResearcher
from .risk import RiskEngine
from .security import GoPlusChecker


def load_cfg(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build(cfg, base_dir):
    db_path = os.path.join(base_dir, cfg.get("db_path", "data/autotrader.db"))
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    ledger = Ledger(db_path)
    if cfg["mode"] == "live":
        LiveExecutor()  # wirft NotImplementedError, absichtlich
    executor = PaperExecutor(ledger, cfg["paper"]["fee_pct"], cfg["paper"]["slippage_pct"])
    market = GeckoTerminalProvider(cfg["network"])
    rcfg = cfg["research"]
    params_fn = lambda strategy: adapt.get_params(cfg, ledger, strategy)
    reviewer = None
    if rcfg["provider"] == "claude":
        researcher = ClaudeResearcher(rcfg["model"], rcfg.get("web_search", True))
        reviewer = adapt.ClaudeReviewer(rcfg["model"])
    else:
        researcher = RuleResearcher(params_fn)
    risk = RiskEngine(cfg["limits"], ledger)
    scfg = cfg.get("security", {})
    security = GoPlusChecker(cfg["network"], scfg.get("max_tax", 0.05), scfg.get("min_holders", 100)) if scfg.get("enabled", True) else None
    agent = Agent(cfg, ledger, market, researcher, executor, risk, security=security, reviewer=reviewer)
    return ledger, agent


def cmd_report(ledger, cfg):
    stats = adapt.strategy_stats(ledger)
    print(f"{'Strategie':<14}{'Slots':>6}{'Equity':>10}{'Trades':>8}{'Netto':>10}{'Gebuehren':>11}{'Trefferq.':>10}  Status")
    for name, st in stats.items():
        wr = f"{st['win_rate']:.0%}" if st["win_rate"] is not None else "-"
        status = "PAUSIERT" if st["paused"] else "aktiv"
        print(f"{name:<14}{st['slots']:>6}{st['equity']:>10.2f}{st['closed']:>8}{st['net']:>+10.2f}{st['fees']:>11.2f}{wr:>10}  {status}")
    a = cfg["adapt"]
    print(f"\nAussagekraft: Pause ab {a['min_closed_trades_for_pause']} Trades, Parameter-Tuning ab {a['min_closed_trades_for_tuning']} Trades pro Strategie.")
    print("Darunter sind die Zahlen Rauschen, keine Evidenz.")
    ov = ledger.kv_get(adapt.PARAM_KEY, "{}")
    print(f"Parameter-Overrides: {ov}")


def fmt_ts(ts):
    return datetime.fromtimestamp(ts).strftime("%d.%m. %H:%M")


def cmd_status(ledger, cfg):
    print(f"Kill-Switch: {'AKTIV' if ledger.kv_get('killed', '0') == '1' else 'aus'} | Gesamt-Equity: {ledger.total_equity():.2f} USD")
    for s in ledger.slots():
        eq = ledger.equity(s["id"])
        print(f"\nSlot {s['id']} {s['name']} [{s['strategy']}] {s['address']}")
        print(f"  Equity {eq:.2f} | Cash {s['cash']:.2f} | Start {s['start_value']:.2f}")
        for p in ledger.positions(s["id"]):
            pnl = (p["last_price"] / p["entry_price"] - 1) * 100
            print(f"  - {p['symbol']:<10} {p['qty'] * p['last_price']:>9.2f} USD  {pnl:+6.1f}%")
    pend = ledger.pending_approvals()
    if pend:
        print("\nOffene Freigaben:")
        for a in pend:
            print(f"  #{a['id']} {fmt_ts(a['ts'])} {a['payload'][:140]}")
    print("\nLetzte Trades:")
    for t in ledger.recent_trades(8):
        pnl = f" pnl {t['pnl']:+.2f}" if t["pnl"] is not None else ""
        print(f"  {fmt_ts(t['ts'])} slot {t['slot_id']} {t['side']:<4} {t['symbol']:<10} {t['usd']:.2f} USD{pnl}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="autotrader")
    ap.add_argument("--config", default="config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    r = sub.add_parser("run")
    r.add_argument("--once", action="store_true")
    sub.add_parser("status")
    sub.add_parser("approvals")
    a = sub.add_parser("approve")
    a.add_argument("id", type=int)
    j = sub.add_parser("reject")
    j.add_argument("id", type=int)
    sub.add_parser("kill")
    sub.add_parser("resume")
    sub.add_parser("report")
    u = sub.add_parser("unpause")
    u.add_argument("strategy")
    args = ap.parse_args(argv)

    cfg = load_cfg(args.config)
    base_dir = os.path.dirname(os.path.abspath(args.config))
    try:
        ledger, agent = build(cfg, base_dir)
    except NotImplementedError as e:
        sys.exit(str(e))

    if args.cmd == "init":
        agent.init_first_slot()
    elif args.cmd == "run":
        agent.init_first_slot()
        while True:
            agent.tick()
            if args.once:
                break
            try:
                time.sleep(cfg["tick_seconds"])
            except KeyboardInterrupt:
                print("Beendet.")
                break
    elif args.cmd == "status":
        cmd_status(ledger, cfg)
    elif args.cmd == "approvals":
        for p in ledger.pending_approvals():
            print(f"#{p['id']} {fmt_ts(p['ts'])} slot {p['slot_id']} {p['payload']}")
    elif args.cmd == "approve":
        print(agent.resolve_approval(args.id, True))
    elif args.cmd == "reject":
        print(agent.resolve_approval(args.id, False))
    elif args.cmd == "report":
        cmd_report(ledger, cfg)
    elif args.cmd == "unpause":
        ledger.kv_set(f"paused:{args.strategy}", "0")
        print(f"Strategie {args.strategy} wieder aktiv.")
    elif args.cmd == "kill":
        ledger.kv_set("killed", "1")
        print("Kill-Switch gesetzt.")
    elif args.cmd == "resume":
        ledger.kv_set("killed", "0")
        ledger.kv_set("hwm", ledger.total_equity())
        print("Kill-Switch aus, Hoechstmarke zurueckgesetzt.")


if __name__ == "__main__":
    main()
