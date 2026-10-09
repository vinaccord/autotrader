# Vorab festgelegter Test: Carry mit Hyperliquid-Funding (festgelegt 9.10.2026, vor dem ersten Lauf)

Frage: Hat der Carry (Spot long, Perp short) nach Kosten einen brauchbaren Ertrag, wenn das Signal und der Ertrag aus dem Funding von Hyperliquid kommen, also dem Ort, an dem er ausgefuehrt wuerde? Bisher stammt der Backtest aus Binance-Funding, das auf Hyperliquid etwa halb so hoch ausfaellt (Ergebnis P1 12).

Werkzeug: `python -m autotrader.quant.carry_hl --config quant_40.yaml` (liest nur Cache-Dateien, optional `--fetch` holt die HL-Funding-Historie nach).

## Daten
Volle Hyperliquid-Tage (24 stuendliche Eintraege) ab Beginn der HL-Historie (ca. Juni 2023) bis gestern, BTC und ETH, Preise aus dem bestehenden Cache. Fehlt ein HL-Tag zwischen erstem und letztem Tag, zaehlt sein Funding 0 (konservativ), die Zahl wird gemeldet.

## Laeufe (6, nicht mehr)
Alle Laeufe: Hebel und Parameterraster aus `quant_40.yaml`, Gitter 3 x 3 x 2 = 18 Kandidaten, Walk-Forward 365 Tage Training, 30 Tage Schritt, Wechselkosten 5 bps. Alle Kennzahlen gelten fuer den Zeitraum nach den ersten 365 Tagen (gleiches Fenster fuer alle Laeufe).
1. V0 Kontrolle: Binance-Funding, Standardparameter (Lookback 14, Einstieg 12%, Ausstieg 4%), Einstiegstag voll.
2. V1 HL-Funding, Standardparameter, Einstiegstag 23/24 (der Job laeuft rund 65 Minuten nach 00:00 UTC).
3. V1x2 wie V1 mit doppelten Kosten (Gebuehren und Slippage).
4. V2 HL-Funding, Walk-Forward ueber das Gitter, Einstiegstag 23/24.
5. V2x2 wie V2 mit doppelten Kosten. **Diese Variante entscheidet.**
6. V3 Kontrolle: Binance-Funding, Walk-Forward, Einstiegstag voll.

## Entscheidungsregel (alle vier muessen erfuellt sein, auf V2x2)
1. Gesamtertrag im Fenster > 0 und CAGR >= 4% (Schwelle ungefaehr auf dem Niveau einer risikoarmen USDC-Verzinsung; grobe Annahme, nicht gemessen).
2. Maximaler Verlust vom Hoechststand nicht schlechter als -10%.
3. Beide zeitlichen Haelften des Fensters haben einen Gesamtertrag > 0.
4. V1x2 hat keine Liquidation des Short-Beins (`liq_flags` = 0).

Ergebnis: alle erfuellt -> Carry-Ausfuehrung bauen, Signalquelle fuer Live = HL-Funding (Umstellung nicht waehrend der Papierphase, Entscheid Patrick). Mindestens eines verfehlt -> Carry nicht bauen, das Carry-Gewicht laeuft ueber Spill ohnehin in den Trend; Patrick entscheidet, ob der Plan angepasst wird.

## Einschraenkungen (vorab festgehalten)
Rund 3.3 Jahre Daten, davon 2.3 Jahre im Fenster, ein Marktregime. Basisrisiko, Margin-Abruf und Ausfuehrung des Perp-Beins sind nur als Modell abgebildet. 18 Kandidaten im Raster, dazu 6 Laeufe: Wiederholungen mit anderen Parametern zaehlen als zusaetzliche Versuche und werden gemeldet. Binance-Kontrollen zeigen nur, wie weit die alte Annahme vom neuen Ergebnis abweicht.
