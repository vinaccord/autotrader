# Briefing für die nächste Session (Stand 7. Oktober 2026)

Dieses Dokument ist die Übergabe an das Modell, das die Arbeit fortsetzt. Erst Abschnitt 0, dann den Rest ganz lesen, dann `docs/STRATEGIE.md`, dann den Code.

---

## 0. Einstieg (Stand 7.10.2026, 13:30, Commit nach 25ba9f3)

**Kurzstand**
- Phase 0 erledigt, Phase 1 bis auf Live-Teile erledigt (Details am Ende von Abschnitt 8), Phase 2 erledigt (negativ). 153 Tests (5 davon nur mit ssh-keygen).
- Auf dem Server laeuft taeglich 01:05 UTC: Daten, Backtest, Signale, Ledger (`ledger.csv`), Trockenlauf-Ausfuehrung mit Papierkonto (`paper_account_A.json`, `orders_dryrun.csv`, `killswitch_A_dryrun.json`), Fear & Greed, Tagesbericht per ntfy, Healthchecks-Ping.
- Patrick hat am 7.10. ausgefuehrt: Update, `harden.sh` (Ausgabe nicht gesehen, er meldet "alles erledigt"), Healthchecks-URL in `.env`, Ledger und Dry-Run-Testdateien geloescht fuer sauberen Start.
- Aktuelle Backtest-Zahlen: Abschnitt 4, Zeile "Nach P1-Korrekturen".

**Stand Phase 2 (7.10., abgeschlossen, Ergebnis negativ)**
- Data Vision enthaelt ausgelistete Coins (Probe: 705 USDT-Paare, 205 nicht mehr gehandelt). `universe_data.py` hat 692 Symbole, 29'596 Dateien, 0 Fehler nach `data/quant_universe/` geladen (Server, Pruefsummen geprueft). Aktualisieren: Lauf wiederholen, laedt nur Neues.
- Zwei vorab festgelegte Tests auf diesen ueberlebensfreien Daten, beide klar negativ (Zahlen und Datenpruefung in Abschnitt 4): Querschnitts-Momentum auf Top-30-Universum und Trendfilter auf Top-3/5/10 nach Volumen. Der feste BTC/ETH-Trend bleibt die beste Variante in beiden Zeitraeumen.
- Folgerung (Empfehlung an Patrick, Entscheid liegt bei ihm): **Wallet B "Explorer" (Querschnitts-Momentum) wird nicht gebaut**, `live_plan.yaml` laesst B auf `enabled: false`. Das Meta-Allokator-Konzept (6.1) entfaellt vorerst: mit zwei Strategien (Trend, Carry) bleiben feste Gewichte. Die Scout-Pipeline fuer neue Tokens (6.4) ist nach diesen Befunden das riskanteste Stueck: nur als Beobachtungsliste und Alarm, **keine automatische Anlage**; ein Papier-Test mit vorab festgelegter Bewertung waere der einzige akzeptable Weg zu echtem Geld.
- Nachrichten (6.5): bisher kein messbarer Nutzen (Fear & Greed, FOMC, Crash-Regel); Feeds nur als Information im Tagesbericht.

**Gegenpruefung Phase 2 (Opus, 7.10. Mittag):** `xstrend` und `xsmom` geprueft: Stablecoins und Hebel-Token ausgeschlossen, Position Tag i wirkt ab i+1, Vola close-to-close, Vergleich bei gleichen Kosten fair. Ergebnis gilt. Kleinigkeit ohne Einfluss auf das Fazit: `xstrend.positions` zaehlt SMA-Tage ueber vorhandene Kerzen, nicht Kalendertage (nur bei Coins mit Luecken relevant).

