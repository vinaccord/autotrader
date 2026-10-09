# Fragen an den Steuerberater (Schweiz, Kanton Zuerich), vor dem ersten echten Franken

Stand 9.10.2026. Das sind Fragen, keine Antworten. Claude ist kein Steuerberater. Mitbringen: `tax_export` (Handelsliste als CSV, siehe unten), Kurzbeschreibung der Strategie (`docs/STRATEGIE.md`), Plattform (Hyperliquid, Wallet bei Patrick, kein Konto bei einer Schweizer Bank oder Boerse).

## Einordnung
1. Bleibt der Handel privates Vermoegen (steuerfreier Kapitalgewinn) oder droht die Einstufung als gewerbsmaessiger Wertschriftenhandel? Welche Kriterien zaehlen bei einem automatisierten System mit taeglichem Rebalancing (Haltedauer, Umsatz, Fremdfinanzierung, Anteil am Einkommen, Zusammenhang mit Berufstaetigkeit)?
2. Spielt der Hebel eine Rolle (Perp-Short im Carry, Hebel 2, nicht gebaut) fuer die Einstufung? Gelten Derivate und Perpetual Futures anders als Spot?
3. Sind die Erträge aus Funding-Zahlungen (Carry) Einkommen, auch bei privatem Vermoegen? Wie werden sie verbucht?

## Bewertung und Meldung
4. Wie wird der Bestand am 31.12. bewertet (Kursliste ESTV, Umrechnung USDC/USD in CHF) und wo erscheint er in der Steuererklaerung (Wertschriftenverzeichnis, Vermoegen)? Zaehlt USDC als Kryptowaehrung oder wie ein Guthaben?
5. Wie sind UBTC/UETH (Unit-Token auf Hyperliquid, gedeckt durch BTC/ETH bei Unit) einzuordnen: wie BTC/ETH oder als eigenes Wertrecht?
6. Gibt es eine Meldepflicht fuer Konten bei auslaendischen Plattformen oder Wallets (z.B. ab einem Betrag)?

## Buchhaltung
7. Welche Aufzeichnungen genuegen: nur die Handelsliste (Zeit, Token, Menge, Kurs, Gebuehr) oder zusaetzlich Ein- und Auszahlungen und Kurse in CHF je Tag?
8. Welche Kursquelle fuer die Umrechnung in CHF ist anerkannt (ESTV-Kursliste, Tageskurs einer Boerse)?
9. Gebuehren und Gas (Arbitrum bei Ein- und Auszahlung): abziehbar, und wann?

## Weiteres
10. Wirkt sich der Verlustfall (Kill-Switch loest bei -40% aus) steuerlich aus? Verluste im privaten Vermoegen sind meist nicht abziehbar: stimmt das hier?
11. Was aendert sich, wenn der Betrag spaeter ueber 10'000 USDC steigt oder die Aktivitaet ueber eine Firma (Stuessi Labs) laufen soll?

## Handelsliste erzeugen
Nach dem ersten echten Trade, im SSH-Fenster auf dem Server:
`cd /opt/autotrader && sudo -u autotrader venv/bin/python -m autotrader.quant.tax_export --config quant_40.yaml`
Die Datei liegt dann unter `data/quant/tax_trades_live.csv` (Papier: `--source dryrun`). CHF-Spalten bleiben leer, Gebuehren sind geschaetzt (7 bps), Funding und Einzahlungen sind nicht enthalten.
