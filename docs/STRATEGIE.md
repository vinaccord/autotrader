# Strategie, Recherche und Entscheidungen

Stand: 6. Oktober 2026. Keine Anlageberatung. Eine Garantie auf Gewinn gibt es nicht und die Recherche liefert auch keine.

## 1. Warum weg von DEX-Altcoins

- Studie zu 17'194 neuen Uniswap-V2-Tokens (Okt bis Dez 2024): 88% Honeypots, Scheingewinne durch nicht verkaufbare Tokens, 68% der Honeypots mit Sandwich-Angriffen. Realisierbare Gewinne fuer Kleinanleger sind kaum belegt.
- Fuer Altcoin-Momentum auf DEXs habe ich keine belastbare Evidenz gefunden. Der bisherige Agent (`autotrader/agent.py`) bleibt als Experiment im Paket, wird aber nicht empfohlen.

## 2. Zwei Ertragsquellen mit nachvollziehbarer Logik

### A. Funding-Carry (delta-neutral)
Spot long, Perpetual short auf BTC und ETH. Wenn der Perp-Kurs ueber Spot liegt, zahlen Longs an Shorts. Hyperliquid zahlt Funding stuendlich, die Zinskomponente liegt laut Doku bei 0.01% pro 8 Stunden (ca. 11% p.a.), dazu kommt die Praemie.

Evidenz und Grenzen:
- Springer-Studie (CEX-DEX-Basis-Trade): rund 103% Netto-Rendite p.a. sind modellbasiert unter synthetischen Annahmen, nicht realisiert. Gas ca. 4.6% und Slippage ca. 2.9% pro Jahr fressen Ertrag. Gegenparteirisiko (FTX, Nov 2022) schadete mehr als Kursstuerze. Empfohlener Hebel: hoechstens 2 bis 3x.
- Funding kann negativ werden. Dann zahlt man. Die Strategie steigt bei tiefem Trailing-Funding aus (Hysterese).
- Das Short-Bein kann bei starken Preisspruengen liquidiert werden, bevor man nachschiesst. Der Backtest zaehlt solche Tage (`liq_flags`), preist sie aber nicht ein.

### B. Trendfolge mit Volatilitaetssteuerung (nur Long/Flat)
BTC und ETH sind investiert, solange der Kurs ueber dem gleitenden Durchschnitt liegt. Die Positionsgroesse richtet sich nach Ziel-Volatilitaet.

Evidenz und Grenzen:
- Zeitreihen-Momentum in Krypto ist akademisch belegt (Liu/Tsyvinski, 1 bis 8 Wochen), aber die Datenbasis umfasst nur etwa ein Jahrzehnt.
- Ein Praxistest (BTC, ETH, SOL, 2017 bis Juni 2025): reine Volatilitaetssteuerung ohne Richtungsmeinung senkte den maximalen Verlust von 84% auf 17%. Der Trend-Filter trug weniger bei als die Positionsgroesse. Ein einfacher 200-Tage-Filter auf BTC war ebenbuertig zu komplexeren Ensembles.
- Ein vorregistriertes GitHub-Experiment: Trendstrategie mit CAGR 28% gegen 44% bei Buy-and-Hold, Drawdown -34% gegen -77%, Sharpe 1.00 gegen 0.91. Also weniger Risiko, aber nicht mehr Rendite.
- Das arXiv-Paper "AdaptiveTrend" meldet Sharpe 2.41 (2022 bis 2024, Long/Short auf Binance-Perpetuals). Das ist ein Autoren-Backtest. Ich habe es nicht uebernommen, weil es Shorts auf zentralen Perps braucht und die Zahl einer einzelnen Studie entstammt.

Ehrliche Erwartung: Das System soll Risiko senken und laufende Carry-Ertraege sammeln. Es ist keine Garantie, den Markt zu schlagen.

## 3. Was "lernen und sich anpassen" hier bedeutet

Kein LLM entscheidet ueber Trades. Gelernt wird nach Regeln, die Overfitting begrenzen:
- Walk-Forward: Jede Strategie laeuft mit allen Parameter-Varianten parallel. Alle 30 Tage waehlt das System die Variante mit dem besten Sharpe der letzten 365 Tage und folgt ihr danach Out-of-Sample. Gemeldet werden nur Out-of-Sample-Tage.
- Parameterwechsel kosten pauschal 5 Basispunkte.
- Allokator: Gewichtung zwischen Carry und Trend nach inverser Volatilitaet, leicht nach trailing Sharpe geneigt, Grenzen 10% bis 90%, Neuberechnung alle 30 Tage.
- Der Bericht stellt adaptiv gegen feste Standardwerte, gegen 50/50 und gegen Buy-and-Hold. Wenn adaptiv nicht besser ist als fest, ist die Anpassung kein Gewinn und sollte abgeschaltet werden.
- Je mehr Varianten getestet werden, desto eher ist ein gutes Ergebnis Zufall. Die Zahl der Varianten steht im Bericht.
- Tests pruefen, dass kein Signal Zukunftsdaten nutzt (Kausalitaetstests fuer Carry, Trend, Walk-Forward und Allokator).