**Naechste Aufgaben (Reihenfolge)**
0. **Go/No-Go-Kriterien: von Patrick bestaetigt am 7.10.** (A bis F, Wortlaut in `docs/STRATEGIE.md` Abschnitt 8, nicht mehr aendern). Startbetrag 1'000 USDC echtes Geld, `live_plan.yaml` Abschnitt `live`. ****Kriterium D erfuellt (Logik, 7.10.):** `quant/protection_check.py` loest Kill-Switch (warn, brake, Hysterese, stop, klebender Stopp, Stopp unter 60% der Einzahlungen, Ein-/Auszahlung) und sechs Sicherungsarten mit Testdaten aus, Schwellen aus `live_plan.yaml`; Doku `docs/KRITERIUM_D.md`; Test `ProtectionCheckTests` (erkennt auch gelockerte Schwellen). Danach gebaut (7.10.): ntfy-Kurzalarm im Live-Lauf (`hl_live.alert_text`/`notify`, nur Fake-Post getestet) und Sperre, wenn das USDC im Perp- statt Spot-Konto liegt (`fetch_perp_value`, Opus-Befund 1; echtes Kontoverhalten bei der Einrichtung pruefen). Release `v2026.10.2` faellig, bevor Live-Tests auf dem Server laufen, sonst keine Eile. Kriterium F erfuellt am 7.10. (Screenshot `check_f.sh`, alle 7 Punkte PASS):** Auto-Update aus, signierter Update-Weg `/usr/local/sbin/autotrader-update` aktiv, erstes Tag `v2026.10.1` (Commit bf3ab70) von Patricks Schluessel signiert, auf dem Server geprueft und ausgerollt; ntfy-Thema neu (Zufallsname, nur in `.env`), `NTFY_DETAIL=short`, Testmeldung und Kurzbericht kamen an; ufw aktiv, `HC_PING_URL` gesetzt. **Ab jetzt gilt der Release-Ablauf:** jede Codeaenderung kommt erst auf den Server, wenn Patrick sie signiert. Windows-cmd im Ordner `C:\Users\Patrick\autotrader`: `git pull`, `git tag -s vJAHR.MONAT.N -m "Release"`, `git push origin vJAHR.MONAT.N`; dann SSH: `sudo autotrader-update vJAHR.MONAT.N`. Die Nummer zaehlt hoch (naechste: v2026.10.2). Claude sagt Patrick bei jedem Push, ob ein Release noetig ist. Der Server laeuft bis dahin mit v2026.10.1. **Geprueft auf dem Server am 7.10. (Screenshot):** alle 8 Tests in `tests/test_deploy.py` gruen, darunter gueltiger Tag, fremder Schluessel, unsignierter Tag, Push auf main allein. Aufruf: `cd /opt/autotrader && sudo -u autotrader venv/bin/python -m unittest discover -s tests -p "test_deploy.py" -v`. Noch nicht gelaufen: `update_setup.sh lock` und `check_f.sh` auf dem echten Server. Signierschluessel erzeugt (oeffentlicher Teil in `deploy/release_signer.pub`, privater nur auf Patricks PC, Windows cmd). Offen: `update_setup.sh lock` auf dem Server, erstes signiertes Tag, `check_f.sh`. Patrick muss einmal die Server-Umstellung ausfuehren (Anleitung in `deploy/README_signed_update.md`).
1. Papierbetrieb laufen lassen (seit 6.10., Entscheidung ueber Live frueh. 1.12.2026). Tagesbericht und Ledger beobachten. Keine Strategie-Aenderungen im Papierbetrieb, sonst ist der Track-Record wertlos.
2. Live-Vorbereitung ohne Geld (Kriterium E). **Gebaut am 7.10., nur mit Fakes getestet (142 Tests):** `quant/hl_sender.py` (SDK 0.24.0 aus dem GitHub-Quelltext gelesen, IOC-Limit-Orders, Doppelsende-Schutz per `orderStatus`, Abbruch bei Fehler, Verkaeufe zuerst), `quant/hl_live.py` (einziger Einstieg fuer echte Orders, NICHT im Timer, fuenf Sperren: `mode: live`, `live.armed_until`, `HL_AGENT_KEY` und `HL_ACCOUNT_ADDRESS` nur in der Umgebung, `--confirm-real-money`, SDK-Version), `hl_exec.run(..., sender=)` mit echtem Konto, eigenem Kill-Switch-Zustand (`killswitch_A_live.json`), Protokoll `orders_live.csv`, Kontowert-Obergrenze `live.max_equity_usdc`, Soll/Ist-Abgleich nach der Ausfuehrung (`max_position_mismatch`), `quant/hl_sdk_check.py` (Pruefung ohne Schluessel, siehe unten), `deploy/requirements-live.txt`. `live_plan.yaml` bleibt `dry-run`, `armed_until: null` (ein Test stellt das sicher). **SDK-Pruefung auf dem Server am 7.10. bestanden (Screenshot):** SDK 0.24.0 im venv installiert (Abhaengigkeiten nicht festgenagelt, optional spaeter mit Hashes), UBTC = Paar @142, Asset 10142, 5 Mengen-Dezimalstellen; UETH = @151, Asset 10151, 4 Dezimalstellen (stimmt mit dem Plan ueberein), lokale Signatur erzeugt, nichts gesendet. **Weiterhin ungeprueft gegen die echte API:** Antwortformat von `exchange.order`, `orderStatus` bei unbekannter cloid, `spotClearinghouseState` (braucht Patricks Adresse), Preis-Tickgroesse. Pruefung durch Patrick auf dem Server: SDK installieren (`requirements-live.txt`), dann `python -m autotrader.quant.hl_sdk_check --address <seine Adresse>` (liest nur, sendet nichts). Dann erst Kleinstbetrag-Test nach F und ausdruecklicher Freigabe. **Kill-Switch-Kommando gebaut (7.10., 147 Tests):** `python -m autotrader.quant.killswitch status|flow|reset --config quant_40.yaml [--mode live|dryrun]`. `flow --amount 500` (Einzahlung) bzw. `--amount -200 --equity-before KONTOWERT` (Auszahlung), ohne `--confirm` nur Vorschau, mit `--confirm` verbucht und in `killswitch_flows.csv` protokolliert. **Reihenfolge: erst verbuchen, dann ueberweisen, kein Live-Lauf dazwischen**, sonst zaehlt eine Einzahlung doppelt (evaluate hebt den Hoechststand schon auf den Kontowert). `reset` nur nach Stopp, nur auf Patricks ausdruecklichen Befehl. **Offen:** Mindestorderwert 10 USD gegen die Doku pruefen. **Gegenpruefung Opus 7.10. nachmittags, offene Punkte fuer E:** (1) Hyperliquid trennt USDC im Spot- und im Perp-Konto (SDK: `usd_class_transfer`, Kontomodus `unifiedAccount`/`portfolioMargin`/`disabled`). Eine Einzahlung ueber Arbitrum landet vermutlich im Perp-Konto; `fetch_account` liest nur `spotClearinghouseState` und saehe dann Kontowert 0 (blockiert, also sicher, aber kein Handel). Bei der Einrichtung pruefen und einmal von Hand nach Spot umbuchen oder den Kontomodus klaeren; fuer Carry spaeter beide Konten lesen. (2) Mindesteinzahlung laut Hyperliquid-Doku 5 USDC, kleinere Betraege gehen verloren (vor der Einzahlung in der Doku nachlesen). (3) Healthchecks-Ping-URL stand am 7.10. im Chat; wer sie kennt, kann OK-Pings senden und den Dead-Man-Switch stumm machen. Vor Live neu erzeugen. (4) SDK-Abhaengigkeiten im venv sind nicht festgenagelt (rund 25 Pakete); vor Live mit `pip freeze` festhalten. (5) Plattformwahl fuer groessere Betraege neu bewerten (siehe Abschnitt 9, Punkt 3): Trend ueber Unit-Token traegt Bridge-Risiko (2-von-3-Guardians, kein oeffentliches Audit bekannt). Fuer 1'000 USDC vertretbar, vor einer Aufstockung ueber ca. 10'000 USDC Trend auf einer regulierten Boerse mit echtem BTC/ETH pruefen. Unit-Bridge-Einzahlung (UBTC/UETH) ist nicht gebaut: gekauft wird auf dem Spot-Markt, Einzahlung von USDC macht Patrick von Hand.
3. Carry-Ausfuehrung (Spot long + Perp short) bauen, **vorher** Signalquelle klaeren (Ergebnis P1 12 in Abschnitt 4: HL-Funding rund doppelt so hoch wie Binance, Signale nur zu 69/82% gleich): vorab festgelegter Walk-Forward-Test des Carry auf HL-Funding, Varianten zaehlen, nur 3.3 Jahre Daten, kein Basisrisiko modelliert. Erst danach entscheiden, ob das Signal auf HL-Funding umgestellt wird; waehrend der Papierphase keine Aenderung am Signal.  erst wenn Carry im Papierbetrieb relevant wird (aktuell flat, Funding 4.6 bis 5.0% p.a. unter der Einstiegsschwelle).
4. P0/P1-Reste (P1 12: erledigt am 7.10., Ergebnis Abschnitt 4. Werkzeug: `cd /opt/autotrader && sudo -u autotrader venv/bin/python -m autotrader.quant.fundcmp --config quant_40.yaml`,, holt die stuendliche HL-Funding-Historie und vergleicht mit Binance, zeigt auch die letzten 14 und 30 Tage): Update-Pfad haerten (signierte Tags, Abschnitt 5 Punkt 1), ntfy absichern (Punkt 8). **Harte Reihenfolge:** Update-Pfad gehaertet und Auto-Update als root aus, bevor irgendein Agent-Key auf den Server kommt. Das gilt auch fuer den kleinen SDK-Test aus Punkt 2.
5. Steuer-Export als CSV, Steuerberatung (Schweiz) vor Live.
6. Nur mit neuem, vorab begruendetem Edge: weitere Strategien testen. Methode wie in Phase 2 festhalten: Varianten vorab zaehlen, ueberlebensfreie Daten, Kosten x2, Datenpruefung, negative Ergebnisse melden.

**Daneben offen (kleiner)**
- P1 12: Funding-Timing Binance vs. Hyperliquid (echtes Hyperliquid-Funding ueber `fundingHistory`).
- Kontowert-Abruf `spotClearinghouseState` ist nur aus der Doku gebaut; erst mit echter Adresse pruefbar.
- ntfy-Thema ist oeffentlich (P0 8), vor Live loesen.

**Lehren aus der Gegenpruefung am 7.10. (Opus hat Sonnets Zusammenfassung geprueft)**
- Beispiele muessen die Aussage tragen: "2025 und 2026 nicht zweistellig" war falsch, 2026 lag bei +12.5%. Schwache Jahre sind 2022 (-3.7%) und 2025 (-1.4%).
- Ursachen nur behaupten, wenn einzeln gemessen. Aendert ein Commit mehrere Dinge, heisst es "vermutlich".
- Den Ertrag richtig zuordnen: Trend BTC/ETH bringt etwa die Rendite von Buy-and-Hold (+32.4% gegen +33.5%), der Nutzen des Filters ist der kleinere Verlust (-28% statt -76%).
- Bezugsgroesse nennen: Carry +7% gilt fuer den Carry-Teil allein, Beitrag zum Profil rund 2 Pp.
- Schaetzungen als Schaetzung kennzeichnen.


## 1. Auftraggeber und Arbeitsweise

