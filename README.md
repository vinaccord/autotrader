# autotrader

Zwei Teile, nur Simulation, kein echtes Geld, keine Wallet-Schluessel im Paket.

1. **quant (empfohlen):** Funding-Carry plus volatilitaetsgesteuerte Trendfolge auf BTC und ETH, Walk-Forward-Lernen, adaptiver Allokator, taeglicher Server-Job.
2. **DEX-Paper-Agent (Experiment, nicht empfohlen):** Altcoin-Agent auf DEX-Daten mit Risiko-Limits, Sicherheitscheck und Strategie-Turnier. Hintergrund in `docs/STRATEGIE.md`.

Lies zuerst `docs/STRATEGIE.md`: Recherche, Annahmen, Grenzen und Go-Live-Kriterien.

## quant: erster Lauf (auf deinem Rechner oder Server)

```
pip install -r requirements.txt
python -m autotrader.quant.cli --config quant.yaml fetch       # Daten laden (Binance, ca. 1 Minute)
python -m autotrader.quant.cli --config quant.yaml backtest    # Out-of-Sample-Auswertung
python -m autotrader.quant.cli --config quant.yaml signal      # Zielzustand heute
```

Der Bericht stellt gegenueber: adaptiv kombiniert, Carry und Trend je adaptiv und fest, fest 50/50, Buy-and-Hold, dazu Jahreswerte, gewaehlte Parameter und Gewichte. Schick mir die Ausgabe, dann werte ich sie mit dir aus.

Die Datenanbindung (Binance, Hyperliquid) ist nach Doku geschrieben und nicht live getestet. Blockiert eine Quelle, kannst du `source` in `quant.yaml` wechseln oder eigene CSV-Dateien im Cache-Format ablegen (`data/quant/<source>_prices_BTC.csv` mit `ts,open,high,low,close,volume`, `<source>_funding_BTC.csv` mit `ts,rate`).

## Server (Ubuntu-VPS)

Metanet-Webhosting (METAhost) taugt nicht, es fehlen Python-Dauerprozesse und Root. Guenstig: Infomaniak VPS Lite ab CHF 2.70 pro Monat (Schweiz, Jahresvertrag) oder Hetzner CX23 ab EUR 5.49.

```
scp autotrader.zip root@DEINE_SERVER_IP:/root/
ssh root@DEINE_SERVER_IP
apt-get install -y unzip && unzip autotrader.zip && cd autotrader
bash deploy/setup.sh
tail -n 80 /opt/autotrader/data/quant/daily.log
```

`setup.sh` legt einen eigenen Benutzer an und aktiviert einen systemd-Timer, der taeglich um 01:05 UTC Daten holt, den Backtest rechnet und das Signal ins Log schreibt. Die Skripte sind nicht auf einem echten Server getestet.

Makro (Beobachtung): `python -m autotrader.quant.macro --config quant_40.yaml fetch` laedt Fear & Greed und loggt GDELT-Tonalitaet, `... backtest` rechnet zwei feste Regeln gegen den Trend-Teil. Positionen aendert das nicht.

Tests: `python -m unittest discover -s tests` (57 Tests, laufen ohne Netzwerk).

## DEX-Paper-Agent (Experiment)

```
python -m autotrader.cli init
python -m autotrader.cli run --once
python -m autotrader.cli status
python -m autotrader.cli report
```

Weitere Befehle: `approvals`, `approve ID`, `reject ID`, `kill`, `resume`, `unpause STRATEGIE`. Konfiguration in `config.yaml`. Er wird vom Setup nicht aktiviert (`systemctl enable --now autotrader` falls gewuenscht).

## Live-Modus

Existiert nicht. Weder der DEX-Agent noch quant fuehren echte Orders aus. Voraussetzungen und Wallet-Konzept (Hyperliquid mit MetaMask-Login und Agent-Key ohne Abhebe-Recht) stehen in `docs/STRATEGIE.md`, Abschnitte 5 und 8.

## Grenzen

- Backtest-Annahmen: Ausfuehrung zum Schlusskurs, pauschale Kosten, keine Basis-Schwankung, keine Liquidationsverluste. Siehe `docs/STRATEGIE.md`, Abschnitt 4.
- Kostenannahmen in `quant.yaml` vor Nutzung mit der aktuellen Gebuehrentabelle abgleichen.
- Keine Anlageberatung.
