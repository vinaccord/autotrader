"""P1 12: Funding Binance (Backtest-Quelle) gegen Hyperliquid (Ausfuehrungsort) und Einstiegs-Timing.

python -m autotrader.quant.fundcmp --config quant_40.yaml [--no-fetch]

Holt die stuendliche Hyperliquid-Funding-Historie (Cache data/quant/hyperliquid_funding_<COIN>.csv) und vergleicht sie
auf Tagesbasis mit dem Binance-Funding im Cache. Nur volle Tage (24 stuendliche Eintraege). Fragen, die das beantwortet:
1. Wie gross ist das Funding auf Hyperliquid im Vergleich zu Binance (Mittelwert, Korrelation, Vorzeichen)?
2. Wuerden die Carry-Signale (Einstieg/Ausstieg mit den Standardparametern) auf Hyperliquid-Funding gleich ausfallen?
3. Wie veraendert sich das Carry-Ergebnis mit HL-Funding und dem verpassten Teil des Einstiegstags?
Nichts davon aendert die Strategie. Ergebnis ist eine Entscheidungsgrundlage, ob Binance-Funding als Stellvertreter taugt.
Netzwerk nur auf dem Server testbar.
"""
import argparse
import datetime as dt
import os

import yaml

from . import data
from .metrics import mean, stats
from .strategies import carry_returns

HL_FULL_DAY = 24


def hl_path(cfg, coin):
    return os.path.join(cfg["data_dir"], f"hyperliquid_funding_{coin}.csv")


def fetch(cfg, log=print, session=None):
    start = data.ms(cfg["start"])
    for coin in cfg["coins"]:
        rows = data.fetch_hl_funding(coin, start, session)
        if not rows:
            log(f"{coin}: keine Hyperliquid-Funding-Daten erhalten, Cache bleibt")
            continue
        data.save_if_not_shrunk(hl_path(cfg, coin), ["ts", "rate"], rows, log, f"{coin} HL-Funding")
        log(f"{coin}: {len(rows)} stuendliche Eintraege ab {data.day_str(min(t for t, _ in rows))}")


def hl_full_days(rows, today=None):
    """[(ts_ms, rate)] -> {datum: Tagessumme} nur fuer vollstaendige, abgeschlossene Tage mit genau 24 Eintraegen."""
    today = today or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    cnt, tot = {}, {}
    for ts, r in rows:
        d = data.day_str(ts)
        cnt[d] = cnt.get(d, 0) + 1
        tot[d] = tot.get(d, 0.0) + r
    return {d: tot[d] for d in tot if cnt[d] == HL_FULL_DAY and d < today}, {d: c for d, c in cnt.items() if d < today and c != HL_FULL_DAY}


def corr(a, b):
    ma, mb = mean(a), mean(b)
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb) ** 0.5


def rolling_apr(vals, n):
    out = []
    for i in range(len(vals)):
        out.append(mean(vals[i + 1 - n : i + 1]) * 365 if i + 1 >= n else None)
    return out


def compare(days, bn, hl, ohlc, carry_cfg, costs, hl_frac=23 / 24, bn_frac=2 / 3):
    """days: gemeinsame Tage (sortiert); bn/hl: {datum: Tagesfunding}; ohlc: {datum: (o,h,l,c)}. -> dict mit Kennzahlen."""
    b = [bn[d] for d in days]
    h = [hl[d] for d in days]
    lb, ent, ex, lev = carry_cfg["lookback"], carry_cfg["entry_apr"], carry_cfg["exit_apr"], carry_cfg.get("lev", 2)
    n = len(days)
    out = {
        "days": n,
        "first": days[0],
        "last": days[-1],
        "apr_bn": mean(b) * 365,
        "apr_hl": mean(h) * 365,
        "corr_daily": corr(b, h),
        "corr_14d": corr([x for x in rolling_apr(b, 14) if x is not None], [x for x in rolling_apr(h, 14) if x is not None]) if n > 14 else 0.0,
        "sign_diff_days": sum(1 for x, y in zip(b, h) if (x > 0) != (y > 0)),
        "recent": {k: (mean(b[-k:]) * 365, mean(h[-k:]) * 365) for k in (14, 30) if n >= k},
    }
    fb, fh = dict(zip(days, b)), dict(zip(days, h))
    oh = {d: ohlc[d] for d in days}
    runs = {
        "bn": carry_returns(days, fb, oh, lb, ent, ex, lev, costs),
        "bn_frac": carry_returns(days, fb, oh, lb, ent, ex, lev, costs, entry_day_frac=bn_frac),
        "hl": carry_returns(days, fh, oh, lb, ent, ex, lev, costs),
        "hl_frac": carry_returns(days, fh, oh, lb, ent, ex, lev, costs, entry_day_frac=hl_frac),
    }
    for k, (r, info) in runs.items():
        st = stats(r)
        out[k] = {"total": st["total"], "cagr": st["cagr"], "max_dd": st["max_dd"], "days_in": info["days_in"], "entries": info["entries"]}
    fl_b, fl_h = runs["bn"][1]["flags"], runs["hl"][1]["flags"]
    out["signal_agree"] = sum(1 for x, y in zip(fl_b, fl_h) if x == y) / n
    return out