- **Patrick Stüssi**, Richterswil (ZH). Kommunikation auf Deutsch, präzise, Empfehlung zuerst, dann Begründung. Kurze Absätze, Aufzählungen. Kein Eszett, immer "ss". Keine Floskeln, keine typischen KI-Schreibmuster (aufgeblasene Adjektive, "nicht nur … sondern", künstliche Dreiergruppen, Schlussfloskeln).
- Patrick will Ehrlichkeit über Belege. Wenn etwas geraten ist, so sagen. Wenn ein Test negativ ist, so sagen.
- **Ziel des Projekts:** autonomer Krypto-Trading-Agent mit eigener Wallet, zweistellige Jahresrendite, Verlusttoleranz bis 40% ("Spielgeld, langfristig").
- **Ablauf der Zusammenarbeit:**
  - Code liegt im privaten Repo `vinaccord/autotrader`, Branch `main`. Die Session hat Push-Recht.
  - Der Server holt den Code täglich um 00:50 UTC (`quant-update.timer`). Sofort: Patrick führt `sudo systemctl start quant-update.service` aus.
  - Patrick führt Befehle per SSH aus und schickt Screenshots. Befehle immer vollständig und kopierbar geben, mit Hinweis, in welchem Fenster (Windows-cmd oder SSH `ubuntu@...`). Er hat sich mehrmals im Fenster vertan.
  - Die Claude-Sandbox erreicht Binance, Hyperliquid, GDELT, alternative.me **nicht**. Alles Netzwerk-Abhängige wird mit Fakes getestet und erst auf dem Server echt geprüft. Das jedes Mal sagen.
  - Tests: `python3 -m unittest discover -s tests` (96 Tests, alle grün am 7.10.).
  - Commits mit den Attribution-Zeilen aus dem System-Reminder.

## 2. Infrastruktur

| Teil | Stand |
|---|---|
| Server | Infomaniak VPS Lite, Ubuntu 24.04, 1 vCPU, 2 GB, IP 179.237.125.121, Benutzer `ubuntu`, Laufzeit bis 06.10.2027 |
| SSH von Patrick | `ssh -i %USERPROFILE%\.ssh\autotrader_vps ubuntu@179.237.125.121` (Windows cmd) |
| App | `/opt/autotrader` (Benutzer `autotrader`, venv, `data/quant/`) |
| Code-Quelle | `/opt/autotrader-src` (Git-Clone über Deploy-Key `/root/.ssh/deploy_autotrader`, nur Lesen) |
| Timer | `quant-update.timer` 00:50 UTC, `quant-daily.timer` 01:05 UTC |
| Push-Meldung | ntfy.sh, Thema in `/opt/autotrader/.env` als `NTFY_TOPIC` (Patrick hat die App) |
| Logs | `data/quant/daily.log`, `signals.log`, `latest_report.txt`, `state.json`, `fng.csv`, `gdelt_tone.csv` |
| Daten | Binance-Tageskerzen und Funding ab 2019-12 (BTC, ETH) in `data/quant`; 16 Coins ab 2020-09 in `data/quant_multi` |

Paper-Betrieb läuft seit **6. Oktober 2026**. Entscheidung über Live frühestens nach 8 Wochen, also um den **1. Dezember 2026**.

## 3. Was das System heute tut

Täglicher Lauf (`deploy/quant_daily.sh`): Daten holen → Backtest Profil 40 → Signal Profil 40 und Kernprofil → Makro-Abruf (Fear & Greed, GDELT) → Tagesbericht per ntfy. Seit 7.10.: jeder Schritt läuft weiter, wenn ein früherer scheitert; bei Fehlern kommt eine ntfy-Meldung "Autotrader: FEHLER".

**Hauptprofil `quant_40.yaml`**
- Trend: BTC und ETH, nur Long oder flat, SMA 200, Ziel-Volatilität 0.45, Hebel max. 1, feste Parameter.
- Carry: Spot long + Perp short, Hebel 2, Walk-Forward über ein kleines Gitter.
- Gewichte fest 30% Carry / 70% Trend. Zielvariante **Spill**: flacher Carry-Anteil geht in den Trend (`quant/spill.py`), im Bericht als "Haupt+Spill" mitgeführt.

**Module (`autotrader/quant/`)**

| Datei | Zweck |
|---|---|
| `data.py` | Binance/Hyperliquid-Abruf, CSV-Cache (seit 7.10. atomar, mit Retry, Schrumpf-Schutz) |
| `strategies.py` | `carry_returns` (mit `flags`), `trend_returns` (SMA int oder Liste, optional `crash`, `event_days`) |
| `walkforward.py` | Walk-Forward-Auswahl, Allokator (inverse Vola, Sharpe-Tilt) |
| `pipeline.py` | verbindet alles; `fixed`-Gewichte und `trend.adapt: false` möglich |
| `cli.py` | `fetch`, `backtest`, `signal` |
| `report.py` | Tagesbericht, Warnungen, Papier-Ergebnis, ntfy |
| `macro.py` | Fear & Greed (Backtest), GDELT-Tonalität (nur Logging) |
| `variants.py` | Vergleich von Trend-Varianten und Coin-Körben (`quant_variants.yaml`) |
| `spill.py` | Test und Gewichte für Spill |

Der alte DEX-Agent (`autotrader/agent.py`, `adapt.py`, `security.py`, `risk.py`, `research.py`, `executor.py`, `market.py`, `db.py`) ist nicht in Betrieb. `security.py` (GoPlus-Honeypot-Check, fail-closed) ist für das Token-Scouting wiederverwendbar.

## 4. Ergebnisse bisher (Backtests auf echten Daten, vom Server)