## 4. Was der Backtest nicht abbildet

Ausfuehrung zum Schlusskurs, pauschale Kosten, keine Teilfuellungen, keine Basis-Schwankung zwischen Spot und Perp, keine Liquidationsverluste, kein Plattformausfall, kein Kapitaltransfer-Aufwand. Funding stammt bei `source: binance` als Proxy von Binance, nicht von Hyperliquid. Ein sehr hoher Carry-Sharpe ist darum ein Warnsignal und kein Beleg.

## 5. Wallet-Architektur fuer die spaetere Live-Phase (noch nicht gebaut)

- Hyperliquid: Anmeldung mit deiner MetaMask-Wallet, kein KYC. Fuer den Bot legst du in Hyperliquid einen API-/Agent-Key an. Dieser Key kann handeln, aber laut Guides nicht abheben. Ein gestohlener Bot-Key koennte also Trades ausloesen, aber die Gelder nicht wegschicken. Abheben geht nur mit deiner Hauptwallet.
- Alternative: MetaMask Agent Wallet (Early Access). Laut Produktseite on-chain Limits (Tageslimit, erlaubte Protokolle), Hyperliquid unterstuetzt. Verfuegbarkeit und Konditionen sind unklar.
- Einzahlung ueber USDC auf Arbitrum.
- Offene Frage: Spot-Bein des Carry. Entweder Hyperliquid-Spot (Verfuegbarkeit von BTC/ETH-Spot muss geprueft werden) oder eine andere Boerse. Davon haengt ab, ob alles auf einer Plattform bleibt.
- Risiken: Smart-Contract- und Plattformrisiko, Bridge-Risiko, Liquidation des Short-Beins. Hebel hoechstens 2.

## 6. Conway Automaton, nochmals analysiert

- Architektur: ReAct-Schleife, 57 Tools in 10 Kategorien, 7 Sicherheitsebenen (Konstitution, Policy-Engine vor jeder Aktion, Injection-Erkennung, Pfadschutz, Befehlssicherheit, Ausgabenlimits, Autoritaetsstufen), SQLite mit 22 Tabellen, Heartbeat-Scheduler, Kinder-Agenten (Standard max. 3).
- Wallet: Schluessel in `~/.automaton/wallet.json` (Rechte 0600), laut Dokument nicht ueber Tools erreichbar.
- Trading: Es gibt keine Trading-Tools. Finanzfunktionen sind Credits, USDC-Saldo, x402-Zahlung und Transfers. Wie der Agent Geld verdient, bleibt dem LLM ueberlassen. In den Issues (138 offen) dominieren Anmeldefehler. Belege fuer echte Einnahmen habe ich nicht gefunden.
- Abhaengigkeit: stark an Conway Cloud gebunden.
- Uebernehmenswert: Policy-Engine vor Ausfuehrung, Risiko-Labels pro Tool, Injection-Pruefung externer Eingaben, Audit-Log, Idle- und Loop-Erkennung, Treasury-Limits.
- Nicht uebernehmen: Selbstmodifikation, Replikation und "stirbt ohne Einnahmen". Bei Geld im Spiel setzt der Todesdruck Anreize zu Risiko.

## 7. Hosting

| Option | Preis | Hinweis |
|---|---|---|
| Infomaniak VPS Lite 1 vCPU, 2 GB | CHF 2.70 pro Monat | Schweizer Standort, Root, Jahresvertrag. Reicht fuer den taeglichen Job |
| Infomaniak VPS Lite 2 vCPU, 2 GB | CHF 5.40 pro Monat | mehr Reserve |
| Hetzner CX23 2 vCPU, 4 GB | EUR 5.49 pro Monat | Deutschland oder Finnland, stuendliche Abrechnung. Preise stiegen im Juni 2026 |
| Metanet VPS | ab CHF 24 pro Monat | Root, deutlich teurer |
| Metanet Webhosting (dein Paket) | | PHP/MariaDB, keine Python-Dauerprozesse. Nicht geeignet |

