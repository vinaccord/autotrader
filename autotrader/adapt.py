"""Strategie-Turnier: Kennzahlen pro Strategie, Auto-Pause, begrenzte Parameter-Anpassung.

Grundsatz: Parameter werden nur geaendert, wenn genug abgeschlossene Trades vorliegen, nur innerhalb
fester Grenzen und nur in kleinen Schritten. Sonst passt man Parameter an Zufall an (Overfitting).
"""
import json
import os
import re
import time

import requests

PARAM_KEY = "param_overrides"
LAST_REVIEW_KEY = "last_review_ts"

SELLS_SQL = """
SELECT s.strategy AS strategy, COUNT(*) AS n, COALESCE(SUM(t.pnl),0) AS pnl,
       COALESCE(SUM(CASE WHEN t.pnl>0 THEN 1 ELSE 0 END),0) AS wins
FROM trades t JOIN slots s ON s.id=t.slot_id WHERE t.side='sell' GROUP BY s.strategy
"""
FEES_SQL = """
SELECT s.strategy AS strategy, COALESCE(SUM(t.fee),0) AS fees, COUNT(*) AS trades
FROM trades t JOIN slots s ON s.id=t.slot_id GROUP BY s.strategy
"""


def get_params(cfg, ledger, strategy):
    params = dict(cfg["strategy_params"][strategy])
    try:
        overrides = json.loads(ledger.kv_get(PARAM_KEY, "{}")).get(strategy, {})
    except json.JSONDecodeError:
        overrides = {}
    params.update(overrides)
    return params


def is_paused(ledger, strategy):
    return ledger.kv_get(f"paused:{strategy}", "0") == "1"


def strategy_stats(ledger):
    stats = {}
    for s in ledger.slots():
        st = stats.setdefault(
            s["strategy"],
            {"slots": 0, "equity": 0.0, "closed": 0, "realized": 0.0, "wins": 0, "fees": 0.0, "trades": 0, "unrealized": 0.0},
        )
        st["slots"] += 1
        st["equity"] += ledger.equity(s["id"])
        for p in ledger.positions(s["id"]):
            st["unrealized"] += p["qty"] * p["last_price"] - p["cost_usd"]
    for r in ledger.con.execute(SELLS_SQL):
        if r["strategy"] in stats:
            stats[r["strategy"]].update(closed=r["n"], realized=r["pnl"], wins=r["wins"])
    for r in ledger.con.execute(FEES_SQL):
        if r["strategy"] in stats:
            stats[r["strategy"]].update(fees=r["fees"], trades=r["trades"])
    for name, st in stats.items():
        st["net"] = st["realized"] + st["unrealized"]
        st["win_rate"] = st["wins"] / st["closed"] if st["closed"] else None
        st["paused"] = is_paused(ledger, name)
    return stats


def apply_pause_rules(ledger, cfg):
    """Pausiert Strategien mit genug Trades und negativem Netto-Ergebnis. Gibt neu pausierte Namen zurueck."""
    a = cfg["adapt"]
    newly = []
    for name, st in strategy_stats(ledger).items():
        if st["paused"]:
            continue
        if st["closed"] >= a["min_closed_trades_for_pause"] and st["net"] < 0:
            ledger.kv_set(f"paused:{name}", "1")
            ledger.log("WARN", f"Strategie {name} pausiert: {st['closed']} Trades, Netto {st['net']:+.2f} USD")
            newly.append(name)
    return newly


def sanitize_changes(cfg, ledger, proposal):
    """Begrenzt Aenderungsvorschlaege auf erlaubte Parameter, Grenzen und Schrittweite."""
    a = cfg["adapt"]
    stats = strategy_stats(ledger)
    applied = {}
    if not isinstance(proposal, dict):
        return applied
    for strat, changes in proposal.items():
        if strat not in cfg["strategy_params"] or not isinstance(changes, dict):
            continue
        if stats.get(strat, {}).get("closed", 0) < a["min_closed_trades_for_tuning"]:
            continue
        cur = get_params(cfg, ledger, strat)
        for key, val in changes.items():
            bounds = a["bounds"].get(strat, {}).get(key)
            if key not in cur or bounds is None:
                continue
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue
            lo, hi = bounds
            c = float(cur[key])
            step = abs(c) * a["max_rel_change"] if c != 0 else (hi - lo) * a["max_rel_change"]
            val = min(max(val, c - step), c + step)
            val = min(max(val, lo), hi)
            if abs(val - c) > 1e-9:
                applied.setdefault(strat, {})[key] = round(val, 4)
    return applied


def commit_changes(ledger, applied):
    if not applied:
        return
    try:
        cur = json.loads(ledger.kv_get(PARAM_KEY, "{}"))
    except json.JSONDecodeError:
        cur = {}
    for strat, ch in applied.items():
        cur.setdefault(strat, {}).update(ch)
    ledger.kv_set(PARAM_KEY, json.dumps(cur))
    ledger.log("INFO", f"Parameter angepasst: {json.dumps(applied)}")


def review_due(ledger, cfg, now):
    last = float(ledger.kv_get(LAST_REVIEW_KEY, 0))
    return now - last >= cfg["adapt"]["review_interval_hours"] * 3600


SYSTEM_PROMPT = """Du pruefst die Ergebnisse eines Paper-Trading-Systems (Krypto-Kleinwerte, DEX).
Du bekommst Kennzahlen pro Strategie nach Kosten, aktuelle Parameter, erlaubte Grenzen und das Marktregime.
Aufgabe: hoechstens kleine Parameteraenderungen vorschlagen, wenn die Daten sie stuetzen. Bei wenigen Trades
oder gemischten Ergebnissen: keine Aenderung. Aenderungen ausserhalb der Grenzen werden verworfen.
Antworte ausschliesslich mit JSON:
{"changes":{"<strategie>":{"<parameter>":zahl}},"rationale":"max 300 Zeichen"}"""


class ClaudeReviewer:
    def __init__(self, model, api_key=None, max_tokens=1000):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.max_tokens = max_tokens

    def review(self, stats, params, bounds, regime):
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY fehlt")
        user = json.dumps(
            {"kennzahlen": stats, "parameter": params, "grenzen": bounds, "regime": regime}, ensure_ascii=False, default=str
        )
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": self.model, "max_tokens": self.max_tokens, "system": SYSTEM_PROMPT,
                  "messages": [{"role": "user", "content": user}]},
            timeout=120,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return {}, ""
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}, ""
        return data.get("changes", {}), str(data.get("rationale", ""))[:300]


def run_review(cfg, ledger, regime, reviewer, now=None):
    """Auto-Pause immer, Parameter-Review nur wenn faellig und ein Reviewer vorhanden ist."""
    now = now or time.time()
    paused = apply_pause_rules(ledger, cfg)
    applied = {}
    if reviewer is not None and review_due(ledger, cfg, now):
        stats = strategy_stats(ledger)
        params = {s: get_params(cfg, ledger, s) for s in cfg["strategy_params"]}
        try:
            proposal, why = reviewer.review(stats, params, cfg["adapt"]["bounds"], regime)
            applied = sanitize_changes(cfg, ledger, proposal)
            commit_changes(ledger, applied)
            ledger.log("INFO", f"Review abgeschlossen. Begruendung: {why or '-'}", ts=now)
        except Exception as e:
            ledger.log("WARN", f"Review fehlgeschlagen: {e}", ts=now)
        ledger.kv_set(LAST_REVIEW_KEY, now)
    return paused, applied