| Test | Ergebnis | Entscheid |
|---|---|---|
| Kernprofil adaptiv (90% Carry) | CAGR +10.4%, MaxDD -6.8%, aber 2025/26 nur +2% / +0.3% | zu wenig Rendite |
| Profil 40 (30/70 fest), 2020-11 bis 2026-10 | CAGR +25.6%, Sharpe 1.16, MaxDD -18.5%; Kosten x2: +25.0% | Hauptprofil |
| Trend allein BTC/ETH | +32.5%, MaxDD -28.4% | Option |
| Spill | +29.0%, Sharpe 1.16, MaxDD -22.9%; Kosten x2: +28.2% | Zielvariante |
| Trend-Adaption per Walk-Forward | schlechter als feste Parameter | abgeschaltet |
| Fear & Greed (Gier/Angst halbiert Position) | Sharpe -0.06 / -0.02 | verworfen |
| SMA-Mix 50/100/200 | gleiche Rendite, MaxDD 10 Pp schlechter | verworfen |
| Crash-Regel (-15% in 7 Tagen) | kein Nutzen | verworfen |
| FOMC-Tage halbieren | kein Nutzen | verworfen |
| 5 Coins gleichgewichtet | Sharpe +0.15, MaxDD 8 Pp schlechter | nicht übernommen |
| 12 / 16 Coins gleichgewichtet | CAGR 15–16% statt 21% (ab 2021-06) | verworfen |
| Trend-Sensitivitaet (7.10., Server, 2020-11 bis 2026-10, `quant.sensitivity`) | Trend / Profil 40 CAGR: Spot 10 bps +32.4% / +25.5%; Spot 20 bps +31.6% / +24.9%; Spot 40 bps +29.9% / +23.8%; Spot 10 bps + 1 Tag spaeter +28.6% / +23.0%; Spot 20 bps + 1 Tag +27.8% / +22.5%; Perp + Funding +24.3% / +20.1%; Perp + Funding + 1 Tag +20.8% / +17.7%. MaxDD Trend -28% bis -32%, Profil 40 -18.5% bis -22% | Spot bestaetigt: Kosten x4 kosten 2.5 Pp, 1 Tag Verzoegerung 3.8 Pp, Perp-Funding 8 Pp |
| Liquiditaet Hyperliquid Spot (7.10., Server, `quant.hl_liquidity`) | UBTC/USDC: 24h-Volumen 29.1 Mio USD, Spread 0.2 bps; Marktorder 50'000 USD kaufen 0.9 bps / verkaufen 0.1 bps. UETH/USDC: 13.7 Mio USD, Spread 0.4 bps; 50'000 USD kaufen 0.6 / verkaufen 1.2 bps. Basis Spot-Mid gegen Perp-Mid +1.5 bps (beide). Perp-Buecher aehnlich duenn im Spread | Liquiditaet reicht weit ueber die geplante Groesse; Gebuehr (7 bps Taker) ist der Hauptkostenpunkt |
| Nach P1-Korrekturen (7.10., Server, Commit 52e16b7) | Profil 40 idle: +25.5%, Sharpe 1.15, MaxDD -18.5%. Spill: +28.3%, Sharpe 1.21, MaxDD -18.4%, Calmar 1.54 (vorher +29.0%, Sharpe 1.16, MaxDD -22.9%). Trend allein +32.4%, MaxDD -28.4%. Carry adaptiv +7.0% bei Sharpe 8.8 (Warnsignal, Modell ohne Basisrisiko) | Profil 40 praktisch unveraendert. Spill: Rendite 0.7 Pp tiefer, MaxDD 4.5 Pp besser. Vermutlich wegen der Walk-Forward-Carry-Parameter (Carry ist oefter in Position, weniger fliesst in den Trend); nicht einzeln gemessen, der Commit aendert drei Dinge gleichzeitig. Spill bleibt Zielvariante |
| Querschnitts-Momentum (7.10., Server, `quant.xsmom`, Data Vision inkl. 197 ausgelistete/eingestellte Symbole) | Alle 12 Laeufe (6 Varianten x Kosten 20/40) negativ: ab 2020-12 CAGR -35% bis -63%, MaxDD fast -100%; Top-30 gleichgewichtet -19.5%, MaxDD -97%; Trend BTC/ETH +31.4%, BTC Buy-and-Hold +28.5%. Ab 2019-07 aehnlich (-25% bis -57%). Datenpruefung (`--diagnose`): die 10 groessten Tagesspruenge sind echte Ereignisse (LUNA-Kollaps Mai 2022, DOGE 28.1.2021, Pumps kleiner Coins), Verlauf passt zur Marktgeschichte (Momentum 2021 +1214%, 2022 -92%, Ende 0.08; schlechtester Tag 19.5.2021) | Verworfen, nicht einbauen. Ergebnis gilt |
| Trend auf Top-N nach Volumen (7.10., Server, `quant.xstrend`) | ab 2020-12: BTC/ETH fix +30.5% (Kosten 20), Sharpe 1.02, MaxDD -29%; Top-3 +18.2%, MaxDD -41%; Top-5 +12.9%, -36%; Top-10 +13.3%, -38%. Ab 2019-07 gleiches Bild (BTC/ETH +30.3%, Top-N +12% bis +19%). Einzig 2021 war Top-10 besser (+67% gegen +39%), 2022 und 2025 deutlich schlechter | Verworfen: BTC/ETH fix bleibt. Breitere Coin-Auswahl senkt die Rendite und erhoeht den Verlust in beiden Zeitraeumen |
| Funding Binance gegen Hyperliquid (7.10., Server, `quant.fundcmp`, 1214 volle Tage 2023-06-08 bis 2026-10-06, Standardparameter ohne Walk-Forward) | Funding p.a. im Mittel: BTC Binance +7.2% / HL +14.4%, ETH +7.3% / +14.5%. Korrelation Tagesfunding 0.75 (BTC) / 0.72 (ETH), 14-Tage-Mittel 0.89 / 0.86. Vorzeichen verschieden an 186 / 172 Tagen (15% / 14%). Carry-Signal gleich an 69% / 82% der Tage. Carry-Lauf (nur Carry-Teil, ohne Basisrisiko, MaxDD -0.1 bis -0.2% ist Modellgrenze): BTC Binance +9.4% total (CAGR 2.7%, 389 Tage in Position) gegen HL +30.5% (8.3%, 751 Tage); ETH +9.8% (2.9%) gegen +26.0% (7.2%). Einstiegstag mit 2/3 bzw. 23/24 des Funding: Aenderung 0.0 bis 0.1 Pp | Binance-Funding im Backtest ist kein Spiegel von Hyperliquid, sondern in dieser Periode rund halb so hoch (konservativ fuer den Carry-Teil). Verpasste Einstiegszahlung unerheblich. Folge: Signalquelle fuer Live-Carry muss HL-Funding sein; Test dafuer vorab festlegen (Aufgabe 3). Profil-40-Backtest nicht aendern, Papierphase laeuft. Aktuell (Stand 6.10.): letzte 14 / 30 Tage p.a. BTC Binance +3.0% / +5.0%, HL +8.9% / +8.8%; ETH Binance +5.3% / +4.6%, HL +11.1% / +10.2%. Alle unter der Einstiegsschwelle 12%, Carry waere auch auf HL-Funding flat (ETH knapp darunter) |
| GDELT-Abruf | HTTP 429 auch mit Pause und Retry (7.10.) | abgeschaltet |

**Lehre:** Mehr Regeln und mehr Coins im Gleichgewicht haben nichts gebracht. Der Ertrag kommt aus dem Trend-Filter auf BTC/ETH. Die Jahre sind sehr ungleich (2023 +42%, 2024 +52%, 2022 -4%, 2025 -1%).

**Achtung Data Snooping:** Profil 40 (Ziel-Vola 0.45, 30/70) wurde nach Ansicht der Ergebnisse gewählt. Die Zahlen sind "in-sample-getunt". Echte Out-of-Sample-Prüfung ist nur der Paper-Betrieb.

## 5. Code-Review vom 7. Oktober (eigene Prüfung + unabhängiger Agent)

### Bereits behoben (Commit b3c0e81)
- Ein fehlgeschlagener Funding-Abruf überschrieb den Funding-Cache mit einer leeren Datei → `load_all` fand 0 Tage → Lauf brach ab, ohne Meldung. Jetzt: Funding nur bei Erfolg speichern, atomar schreiben, kein Überschreiben mit deutlich kürzeren Reihen, Retry bei 429/5xx/Timeout.
- `quant_daily.sh` brach bei jedem Fehler still ab (`set -e`). Jetzt: Schritte laufen weiter, Bericht läuft immer, ntfy-Alarm bei Fehlern, Exit-Code 1.
- `update.sh` kopiert Units aus `/opt/autotrader-src` statt aus dem vom App-Benutzer beschreibbaren Ordner. Dienst-Timeout 45 min.

### Offen, nach Priorität

**P0 – vor jedem Live-Geld**
1. **Auto-Deploy läuft als root aus GitHub.** Wer auf `main` pushen kann (auch eine KI-Session oder ein geleakter Token), hat innerhalb von 24 h root auf dem Server. Umbau: `update.sh` ausserhalb des Repos, root-eigen; Fetch als unprivilegierter Benutzer; signierte Tags (`git verify-tag`) und Branch-Schutz; Units nicht automatisch installieren. **Vor Live: Auto-Update abschalten** (`systemctl disable --now quant-update.timer`) und Updates nur nach Patricks Freigabe.
2. **Live-Ausführung existiert nicht.** Siehe Abschnitt 7.
3. **Trend über Perps kostet Funding** (Long zahlt im neutralen Markt rund 11.6% p.a.). Entschieden: Trend über Spot (7.1). Der Backtest muss Spot-Kosten (7 bps Taker + Slippage) abbilden, die Perp-Variante läuft als Vergleich mit echtem Hyperliquid-Funding.
4. **Papier-Ergebnis wird täglich neu berechnet**, es gibt kein festes Protokoll. Ein append-only Ledger einführen (`data/quant/ledger.csv`: Datum, Zielgewichte je Coin und Teil, Preis zum Signalzeitpunkt, realisierte Rendite des Folgetags). Das ist der echte Track-Record für die Live-Entscheidung.
5. **Ausführungsverzögerung nicht abgebildet.** Backtest füllt zum Tagesschluss, der Job läuft 01:05 UTC. Sensitivität mit 1 Bar Verzögerung bzw. Open des Folgetags rechnen.
6. **Dead-Man-Switch fehlt.** Kommt gar keine Meldung (Server aus), merkt es niemand. Healthchecks.io (gratis) oder ein zweiter Check, der nach 36 h ohne Bericht alarmiert.
7. **Server härten:** Passwort-Login aus (`PasswordAuthentication no`), `ufw` (nur 22), `fail2ban`, GitHub-Host-Key-Fingerprint fest eintragen statt `ssh-keyscan` (TOFU).
8. **ntfy.sh ist öffentlich:** Wer das Thema kennt, liest Positionen mit und kann falsche "OK"-Meldungen senden. Vor Live: Zugangs-Token oder eigener ntfy-Server, Inhalte reduzieren.

