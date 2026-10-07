# Kriterium D: Schutzmechanismen getestet (Stand 7.10.2026)

Anforderung (docs/STRATEGIE.md Abschnitt 8): Kill-Switch (warn, brake, stop) und mindestens 3 Sicherungen mit Testdaten ausgeloest und im Repo dokumentiert.

**Stand: erfuellt** (Logik, mit Testdaten). Die Pruefung ist reproduzierbar:

    python -m autotrader.quant.protection_check          # nimmt die Schwellen aus live_plan.yaml, Exit 1 bei Abweichung
    python3 -m unittest discover -s tests               # enthaelt dieselben Szenarien als Test (ProtectionCheckTests)

## Was ausgeloest wird (Schwellen aus live_plan.yaml)

Kill-Switch (Hoechststand-basiert, Hoechststand im Beispiel 1100):
- normal: neuer Hoechststand
- warn: Verlust -21% (Schwelle -20%), Exposure bleibt x1.0
- brake: Verlust -31% (Schwelle -30%), Exposure x0.5
- Hysterese: Erholung auf -25% haelt die Bremse, erst unter -20% (Test: -15%) loest sie sich
- stop: Verlust -41% (Schwelle -40%), Exposure x0.0, alles USDC
- Stopp klebt: Erholung auf den alten Hoechststand hebt ihn nicht auf; nur `killswitch reset` auf Patricks Befehl
- stop bei Kontowert unter 60% der Einzahlungen (auch ohne grossen Verlust ab Hoechststand)
- verbuchte Auszahlung loest keinen Alarm aus; nicht verbuchte wirkt wie Verlust (zeigt, warum erst verbuchen, dann ueberweisen)

Sicherungen (je ein Fall der ausloest, einer der nicht ausloest, und fail-closed bei fehlender Eingabe):
1. Datenalter (max. 36 h)
2. Abweichung zweite Datenquelle (max. 3%)
3. USDC-Entkopplung (unter 0.98)
4. Unit-Token gegen Referenzkurs (max. 2%)
5. Einzelorder ueber 25% des Kontowerts und Tagesumsatz ueber 100%
6. Soll/Ist-Abweichung nach der Ausfuehrung (max. 5% des Kontowerts)

## Zusammenspiel im Lauf (Tests mit Fake-API, tests/test_quant.py HlExecTests, tests/test_live.py LiveRunTests)
- Alte Daten blockieren alle Orders (Papier und Live).
- Kontowert ueber `live.max_equity_usdc` blockiert alle Orders.
- Im Stopp werden Verkaeufe auch bei Sicherungs-Verstoessen gesendet (Kontowert kommt aus dem Konto, nicht aus Marktdaten); Kaeufe nie.
- Eine abgelehnte Order bricht die restlichen ab; ein Fill, der im Konto nicht erscheint, loest die Soll/Ist-Meldung aus.
- Live nur ueber `hl_live.py` mit fuenf Sperren (siehe Kopf der Datei); `live_plan.yaml` im Repo ist `dry-run` und nicht freigegeben (Test).

## Grenzen (ehrlich)
- Das sind Logik-Tests mit Testdaten. Nicht geprueft: Verhalten gegen die echte API (Antwortformate, Fehlerfaelle, Zeitverhalten). Das gehoert zu Kriterium E (Kleinstbetrag-Test).
- ntfy-Alarm im Live-Lauf: `hl_live.py` sendet bei abgelehnter Order, Soll/Ist-Abweichung oder blockierten Orders eine Kurzmeldung (ohne Betraege und Positionen) und endet mit Exit-Code 1. Getestet mit Fake-Post, nicht gegen ntfy.sh. Der Tagesbericht und `quant_daily.sh` melden getrennt davon.
- Liegt das USDC im Perp- statt im Spot-Konto, blockiert der Live-Lauf mit klarer Meldung (Test mit Fake-API; echtes Kontoverhalten bei der Einrichtung pruefen).
- Schwellen sind Annahmen (Patricks Verlusttoleranz 40%), keine Optimierung.