Zusatztool nicht noetig: Ein systemd-Timer (im Paket) startet den Job taeglich. Optional ein externer Dead-Man-Switch wie Healthchecks.io, der meldet, wenn der Job ausbleibt (nicht enthalten).

## 8. Go-Live-Kriterien (von Patrick bestaetigt am 7.10.2026)

Stand ersetzt die frueheren Vorschlaege (adaptives Profil, Hebel 2, Kill-Switch -15%), die nicht mehr gelten. Die Kriterien sind vorab festgelegt und werden waehrend des Papierbetriebs nicht angepasst. Entscheid frueh. 1.12.2026, nur mit Patricks ausdruecklicher Freigabe im Chat.

Geprueft wird der Betrieb, nicht die Rendite: 8 Wochen Papier sagen statistisch nichts ueber die Rendite, und BTC/ETH kann ohne jeden Systemfehler schlecht laufen.

Muss-Kriterien (alle erfuellt, sonst kein Live):
- **A Betrieb lueckenlos.** Von 56 Tagen ab 6.10. fehlt hoechstens 1 Tageslauf (Healthchecks, daily.log), kein Ausfall laenger als 48 h, Ledger ohne Datenluecke.
- **B Papier gleich Backtest.** Papierkonto haelt taeglich dieselben Positionen wie der Backtest derselben Tage, Abweichung hoechstens 0.05 Anteil Kontowert; hoechstens 3 Tage verletzt, jeweils erklaert.
- **C Kosten wie angenommen.** Gebuchte Papierkosten liegen innerhalb 2x der Backtest-Kosten (trend_bps 10).
- **D Schutz getestet.** Kill-Switch (warn, brake, stop) und mindestens 3 Sicherungen mit Testdaten ausgeloest und im Repo dokumentiert.
- **E Ausfuehrung geprueft.** Order-Senden ueber das offizielle SDK (Version festgenagelt), Soll/Ist-Abgleich, spotClearinghouseState mit echter Adresse und Mindestorderwert gegen die Doku verifiziert. Test mit Kleinstbetrag erst nach F und nach Patricks Freigabe.
- **F Server gehaertet.** Auto-Update als root abgeschaltet, Updates nur ueber signierte Tags; ntfy-Thema nicht erratbar und ohne Positionsdaten. Vor dem Agent-Key auf dem Server. Pruefung: `deploy/check_f.sh`.

Warnsignale (kein Muss-Kriterium): Papierrendite der Periode weicht um mehr als 10 Prozentpunkte vom Backtest derselben Tage ab (Ursache klaeren vor Live). Papier-Drawdown ueber 30% ist Anlass fuer Pause und Analyse. Ein Verlust allein schliesst Live nicht aus.

Start live (`live_plan.yaml`): 1'000 USDC echtes Geld, mindestens 4 Wochen auf diesem Betrag, Aufstockung nur auf ausdrueckliche Freigabe. Trend ueber Spot (Hebel 1). Kill-Switch warn -20%, brake -30%, stop -40% ab Hoechststand, zusaetzlich stop bei Kontowert unter 60% der Einzahlungen. Carry-Teil erst, wenn die Carry-Ausfuehrung gebaut und getestet ist.

## 9. Recht und Steuern Schweiz (Hinweise, keine Beratung)

- Gehebelte Derivate auf einer nicht regulierten Plattform: Du traegst die Verantwortung, dass das fuer dich zulaessig ist. Hyperliquid sperrt unter anderem die USA, die Schweiz steht nicht auf der Sperrliste. VPN-Umgehung verstoesst gegen die Bedingungen.
- Hochfrequenter oder systematischer Handel kann als gewerbsmaessig gelten, dann sind Gewinne steuerbar. Vor dem Start mit einer Steuerberatung klaeren.

## Quellen

- Hyperliquid Docs: Funding, Info-Endpunkte (gitbook)
- Springer: CEX-DEX Funding Rate Arbitrage as a Basis Trade (2026)
- arXiv 2602.11708: Systematic Trend-Following with Adaptive Portfolio Construction
- summitward.com: Does Trend Following Work on Crypto?
- GitHub creditcomebackclub/crypto-trend-research
- arXiv 2502.10512: Price manipulation schemes of new crypto-tokens in decentralized exchanges
- Conway-Research/automaton: README, ARCHITECTURE.md, Issues
- MetaMask: Agent Wallet und "Self-custody in the era of AI agents"
- Infomaniak VPS Lite, Hetzner Preisuebersicht (costgoat), Metanet Webhosting