**P1 – Korrektheit des Backtests**
9. **Carry-Liquidation unterschätzt:** `strategies.py` vergleicht nur Tageshoch mit Vortagesschluss und bucht keinen Verlust. Kumulierte Bewegung seit Einstieg verfolgen, Rebalancing-Kosten oder Liquidation buchen.
10. **Spill inkonsistent:** `spill.py` rechnet Carry mit Standardparametern, das Signal mit Walk-Forward-Parametern. Der Bericht kann gleichzeitig "Carry IN" und "flat" zeigen. Lösung: `pipeline.run` gibt Carry-Renditen und Flags je Coin aus dem Walk-Forward zurück, `spill` nutzt diese.
11. **Kalenderlücken:** `load_all` nimmt nur Tage, die in allen Preis- und Funding-Reihen vorkommen. Fehlt ein Funding-Tag, entsteht eine Zwei-Tages-Rendite als ein Tag. Kalender aus Preisen bauen, fehlendes Funding = 0, Lücken loggen.
12. Funding-Timing: Einstiegstag bekommt im Backtest die 00:00-Zahlung, die live verpasst wird. Funding-Quelle ist Binance, Ziel Hyperliquid (stündlich, andere Höhe).
13. Tägliches Rebalancing der Körbe ist kostenlos gerechnet.

**P2 – Qualität**
14. Config laden und `data_dir` auflösen ist fünfmal kopiert (`cli`, `variants`, `spill`, `report`, `macro`) → `quant/config.py`.
15. `pipeline.run` läuft pro Tag etwa sechsmal → Ergebnis einmal berechnen und weitergeben.
16. Magische Zahlen (0.3, 0.9/lev, -0.30), breite `except Exception` im Bericht.
17. Bericht warnt bei -30%, Kommentar sagt 40% → in die Config.
18. Kernprofil im Bericht nach Anzahl statt Datum ausgerichtet.
19. `macro.apply_rule`: Wechselkosten werden an Tagen mit Rendite 0 nicht gebucht.
20. `update.sh`: gelöschte Dateien bleiben liegen, neue Requirements werden nicht installiert. `requirements.txt` ohne feste Versionen.
21. Logrotate für `daily.log`, `signals.log`.
22. Alten DEX-Agenten archivieren oder entfernen, ausser `security.py`.

## 6. Patricks Ausbauwünsche (7. Oktober) und Bewertung

Patricks Wortlaut sinngemäss: Strategie soll sich laufend an Markt und Gegebenheiten anpassen, möglichst hohe Gewinne. Ab einer sinnvollen Grösse Einsatz auf zwei Wallets splitten, die autonom mit unterschiedlichen Strategien arbeiten. Coins nicht fix auf 2–3, sondern die mit dem meisten Potenzial. Neue Trends und Tokens erkennen, Whitepaper lesen, bei Potenzial testen, wenn gut, live gehen.

### 6.1 Laufende Anpassung

**Was die Daten sagen:** Anpassung innerhalb einer Strategie (Parameter per Walk-Forward) hat nichts gebracht. Sinnvoller ist Anpassung **zwischen** verschiedenen Strategien.

**Vorschlag: Strategie-Bibliothek + Meta-Allokator**
- Jede Strategie liefert eine kausale Tagesrenditen-Reihe und eine Zielposition.
- Bibliothek (erste Ausbaustufe): Trend BTC/ETH (bestehend), Carry (bestehend), **Querschnitts-Momentum** auf einem dynamischen Universum (6.3), Cash.
- Meta-Allokator: Gewichte aus inverser Volatilität, leicht nach trailing Sharpe geneigt, mit Ober- und Untergrenzen und Schrumpfung Richtung Gleichgewicht. Gewichtswechsel nur monatlich. Das Gerüst existiert in `walkforward.allocate`.
- Neue Strategien durchlaufen eine feste Promotion: Backtest (Kosten x2, 1 Bar Verzögerung) → mindestens 8 Wochen Paper im Ledger → kleiner Live-Anteil → volle Gewichtung. Abstieg automatisch bei Verletzung von Grenzen (z.B. Drawdown grösser als 1.5x Backtest-Maximum).
- Kein LLM entscheidet über Positionen. LLMs liefern höchstens Zusammenfassungen und Risiko-Flags.

### 6.2 Wallet-Split (entschieden 7.10., Werte in `live_plan.yaml`)

**Technische Grenze:** Hyperliquid-Agent-Keys können handeln, aber nicht abheben oder überweisen (dexly.trade, Stand Juni 2026). Der Bot kann den Split nicht selbst ausführen, ohne einen Vollzugriffs-Schlüssel zu halten. Das ist ausgeschlossen. Der Bot meldet, Patrick überweist.

**Entscheid**
- **Zwei getrennte Wallets** (zwei MetaMask-Adressen, je ein eigenes Hyperliquid-Konto mit eigenem Agent-Key). Keine Sub-Accounts: Die gibt es laut Hyperliquid-Doku erst ab 100'000 USD Handelsvolumen.
- **Keine Kaskade A → B → C.** Krypto-Coins sind stark korreliert. Mehr Wallets auf derselben Plattform mit ähnlichen Coins senken das Marktrisiko kaum. Ein Split lohnt nur, wenn die zweite Wallet eine eigenständige, getestete Strategie fährt. Davon haben wir genau zwei: Core und Explorer.
- **Auslöser für den Split** (beides muss erfüllt sein):
  1. Die Explorer-Strategie hat ihren Backtest (Kosten x2, 1 Bar Verzögerung) und 8 Wochen Paper im Ledger bestanden.
  2. Gesamtkapital mindestens 10'000 USDC. Begründung (eigene Abwägung, keine Studie): Explorer hält etwa 5 Positionen. Ab etwa 3'000 USDC in Wallet B liegt jede Position weit über dem Mindestorderwert und die Gebühren fallen nicht ins Gewicht. Darunter bringt der Split wenig und kostet Komplexität.
- **Aufteilung:** 70% Core (Wallet A), 30% Explorer (Wallet B).
- **Rebalancing:** Quartalsweise prüfen. Weicht die Aufteilung um mehr als 10 Prozentpunkte ab, schickt der Bot per ntfy den Betrag und die Richtung. Patrick überweist.
- **Dritte Wallet:** erst ab 100'000 USDC Gesamtkapital, nur mit einer dritten, eigenständig getesteten Strategie und dann auf einer zweiten Plattform (gegen Plattformrisiko). Vorher nicht.
- **Rollen:** Wallet A "Core" = Trend BTC/ETH (Spot) + Carry, Spill-Variante. Wallet B "Explorer" = Querschnitts-Momentum auf dem dynamischen Universum inkl. geprüfter neuer Tokens (6.3, 6.4).
- **Betrieb:** je Wallet eigener Prozess, eigene Config, eigene Limits. Ein Supervisor hält nur die globale Notbremse (7.2) und den gemeinsamen Tagesbericht.

