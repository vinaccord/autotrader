# Briefing für die nächste Session (Stand 7. Oktober 2026)

Dieses Dokument ist die Übergabe an das Modell, das die Arbeit fortsetzt. Erst ganz lesen, dann `docs/STRATEGIE.md`, dann den Code.

---

## 1. Auftraggeber und Arbeitsweise

- **Patrick Stüssi**, Richterswil (ZH). Kommunikation auf Deutsch, präzise, Empfehlung zuerst, dann Begründung. Kurze Absätze, Aufzählungen. Kein Eszett, immer "ss". Keine Floskeln, keine typischen KI-Schreibmuster (aufgeblasene Adjektive, "nicht nur … sondern", künstliche Dreiergruppen, Schlussfloskeln).
- Patrick will Ehrlichkeit über Belege. Wenn etwas geraten ist, so sagen. Wenn ein Test negativ ist, so sagen.
- **Ziel des Projekts:** autonomer Krypto-Trading-Agent mit eigener Wallet, zweistellige Jahresrendite, Verlusttoleranz bis 40% ("Spielgeld, langfristig").
- **Ablauf der Zusammenarbeit:**
  - Code liegt im privaten Repo `vinaccord/autotrader`, Branch `main`. Die Session hat Push-Recht.
  - Der Server holt den Code täglich um 00:50 UTC (`quant-update.timer`). Sofort: Patrick führt `sudo systemctl start quant-update.service` aus.
  - Patrick führt Befehle per SSH aus und schickt Screenshots. Befehle immer vollständig und kopierbar geben, mit Hinweis, in welchem Fenster (Windows-cmd oder SSH `ubuntu@...`). Er hat sich mehrmals im Fenster vertan.
  - Die Claude-Sandbox erreicht Binance, Hyperliquid, GDELT, alternative.me **nicht**. Alles Netzwerk-Abhängige wird mit Fakes getestet und erst auf dem Server echt geprüft. Das jedes Mal sagen.
  - Tests: `python3 -m unittest discover -s tests` (72 Tests, alle grün am 7.10.).
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
| GDELT-Abruf | HTTP 429 vom Server, Korrektur (Pause 12 s, Retry) seit 6.10. aktiv, Ergebnis offen | prüfen |

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
| 2 | Wochen 2–6 | Strategie-Bibliothek, dynamisches Universum, Querschnitts-Momentum mit überlebensfreien Daten, Meta-Allokator; alles in den Ledger |
| 3 | Wochen 4–8 | Scout-Pipeline (Hyperliquid neue Perps/Spot, CoinGecko Trending/Kategorien, GoPlus, LLM-Zusammenfassung über Groq); Nachrichten-Feeds aus 6.5 in den Tagesbericht |
| 4 | ab ca. 1.12.2026, nur mit Patricks Freigabe | Wallet A klein live; Split nach 6.2, sobald Explorer bestanden hat und 10'000 USDC erreicht sind |

**Stand Phase 0 (7.10., Sonnet 5.5):**
- Ledger gebaut (`quant/ledger.py`, `data/quant/ledger.csv`, vom Tagesbericht geschrieben, Test `LedgerTests`). Offen: auf dem Server verifizieren, nach dem ersten Lauf nach Update.
- Dead-Man-Switch im Code (`HC_PING_URL` in `.env`, Ping am Ende von `quant_daily.sh`, `/fail` bei Fehlern). Offen: Patrick legt Healthchecks-Check an (Periode 1 Tag, Grace 12 h) und setzt die URL.
- Haertung als `deploy/harden.sh` (ufw, fail2ban, Passwort-Login aus, GitHub-Host-Key aus api.github.com/meta, Logrotate). Offen: Patrick fuehrt es auf dem Server aus.
- Offen: Update-Pfad (Punkt 1). Auto-Update bleibt in der Paper-Phase an und wird vor Live abgeschaltet; Umbau auf signierte Tags erst, wenn Live naht.
- GDELT-Ergebnis: noch nicht geprueft (Server-Zugriff noetig).

## 9. Entscheidungen

**Entschieden am 7.10.2026** (Patrick hat die Wahl an Claude delegiert, Werte in `live_plan.yaml`):
1. Split: zwei Wallets, 70/30, Auslöser Explorer bestanden + 10'000 USDC; keine Kaskade; dritte Wallet erst ab 100'000 USDC auf zweiter Plattform (6.2).
2. Wallet B auf derselben Plattform (Hyperliquid), eigene Adresse und eigener Agent-Key (6.2).
3. Trend über Spot auf Hyperliquid (UBTC/UETH), nicht über Perps (7.1).
4. Kill-Switch gestuft -20/-30/-40% ab Höchststand (7.2).
5. LLM über Groq Free Tier, Fallback Gemini/Mistral; kein Anthropic-Key; kein X (kostenpflichtig) (6.5).

**Noch offen**
- Steuerberatung zur Frage gewerbsmässiger Handel (Schweiz) vor Live.
- Patrick legt einen Groq-Key an, sobald die Scout-Pipeline gebaut ist (Sonnet sagt Bescheid).
- Ob X gegen Bezahlung (grob 10–30 USD/Monat) gewünscht ist: Standard nein.

## 10. Feste Regeln für die nächste Session

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
