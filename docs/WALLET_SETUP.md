# Wallet und Hyperliquid einrichten (Anfang November), Stand 12.10.2026

Dieses Dokument ist die Anleitung fuer die Einrichtung, der Test mit Kleinstbetrag und den Start. Es ersetzt keine Freigabe: **Echte Orders gibt es nur nach Patricks ausdruecklicher Freigabe im Chat**, und der Start mit 1'000 USDC fruehestens nach der Entscheidung ab 1.12.2026 (Kriterien A bis F, `docs/STRATEGIE.md` Abschnitt 8).

## Grundregeln
- Seed-Phrase, privater Schluessel, Agent-Key, Inhalt von `.env` und der ntfy-Name erscheinen nie im Chat, in Screenshots oder im Repo. Befehle in dieser Anleitung geben nichts davon aus.
- Fenster angeben: **PC** = Windows-cmd oder Browser auf Patricks PC, **SSH** = Fenster `ubuntu@...` auf dem Server.
- Hyperliquid-Adresse nur ueber die offizielle Doku (hyperliquid.gitbook.io) oder ein selbst gesetztes Lesezeichen oeffnen, nie ueber Suchanzeigen, Nachrichten oder Links von Dritten. Das ist der haeufigste Weg, Wallets zu leeren.
- Oberflaechen aendern sich. Weicht ein Schritt ab, Screenshot an Claude (ohne Seeds, Schluessel, Adressen von Dritten).

## Phase A, ohne Geld (Anfang November)
1. **Neue Wallet nur fuer dieses Projekt** (EVM-Adresse, nicht die private Haupt-Wallet). Empfehlung: Hardware-Wallet, wenn vorhanden; sonst eine Software-Wallet in einem eigenen Browserprofil. Die Seed-Phrase auf Papier schreiben, zwei Kopien an getrennten Orten, nie fotografieren oder abtippen ausser bei der Wiederherstellung.
2. Wallet mit der offiziellen Hyperliquid-App verbinden (noch keine Einzahlung). Kontomodus ansehen (Standard, `unifiedAccount` oder `portfolioMargin`) und notieren, welcher aktiv ist: er entscheidet, ob Spot- und Perp-Guthaben getrennt sind.
3. **Agent-Wallet (API-Wallet) anlegen**: In der App unter API einen Agenten erzeugen und mit der Haupt-Wallet freigeben. Der Agent darf handeln, aber nicht abheben. Gueltigkeit (Ablaufdatum) in der Oberflaeche pruefen und notieren, damit der Key nicht mitten im Betrieb ablaeuft. Der private Agent-Key wird nur einmal angezeigt.
4. **Agent-Key in die `.env` auf dem Server, nur von Patrick** (SSH). Die Eingabe bleibt unsichtbar und landet nicht im Verlauf:
   ```
   read -rsp "Agent-Key: " K; echo; echo "HL_AGENT_KEY=$K" | sudo tee -a /opt/autotrader/.env >/dev/null; unset K
   read -rp "Hauptadresse (0x...): " A; echo "HL_ACCOUNT_ADDRESS=$A" | sudo tee -a /opt/autotrader/.env >/dev/null; unset A
   sudo grep -c -E '^HL_(AGENT_KEY|ACCOUNT_ADDRESS)=0x' /opt/autotrader/.env
   ```
   Die letzte Zeile muss `2` ausgeben. Danach die Zwischenablage leeren (neuen Text kopieren). `.env` gehoert `autotrader`, Rechte 600 (`check_f.sh` prueft das). Der Agent-Key ist nie der Schluessel der Hauptadresse: der Sender weigert sich, wenn beide dieselbe Adresse ergeben.
5. **Lesepruefung mit der echten Adresse, ohne Geld** (SSH): `sudo -u autotrader bash -c 'cd /opt/autotrader && set -a && . ./.env && set +a && venv/bin/python -m autotrader.quant.hl_sdk_check --address "$HL_ACCOUNT_ADDRESS"'` (die `.env` darf nur `autotrader` lesen, darum laeuft alles in dessen Shell). Erwartet: leeres Spot-Konto, kein Fehler im Parser. Die Ausgabe zeigt weder Key noch Adresse.