### 6.3 Dynamisches Coin-Universum

**Nicht nach "Potenzial" von Hand wählen.** Das ist im Rückblick immer eine Gewinnerliste (Survivorship Bias). Stattdessen feste, objektive Regeln, die jeden Tag neu angewendet werden:
- Handelbar auf der Ausführungsplattform (Hyperliquid `meta`-Endpunkt liefert die Perp-Liste).
- Mindestalter (Vorschlag 120 Tage Kursdaten), Mindestvolumen (Vorschlag 20 Mio. USD Tagesvolumen, 30-Tage-Median).
- Keine Stablecoins, keine Wrapped-Token.
- **Auswahl per Querschnitts-Momentum:** Rang nach volatilitätsbereinigter Rendite (z.B. 30 und 90 Tage kombiniert), die besten N (Vorschlag 5) mit Ziel-Volatilität, nur wenn BTC über SMA 200 (Regime-Filter), sonst Cash. Wöchentlich neu gewichten, Band gegen Kleinst-Umschichtungen.
- Belege: Liu, Tsyvinski & Wu ("Common Risk Factors in Cryptocurrency", Journal of Finance 2022) finden einen Momentum-Faktor im Krypto-Querschnitt. Das ist aus meinem Wissensstand. Neuere Arbeiten zu realistischen Kosten wurden gesucht, aber nicht gelesen (Springer-Seite rate-limitiert). Vor dem Bau prüfen.
- **Backtest-Problem:** Für ein überlebensfreies Universum braucht man auch ausgelistete Coins (LUNA, FTT …). Binance liefert Kerzen ausgelisteter Paare teilweise nicht mehr. Lösung prüfen: Binance Data Vision (data.binance.vision, Monats-ZIPs, enthält nach meinem Wissen auch ausgelistete Symbole). Ohne das ist jedes Ergebnis zu optimistisch und muss so beschriftet werden.

### 6.4 Neue Tokens, Trends, Whitepaper

**Patricks Wunsch "sofort live" ist so nicht vertretbar und muss so gesagt werden:**
- Neue Tokens haben keine Kurshistorie, also gibt es nichts zu testen.
- Studie zu 17'194 neuen Uniswap-V2-Tokens: 88% Honeypots (arXiv 2502.10512, in `docs/STRATEGIE.md`).
- Ein LLM kann aus einem Whitepaper kein Kurspotenzial ableiten. Es kann Fakten und Warnsignale zusammenfassen.

**Vorschlag: Scout-Pipeline mit Stufen, Aufstieg nur nach Regeln**
1. **Erkennen (täglich):** neue Perps auf Hyperliquid (`meta`), neue Listings auf Binance (Ankündigungen), CoinGecko keyless `/search/trending` und `/coins/categories` (10–30 Abrufe/Minute laut Doku). Kategorien mit stark steigender Marktkapitalisierung als "Trend" markieren.
2. **Prüfen:** Sicherheitscheck (`security.py`, GoPlus, fail-closed), Tokenomics (FDV/Marktkapitalisierung, Unlock-Termine, Konzentration der Halter), Liquidität. LLM fasst Whitepaper und Doku zusammen und liefert Risiko-Flags, aber kein Kaufsignal. LLM über einen kostenlosen API-Tarif, siehe 6.5.
3. **Watchlist / Quarantäne:** Daten sammeln, bis Mindestalter und Mindestvolumen erreicht sind.
4. **Universum:** Erfüllt der Token die Regeln aus 6.3, kommt er ins Universum. Dann entscheidet allein das Momentum-Ranking.
5. **Grenzen:** max. 5% je Coin, neue Coins (unter 1 Jahr) zusammen max. 20% von Wallet B.

So wird ein neuer Trend automatisch und schnell berücksichtigt, aber nicht vor der Mindestprüfung.

### 6.5 Nachrichtenquellen und LLM (kostenlos, entschieden 7.10.)

**Quellen**

| Quelle | Inhalt | Kosten | Status |
|---|---|---|---|
| alternative.me Fear & Greed | Stimmung, Historie ab 2018 | gratis | läuft; als Filter wirkungslos |
| GDELT DOC 2.0 | Tonalität nach Stichwort, nur rollende 3 Monate | gratis | 429 vom Server, Fix aktiv, prüfen |
| RSS: CoinDesk, Cointelegraph, The Block, Decrypt | Schlagzeilen | gratis | bauen, Feed-URLs prüfen |
| Fed, SEC, Weisses Haus (RSS der Pressemitteilungen) | Zinsen, Regulierung, Erlasse | gratis | bauen, URLs prüfen |
| Truth Social (Trump) über das Archiv `https://www.trumpstruth.org/feed` | Posts, Archiv prüft "every few minutes" laut FAQ | gratis | bauen; Drittanbieter, Nutzungsbedingungen für automatischen Abruf unklar, kann wegfallen; höchstens alle 15 min abrufen |
| Hyperliquid `meta`, `spotMeta`, `metaAndAssetCtxs` | neue Perps/Spot-Paare, Funding, Open Interest | gratis | bauen |
| CoinGecko keyless | Trending, Kategorien, Märkte; 10–30 Abrufe/min | gratis | bauen |
| DefiLlama | TVL, Gebühren; Unlocks evtl. nur Pro | gratis/prüfen | prüfen |
| X/Twitter (Musk usw.) | Posts | 0.005 USD pro gelesenem Post, kein Gratis-Lesezugriff seit Feb. 2026 (opentweet.io, Juli 2026) | ausgeschlossen; 10 Konten kosten grob 10–30 USD/Monat, nur auf Patricks Wunsch |

Regel: Nachrichten dienen als Risiko-Flags, für das Scouting und für den Tagesbericht. In Positionen fliessen sie nur, wenn ein Backtest den Nutzen zeigt. Bisher hat kein Nachrichten- oder Stimmungssignal einen Nutzen gezeigt. Posts von Politikern bewegen Kurse innerhalb von Minuten. Ein Tagessystem kommt dafür zu spät.

**LLM für Zusammenfassungen (Whitepaper, Nachrichten): kostenloser API-Tarif statt Anthropic-Key**
- **Primär: Groq Free Tier.** Laut ianlpaterson.com (Stand August 2026): u.a. `llama-3.3-70b-versatile`, `gpt-oss-120b`, `qwen3-32b`; 14'400 Anfragen/Tag, 6'000 Tokens/Minute, keine Kreditkarte, kommerzielle Nutzung erlaubt. OpenAI-kompatible Schnittstelle, also mit `requests` ohne extra SDK nutzbar.
- **Fallback: Google Gemini Flash (Free Tier),** dann Mistral (Free/Developer).
- Gratis-Tarife ändern sich ohne Vorwarnung. Code muss ohne LLM weiterlaufen (Zusammenfassung fehlt dann, sonst nichts).
- Nur öffentliche Texte senden. Gratis-Tarife können Daten zum Training nutzen. Das ist hier unkritisch, weil nichts Privates übermittelt wird.
- **Lokales Open-Source-Modell auf dem Server: nicht sinnvoll.** Der VPS hat 2 GB RAM und 1 vCPU. Ein brauchbares Modell (7–8 Mrd. Parameter, quantisiert) braucht grob 6–8 GB RAM und wäre auf einer CPU sehr langsam (eigene Schätzung). Ein grösserer Server kostet mehr, als die Gratis-API spart.
- Key-Ablage: `GROQ_API_KEY` in `/opt/autotrader/.env`. Patrick legt den Key selbst an und trägt ihn ein. Nie im Chat.