def report(res, coin, log=print):
    log(f"\n{coin}: {res['days']} gemeinsame volle Tage, {res['first']} bis {res['last']}")
    log(f"  Funding p.a. im Mittel: Binance {res['apr_bn'] * 100:+.1f}%, Hyperliquid {res['apr_hl'] * 100:+.1f}%")
    log(f"  Korrelation Tagesfunding {res['corr_daily']:.2f}, 14-Tage-Mittel {res['corr_14d']:.2f}; Tage mit anderem Vorzeichen: {res['sign_diff_days']}")
    for k, (xb, xh) in sorted(res["recent"].items()):
        log(f"  Letzte {k} Tage p.a.: Binance {xb * 100:+.1f}%, Hyperliquid {xh * 100:+.1f}% (Einstiegsschwelle 12%, Ausstieg 4%)")
    log(f"  Carry-Signal (Standardparameter) gleich an {res['signal_agree'] * 100:.0f}% der Tage")
    log(f"  {'Carry-Lauf':<36}{'Total':>8}{'CAGR':>8}{'MaxDD':>8}{'Tage in':>9}{'Einstiege':>10}")
    labels = {"bn": "Binance-Funding", "bn_frac": "Binance, Einstiegstag 2/3", "hl": "Hyperliquid-Funding", "hl_frac": "Hyperliquid, Einstiegstag 23/24"}
    for k, lab in labels.items():
        r = res[k]
        log(f"  {lab:<36}{r['total'] * 100:>+7.1f}%{r['cagr'] * 100:>+7.1f}%{r['max_dd'] * 100:>+7.1f}%{r['days_in']:>9}{r['entries']:>10}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fundcmp")
    ap.add_argument("--config", default="quant_40.yaml")
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args(argv)
    with open(a.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["data_dir"] = os.path.join(os.path.dirname(os.path.abspath(a.config)), cfg["data_dir"])
    if not a.no_fetch:
        fetch(cfg)
    carry = dict(cfg["carry"]["default"], lev=cfg["carry"]["lev"])
    for coin in cfg["coins"]:
        hl_rows = [(int(t), float(r)) for t, r in data.load_rows(hl_path(cfg, coin))]
        hl, partial = hl_full_days(hl_rows)
        bn = dict(data.load_funding(data.cache_path(cfg, "funding", coin)))
        ohlc = data.load_ohlc(data.cache_path(cfg, "prices", coin))
        days = sorted(d for d in hl if d in bn and d in ohlc)
        if len(days) < 60:
            print(f"{coin}: nur {len(days)} gemeinsame Tage, Vergleich uebersprungen")
            continue
        if partial:
            print(f"{coin}: {len(partial)} HL-Tage ohne 24 Eintraege ausgelassen (z.B. {sorted(partial)[0]})")
        report(compare(days, bn, hl, ohlc, carry, cfg["costs"]), coin)
    print("\nHinweise: Vergleich nur ueber den Zeitraum, in dem Hyperliquid-Funding vorliegt (ab 2023). Standardparameter, kein Walk-Forward. Einstiegstag-Anteile sind Annahmen (Job laeuft ca. 65 Minuten nach 00:00 UTC).")


if __name__ == "__main__":
    main()
