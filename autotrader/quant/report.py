"""Taegliche Zusammenfassung: Signale beider Profile, Aenderungen seit gestern, Papier-Ergebnis, Gesundheitschecks.

python -m autotrader.quant.report --main quant_40.yaml --core quant.yaml --paper-start 2026-10-06
Schreibt data/quant/latest_report.txt und data/quant/state.json. Optional Push per ntfy (NTFY_TOPIC; NTFY_DETAIL=short sendet nur Status ohne Positionen).
"""
import argparse
import datetime as dt
import json
import os

import yaml

from . import data, pipeline
from .metrics import stats

EXPOSURE_JUMP = 0.20  # Aenderung der Ziel-Exposure, ab der ein Hinweis erscheint


def pct(x):
    return f"{x * 100:+.1f}%"


def _compound(rets):
    eq = 1.0
    for r in rets:
        eq *= 1 + r
    return eq - 1


def snapshot(cfg, dates, ohlc, fund):
    res = pipeline.run(cfg, dates, ohlc, fund)
    sig = pipeline.signal(cfg, dates, ohlc, fund, res)
    return res, sig


def build_report(main, core, paper_start, prev_state, today=None, ledger_path=None):
    """main/core: dict mit cfg, dates, ohlc, fund. Gibt (text, neuer_state, warnungen) zurueck."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    out, warns, infos = [], [], []
    state = {}
    for key, name, p in (("main", "Hauptprofil 40", main), ("core", "Kernprofil (Vergleich)", core)):
        res, sig = snapshot(p["cfg"], p["dates"], p["ohlc"], p["fund"])
        p["res"] = res
        exp = {c: round(v["target_exposure"], 2) for c, v in sig["trend"].items()}
        car = {c: bool(v["in_position"]) for c, v in sig["carry"].items()}
        apr = {c: v["trailing_apr"] for c, v in sig["carry"].items()}
        state[key] = {"as_of": sig["as_of"], "trend": exp, "carry": car}
        if ledger_path and key == "main":
            try:
                from . import ledger

                ledger.update(ledger_path, "quant_40", sig, p["dates"], p["ohlc"])
            except Exception as e:
                warns.append(f"LEDGER nicht geschrieben ({type(e).__name__}: {e})")
        out.append(f"{name} (Stand {sig['as_of']}), Gewichte {sig['weights']}")
        out.append("  Trend: " + ", ".join(f"{c} {e:.2f}" for c, e in exp.items()))
        out.append("  Carry: " + ", ".join(f"{c} {'IN' if car[c] else 'flat'} (Funding {apr[c] * 100:.1f}% p.a.)" if apr[c] is not None else f"{c} {'IN' if car[c] else 'flat'}" for c in car))
        if key == "main":
            try:
                from . import spill

                ew = spill.effective_weights(p["cfg"], p["dates"], p["ohlc"], p["fund"], "spill", res=res)
                p["spill_w"] = ew
                out.append(f"  Effektiv mit Spill: Trend {ew['trend'] * 100:.0f}%, Carry {ew['carry'] * 100:.0f}% (aktiv: {', '.join(ew['carry_aktiv']) or '-'}; flat: {', '.join(ew['carry_flat']) or '-'}), Cash {ew['cash'] * 100:.0f}%")
            except Exception as e:
                warns.append(f"Spill-Gewichte nicht berechenbar ({type(e).__name__})")
        old = (prev_state or {}).get(key)
        if old:
            # Signalwechsel im Hauptprofil sind Warnungen (dort wird gehandelt). Das Kernprofil laeuft nur zum Vergleich mit:
            # seine Wechsel stehen als Hinweis im Bericht und loesen keine Warnung aus.
            sink = warns if key == "main" else infos
            for c, e in exp.items():
                d = e - old["trend"].get(c, e)
                if abs(d) >= EXPOSURE_JUMP:
                    sink.append(f"{name}: Trend {c} Exposure {old['trend'].get(c):.2f} -> {e:.2f}")
            for c, v in car.items():
                if v != old["carry"].get(c, v):
                    sink.append(f"{name}: Carry {c} {'Einstieg' if v else 'Ausstieg'}")
    last = main["dates"][-1]
    age = (today - dt.date.fromisoformat(last)).days
    if age > 1:
        warns.insert(0, f"DATEN VERALTET: letzter Tag {last}, heute {today} (Alter {age} Tage)")
    r = main["res"]
    idx = [i for i, d in enumerate(r["dates"]) if d >= paper_start]
    out.append("")
    if idx:
        i0 = idx[0]
        n = len(idx)
        spill_rets = None
        try:
            from . import spill

            spill_rets = spill.spill_series(main["cfg"], main["dates"], main["ohlc"], main["fund"], r, "spill")
        except Exception as e:
            warns.append(f"Spill-Ergebnis nicht berechenbar ({type(e).__name__})")
        rows = [
            ("Hauptprofil", r["combined"]),
            ("Haupt+Spill", spill_rets or []),
            ("Trend allein", r["trend"]),
            ("Buy-and-Hold", r["buyhold"]),
            ("Kernprofil", core["res"]["combined"][-n:] if len(core["res"]["combined"]) >= n else []),
        ]
        out.append(f"Papier-Ergebnis seit {paper_start} ({n} Tage):")
        for label, series in rows:
            if series:
                s7 = _compound(series[-7:])
                out.append(f"  {label:<14} seit Start {pct(_compound(series[i0:] if label not in ('Kernprofil',) else series))}, letzte 7 Tage {pct(s7)}")
        dd = stats(r["combined"][i0:])["max_dd"]
        out.append(f"  Max. Verlust Hauptprofil seit Start: {pct(dd)}")
        if dd < -0.30:
            warns.append(f"Verlust Hauptprofil {pct(dd)} seit Papierstart (Toleranz 40%)")
    else:
        out.append(f"Papier-Ergebnis: noch keine Tage seit {paper_start}.")
    try:
        from . import macro

        line = macro.latest_line(main["cfg"])
        if line:
            out.append("")
            out.append(line)
    except Exception:  # Makro ist optional und darf den Bericht nie verhindern
        pass
    text = (f"Autotrader Tagesbericht {today}\n" + ("WARNUNGEN:\n  - " + "\n  - ".join(warns) + "\n" if warns else "Keine Warnungen.\n")
            + ("Hinweise (keine Warnung):\n  - " + "\n  - ".join(infos) + "\n" if infos else "") + "\n" + "\n".join(out) + "\n")
    return text, state, warns


def _load(path):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["data_dir"] = os.path.join(os.path.dirname(os.path.abspath(path)), cfg["data_dir"])
    dates, ohlc, fund = data.load_all(cfg)
    return {"cfg": cfg, "dates": dates, "ohlc": ohlc, "fund": fund}


def notify_body(text, warns, detail, status=None):
    """detail 'full': ganzer Bericht (Papierphase). 'short': keine Positionen oder Betraege im Push, nur Status (ntfy.sh ist oeffentlich).
    status: optionale Zeile zu Kriterium A (ohne Betraege), wird bei 'short' angehaengt; bei 'full' steht sie schon im Bericht."""
    if detail == "short":
        first = text.splitlines()[0] if text else "Autotrader"
        body = f"{first}\n{len(warns)} Warnung(en). Details auf dem Server: latest_report.txt" if warns else f"{first}\nKeine Warnungen."
        return body + (f"\n{status}" if status else "")
    return text


def add_status(text, warns, status, violated):
    """Haengt die Statuszeile an den Bericht. Ist Kriterium A verletzt, wird das zusaetzlich eine Warnung (Liste und Text)."""
    if violated:
        msg = "Kriterium A verletzt, Details: paper_status"
        warns.append(msg)
        if "WARNUNGEN:\n" in text:
            text = text.replace("WARNUNGEN:\n", f"WARNUNGEN:\n  - {msg}\n", 1)
        else:
            text = text.replace("Keine Warnungen.\n", f"WARNUNGEN:\n  - {msg}\n", 1)
    return text.rstrip("\n") + f"\n\n{status}\n"


def notify(text, warns, status=None):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return
    import requests

    title = "Autotrader: " + ("WARNUNG" if warns else "OK")
    body = notify_body(text, warns, os.environ.get("NTFY_DETAIL", "full"), status)
    try:
        requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), headers={"Title": title, "Priority": "high" if warns else "default"}, timeout=15)
    except requests.RequestException:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", default="quant_40.yaml")
    ap.add_argument("--core", default="quant.yaml")
    ap.add_argument("--paper-start", default="2026-10-06")
    a = ap.parse_args(argv)
    m, c = _load(a.main), _load(a.core)
    d = m["cfg"]["data_dir"]
    sp = os.path.join(d, "state.json")
    prev = None
    if os.path.exists(sp):
        with open(sp, encoding="utf-8") as f:
            prev = json.load(f)
    text, state, warns = build_report(m, c, a.paper_start, prev, ledger_path=os.path.join(d, "ledger.csv"))
    status = None
    try:  # Statuszeile darf den Bericht nie verhindern
        from . import paper_status

        status, violated = paper_status.status_line(d, a.paper_start)
        text = add_status(text, warns, status, violated)
    except Exception as e:
        status = f"Kriterium A: nicht auswertbar ({type(e).__name__})"
    with open(os.path.join(d, "latest_report.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    print(text)
    notify(text, warns, status)


if __name__ == "__main__":
    main()