### 6.6 Weitere Algorithmen, die sich testen lassen
- Funding als Stimmungsfilter (extrem hohes Funding → Trend-Position kürzen).
- Open-Interest-Veränderung als Überhitzungsfilter (Hyperliquid-Daten, Historie kurz).
- Volatilitäts-Ziel auf Portfolio-Ebene statt je Coin.
- Mean-Reversion kurzfristig: hohes Risiko, nur mit sehr strengem Test.

Jeder Test: Zahl der Varianten nennen, Kosten x2, 1 Bar Verzögerung, Jahre einzeln.

## 7. Live-Ausführung (noch nicht gebaut)

### 7.1 Plattform und Ausführung (entschieden 7.10.)

**Entscheid: Hyperliquid, Trend über Spot (UBTC/UETH gegen USDC), Carry über Spot long + Perp short.**

Begründung:
- **Perps kosten beim Long-Trend Funding.** Laut Hyperliquid-Doku ist die Zinskomponente fest 0.01% pro 8 Stunden, "11.6% APR paid to short". In einem neutralen Markt zahlt ein Long also rund 11.6% pro Jahr. Bei durchschnittlich etwa 70% Trend-Exposure wären das grob 8 Prozentpunkte Rendite pro Jahr weniger (eigene Rechnung). Das frisst einen grossen Teil des Backtest-Ertrags.
- **Spot-Gebühren** (Basistarif): Taker 0.070%, Maker 0.040%. Perps: Taker 0.045%, Maker 0.015%. Der Trend handelt selten, die Gebührendifferenz ist klein gegen 11.6% Funding.
- **Spot auf Hyperliquid** gibt es für BTC, ETH, SOL über die Unit-Bridge (UBTC, UETH, USOL). Risiko: 2-von-3-Guardian-Modell, laut hyperliquidguide.com (Sept. 2026) kein öffentlich bestätigtes Audit. Gegenmassnahme: Unit-Token nur halten, solange der Trend long ist; sonst USDC.
- **Agent-Key** auf Hyperliquid kann handeln, aber nicht abheben. Das ist der wichtigste Sicherheitsvorteil.
- **Verworfen:**
  - MetaMask-Swaps: 0.875% Gebühr pro Swap (cryptoslate.com, Coin Bureau). Zu teuer.
  - Handel direkt aus der Wallet (MetaMask, MyEtherWallet) oder über Uniswap: Der Bot bräuchte den privaten Schlüssel der Wallet auf dem Server und könnte damit auch alles abheben. Ein Serverleck wäre ein Totalverlust.
  - Zentrale Börse (Kraken, Binance o.ä.): KYC, oft höhere Spot-Gebühren, Gegenparteirisiko. Kein Vorteil gegenüber Hyperliquid für diesen Zweck.
- **Vor dem Bau prüfen (Sonnet):** Liquidität und Spread von UBTC/USDC und UETH/USDC über `spotMetaAndAssetCtxs`; Mindestorderwert in der offiziellen Doku; Backtest des Trends mit 7 bps Taker + Slippage; zum Vergleich die Perp-Variante mit echtem Hyperliquid-Funding (`fundingHistory`). Ergebnis Patrick zeigen.

**Zu bauen: `quant/hl_exec.py`**
- Kontostand und Positionen über das Info-Endpoint lesen (öffentlich per Adresse, im Trockenlauf ohne Key).
- Zielgewichte → Zielmengen, Rundung nach `szDecimals`, Mindestorderwert, Limit-Orders mit maximalem Slippage, idempotente Client-Order-IDs.
- Abgleich Soll/Ist nach jeder Ausführung, Alarm bei Abweichung.
- Modus `dry-run` (nur protokollieren) als Standard. `live` nur mit Schalter in `live_plan.yaml` und Patricks ausdrücklicher Freigabe im Chat.
- Offizielles Python-SDK von Hyperliquid prüfen (Signatur der Orders), Version festnageln.
- Steuer-Export: alle Orders als CSV (Datum, Coin, Menge, Preis, Gebühr, Funding).

### 7.2 Kill-Switch und Sicherungen (entschieden 7.10.)

Gemessen am **Höchststand des Kontowerts** (High-Water-Mark), je Wallet und global:

| Stufe | Auslöser | Aktion |
|---|---|---|
| Warnung | -20% ab Höchststand | ntfy-Warnung, sonst nichts |
| Bremse | -30% ab Höchststand | Exposure halbieren; volle Exposure erst wieder, wenn der Verlust auf unter -20% zurückgeht |
| Stopp | -40% ab Höchststand oder Kontowert unter 60% der Einzahlungen | alles verkaufen (USDC), Bot stoppt, Neustart nur nach Patricks Freigabe |

Begründung:
- Backtest-Maximum Spill -22.9%, Trend allein -28.4%. -30% liegt ausserhalb des bisher Gesehenen und deutet darauf hin, dass etwas anders läuft. -40% ist Patricks erklärte Toleranz.
- Ein früher harter Stopp würde eine Trendstrategie in normalen Rückschlägen abwürgen. Kaminski & Lo ("When do stop-loss rules stop losses?", J. Financial Markets 2014) zeigen nach meinem Wissensstand, dass Stop-Regeln nur bei Momentum- oder Regimewechsel-Verhalten Wert schaffen und bei reinem Zufallsverlauf schaden. Die Seite selbst war nicht abrufbar (robots.txt). Deshalb gestuft: erst bremsen, dann stoppen.
- Global: Fällt der Gesamtwert beider Wallets um -40% ab gemeinsamem Höchststand, stoppen beide.

**Technische Sicherungen (sofortiger Handelsstopp + ntfy):**
- Daten älter als 36 h oder Datenquelle uneinig (Binance vs. Hyperliquid > 3% Abweichung im Schlusskurs).
- Soll/Ist-Abweichung der Positionen > 5% des Kontowerts nach Ausführung.
- USDC-Kurs unter 0.98 → alles flat.
- Einzelorder max. 25% des Kontowerts; Tagesumsatz max. 100% des Kontowerts.
- Unit-Token (UBTC/UETH) weicht > 2% vom Referenzkurs ab → nicht kaufen, Alarm.

## 8. Roadmap

| Phase | Zeitraum | Inhalt |
|---|---|---|
| 0 | sofort | P0-Punkte 1, 4, 6, 7 aus Abschnitt 5; GDELT-Ergebnis prüfen |
| 1 | Wochen 1–4 | Spot-Liquidität UBTC/UETH prüfen, Trend-Backtest mit Spot-Kosten und Perp-Funding-Vergleich; `hl_exec.py` im Trockenlauf mit Kill-Switch nach 7.2; Verzögerungs-Sensitivität; P1-Punkte 9–11 |
| 2 | **erledigt 7.10., negativ** | (Ergebnis: siehe Abschnitt 0 und 4) Strategie-Bibliothek, dynamisches Universum, Querschnitts-Momentum mit überlebensfreien Daten, Meta-Allokator; alles in den Ledger |
| 3 | **zurueckgestellt** | (nur Beobachtungsliste/Alarm, keine automatische Anlage, siehe Abschnitt 0) Scout-Pipeline (Hyperliquid neue Perps/Spot, CoinGecko Trending/Kategorien, GoPlus, LLM-Zusammenfassung über Groq); Nachrichten-Feeds aus 6.5 in den Tagesbericht |
| 4 | ab ca. 1.12.2026, nur mit Patricks Freigabe | Wallet A klein live. Split nach 6.2 entfaellt vorerst (Explorer nach Phase 2 nicht gebaut); Wallet A traegt alles |