## Phase B, Einzahlung und Umbuchung (nur nach ausdruecklicher Freigabe)
Betrag fuer den Test: **100 USDC** (siehe Bauteile unten, bei 40 USDC wuerden Teilorders unter dem Mindestwert liegen).
1. USDC (native, Netz **Arbitrum One**, nicht USDC.e, nicht ein anderes Netz) auf die neue Wallet senden, dazu wenige USD Ether auf Arbitrum fuer Gebuehren. Erst 10 USDC als Wegtest, Eingang abwarten, dann den Rest.
2. Einzahlen **nur ueber die Deposit-Funktion der offiziellen App**, nie eine Bridge-Adresse von Hand eintippen. Mindesteinzahlung 5 USDC, darunter geht der Betrag verloren (Doku, `for-developers/api/usdc.md`).
3. Ankunft pruefen. Das Guthaben liegt vermutlich im **Perp-Konto**; der Bot liest nur das Spot-Konto und blockiert, wenn mehr als 5 USD im Perp-Konto liegen. In der App von Perps nach Spot umbuchen (Transfer), oder im Kontomodus klaeren, ob das noetig ist.
4. Erneut Phase A, Punkt 5: Spot-Konto zeigt jetzt USDC 100, Perp-Konto 0. Mit diesem Screenshot ist der Teil von Kriterium E "spotClearinghouseState mit echter Adresse" erledigt.
5. **Kill-Switch:** Vor dem allerersten Live-Lauf existiert kein Zustand, er entsteht mit dem ersten Lauf (Hoechststand = Kontowert). Eine Einzahlung danach erst verbuchen, dann ueberweisen: `python -m autotrader.quant.killswitch flow --config quant_40.yaml --mode live --amount 900 --confirm`.

## Phase C, Test mit Kleinstbetrag (eigene, ausdrueckliche Freigabe, nur nach Kriterium F)
Ziel: die ungeprueften Teile von Kriterium E gegen die echte API bestaetigen. Pruefliste:
- **Antwortformat** von `exchange.order`: Status `filled` mit `totalSz`, `avgPx`, `oid` im Protokoll `orders_live.csv`, `hl_sender.parse_order_response` versteht es.
- **Doppelsende-Schutz:** `orderStatus` mit unbekannter und mit bekannter `cloid` liefert, was `already_sent` erwartet.
- **Tickgroesse und Rundung:** Limitpreis (5 signifikante Stellen) wird akzeptiert, Mengen-Dezimalstellen stimmen (UBTC 5, UETH 4).
- **Mindestorder 10 USDC:** Doku nennt "Order must have minimum value of 10 {quote_token}" fuer Spot. Pruefen, ob eine Order unter 10 USDC abgelehnt wird, und ob ein Verkauf einer Restposition unter 10 USDC moeglich ist (die Doku sagt dazu nichts). Der Bot ueberspringt Orders unter 10 USDC; ein Rest unter 10 USDC bliebe liegen.
- **Soll/Ist-Abgleich** nach der Ausfuehrung (`max_position_mismatch` 5%) meldet nichts.
- **Kill-Switch** wird mit echtem Kontowert angelegt (`killswitch status --mode live`).
Ablauf: Claude setzt in einem eigenen, signierten Release `live_plan.yaml` auf `mode: live` und `armed_until` auf den Testtag, Patrick signiert und spielt es ein, startet **von Hand** (SSH): `sudo -u autotrader bash -c 'cd /opt/autotrader && set -a && . ./.env && set +a && venv/bin/python -m autotrader.quant.hl_live --config quant_40.yaml --plan live_plan.yaml --confirm-real-money'`. Danach Release zurueck auf `dry-run`, `armed_until: null`. Protokoll `orders_live.csv` und `tax_export` (`docs/STEUER_FRAGEN.md`) sichern.

## Phase D, Start mit 1'000 USDC (ab 1.12.2026, nur mit Freigabe)
Aufstocken von 100 auf 1'000 USDC: Kill-Switch verbuchen (Phase B Punkt 5, `--amount 900`), dann einzahlen und nach Spot umbuchen. Danach mindestens 4 Wochen auf diesem Betrag, Aufstockung nur auf ausdrueckliche Freigabe (`live_plan.yaml`).

## Bauteile vor Phase C (Claude, noch offen, in HANDOFF Abschnitt 0)
1. **`mode: live` bricht den Tageslauf.** `hl_exec.py` ohne Sender verweigert sich bei `mode: live` (Schritt "Trockenlauf Ausfuehrung" im Timer schlaegt fehl und loest einen Alarm aus). Loesung vor dem Test: zusaetzliche Datei oder Ueberlagerung nur fuer den Live-Lauf, `live_plan.yaml` bleibt `dry-run`. Wie der Live-Lauf spaeter im Timer laeuft, ist noch nicht gebaut.
2. **Teilorders unter dem Mindestwert.** `plan_orders` teilt grosse Orders in Stuecke von hoechstens 0.9 x 25% des Kontowerts. Ein letztes Stueck kann unter 10 USDC fallen (z.B. 225 + 2 bei einem Delta von 227) und wuerde abgelehnt, der Sender bricht dann ab und alarmiert. Loesung: gleichmaessig teilen. Bei Kontowerten unter etwa 45 USDC liegt schon das Hoechststueck unter 10 USDC, darum 100 USDC fuer den Test. Das aendert die Orderaufteilung im Papierbetrieb (Menge und Strategie bleiben gleich); Entscheid, ob schon waehrend der Papierphase, liegt bei Patrick.
3. **Kontomodus pruefen** (Phase A Punkt 2) und bei `unifiedAccount` klaeren, ob `spotClearinghouseState` das Guthaben so zeigt, wie `fetch_account` es liest.