**Stand Phase 0 (7.10., Sonnet 5.5):**
- Ledger gebaut (`quant/ledger.py`, `data/quant/ledger.csv`, vom Tagesbericht geschrieben, Test `LedgerTests`). Auf dem Server verifiziert (7.10.).
- Dead-Man-Switch im Code (`HC_PING_URL` in `.env`, Ping am Ende von `quant_daily.sh`, `/fail` bei Fehlern). Patrick hat den Check angelegt und die URL gesetzt (7.10.).
- Haertung als `deploy/harden.sh` (ufw, fail2ban, Passwort-Login aus, GitHub-Host-Key aus api.github.com/meta, Logrotate). Von Patrick ausgefuehrt (7.10.).
- Offen: Update-Pfad (Punkt 1). Auto-Update bleibt in der Paper-Phase an und wird vor Live abgeschaltet; Umbau auf signierte Tags erst, wenn Live naht.
- GDELT: Server liefert auch mit Pause und Retry HTTP 429, Tageszeile leer. Abruf per `macro.gdelt_enabled: false` abgeschaltet (kein Backtest-Nutzen). Nachrichten kommen in Phase 3 ueber RSS.

**Stand Phase 1 (7.10.):**
- `quant/sensitivity.py` gebaut (7 vorab festgelegte Szenarien: Spot 10/20/40 bps, 1 Tag Verzoegerung, Perp mit echtem Binance-Funding). `trend_returns` hat neu `delay` und `funding`. Basis-Trend-Kosten `trend_bps: 10` entsprechen bereits Spot (7 bps Taker + Slippage). Lauf auf dem Server am 7.10. erledigt, Zahlen in Abschnitt 4; Punkt 3 und 5 aus Abschnitt 5 sind damit erledigt. Nicht abgedeckt: tatsaechliche Orderbuch-Tiefe UBTC/UETH, Abweichung des Spot-Preises zu Binance, Bridge-Risiko.
- Gebaut (Trockenlauf, nur Fakes getestet): `killswitch.py` (Stufen, Hysterese, klebriger Stopp, Ein-/Auszahlungen), `safety.py` (fail-closed), `hl_exec.py` (Zielwerte je Unit-Token, Rundung, Mindestwert, Teilorders unter 25%-Grenze, feste Client-Order-ID, Protokoll `orders_dryrun.csv`). Live-Modus gesperrt. Papierkonto `paper_account_A.json` (Fills zum Mid + 7 bps), laeuft taeglich im `quant_daily.sh` (Schritt "Trockenlauf Ausfuehrung"). Stopp verkauft auch bei Sicherungs-Verstoessen (Abweichung von "sofortiger Handelsstopp", weil der Kontowert aus dem Konto kommt); alle anderen Verstoesse blockieren.
- Nicht gebaut / ungeprueft: Carry-Ausfuehrung (Spot long + Perp short), Order-Senden ueber das offizielle SDK, Kontowert-Abruf (`spotClearinghouseState`, Format aus Doku, nicht live gesehen), Mindestorderwert 10 USD gegen Doku pruefen, Gebuehren-Tier, Unit-Bridge-Ein-/Auszahlung, Soll/Ist-Abgleich nach Ausfuehrung.
- P1 9-11 umgesetzt (7.10.): Carry mit Margin-Ausgleich (ab 0.5/lev Bewegung seit Referenz, Kosten) und Liquidation mit Margin-Verlust; Spill und Signal nutzen dieselben Walk-Forward-Carry-Parameter (`spill.carry_wf_parts`); `load_all` behaelt Tage mit fehlendem Funding (0) und loggt Luecken. Folge: Backtest-Zahlen koennen sich leicht aendern; Vorher-Werte stehen in Abschnitt 4 (Profil 40 +25.6%, Sharpe 1.16, MaxDD -18.5%; Spill +29.0%, MaxDD -22.9%). Neue Werte in Abschnitt 4. Offen: P1 12 (Funding-Timing). P1 13 (Korb-Rebalancing BTC/ETH kostenlos gerechnet): eigene Grobschaetzung unter 0.2 Pp pro Jahr, nicht gebaut.

## 9. Entscheidungen

**Entschieden am 7.10.2026** (Patrick hat die Wahl an Claude delegiert, Werte in `live_plan.yaml`):
1. Split: zwei Wallets, 70/30, Auslöser Explorer bestanden + 10'000 USDC; keine Kaskade; dritte Wallet erst ab 100'000 USDC auf zweiter Plattform (6.2). **Stand 7.10.: ruht**, weil der Explorer in Phase 2 negativ war; lebt nur wieder auf, wenn eine neue Strategie die Methode aus Abschnitt 0 Punkt 6 besteht.
2. Wallet B auf derselben Plattform (Hyperliquid), eigene Adresse und eigener Agent-Key (6.2).
3. Trend über Spot auf Hyperliquid (UBTC/UETH), nicht über Perps (7.1).
4. Kill-Switch gestuft -20/-30/-40% ab Höchststand (7.2).
5. LLM über Groq Free Tier, Fallback Gemini/Mistral; kein Anthropic-Key; kein X (kostenpflichtig) (6.5).
6. **Entschieden von Patrick am 7.10. (nachmittags):** Go/No-Go-Kriterien A bis F (STRATEGIE.md Abschnitt 8); Startbetrag 1'000 USDC echtes Geld nach bestandenem Papier-Test und Freigabe, mindestens 4 Wochen, Aufstockung nur auf Freigabe.

**Noch offen**
- Steuerberatung zur Frage gewerbsmässiger Handel (Schweiz) vor Live.
- Patrick legt einen Groq-Key an, sobald die Scout-Pipeline gebaut ist (Sonnet sagt Bescheid).
- Ob X gegen Bezahlung (grob 10–30 USD/Monat) gewünscht ist: Standard nein.

## 10. Feste Regeln für die nächste Session

- Nach jedem Push, der auf den Server soll: Patrick das naechste Tag nennen (Ablauf in Abschnitt 0, Aufgabe 0). Ohne Tag aendert sich auf dem Server nichts. Secrets (ntfy-Thema, Schluessel, `.env`) nie im Chat oder Screenshot zeigen lassen; Befehle so geben, dass sie nichts ausgeben.
- Nie Live-Orders ohne Patricks ausdrückliche Freigabe im Chat. Nie Schlüssel, Seeds oder `.env`-Inhalte im Chat oder im Repo.
- Jede neue Logik: kausal (Signal Tag i, Wirkung ab Tag i+1), Test auf Lookahead, Kosten x2, Zahl der getesteten Varianten im Bericht.
- Negative Ergebnisse klar melden und die Logik nicht trotzdem einbauen.
- Netzwerkcode nur mit Fakes testbar, echter Test auf dem Server. Das jedes Mal sagen.
- Kleine Commits, Tests grün vor jedem Push, Server holt um 00:50 UTC.

## 11. Quellen der Entscheidungen vom 7.10.

- Hyperliquid Docs, Fees: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees
- Hyperliquid Docs, Funding: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding
- Hyperliquid Docs, Sub-accounts: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/sub-accounts
- Unit Protocol Guide: https://hyperliquidguide.com/ecosystem/unit-protocol-guide
- Agent Wallets: https://dexly.trade/learn/hyperliquid-trading-bots
- MetaMask Swap-Gebühr 0.875%: https://cryptoslate.com/crypto-wallets/metamask-review/
- Gratis-LLM-Tarife: https://ianlpaterson.com/blog/free-llm-api-2026/
- X API Kosten: https://opentweet.io/how-to/x-api-pay-per-use-explained
- Truth-Social-Archiv: https://www.trumpstruth.org/faq
- CoinGecko keyless: https://docs.coingecko.com/docs/keyless-public-api
- Kaminski & Lo (2014), When do stop-loss rules stop losses?: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=968338
