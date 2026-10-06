#!/usr/bin/env bash
# Taeglicher Lauf: Daten holen, Signale beider Profile berechnen, Ergebnis ins Log schreiben.
# quant_40.yaml = Hauptprofil (Trend 70%, Carry 30%). quant.yaml = Vergleichsprofil (adaptiv, risikoarm).
set -euo pipefail
cd /opt/autotrader
PY=/opt/autotrader/venv/bin/python
LOG=/opt/autotrader/data/quant/daily.log
SIG=/opt/autotrader/data/quant/signals.log
mkdir -p /opt/autotrader/data/quant
{
  echo "=== $(date -u +%FT%TZ) ==="
  $PY -m autotrader.quant.cli --config quant_40.yaml fetch
  echo "--- Profil 40 (Haupt) ---"
  $PY -m autotrader.quant.cli --config quant_40.yaml backtest
  $PY -m autotrader.quant.cli --config quant_40.yaml signal | tee -a "$SIG"
  echo "--- Profil Kern (Vergleich) ---"
  $PY -m autotrader.quant.cli --config quant.yaml signal | tee -a "$SIG"
  echo "--- Makro (Beobachtung) ---"
  $PY -m autotrader.quant.macro --config quant_40.yaml fetch || echo "Makro-Abruf fehlgeschlagen (nicht kritisch)"
  echo "--- Tagesbericht ---"
  $PY -m autotrader.quant.report --main quant_40.yaml --core quant.yaml --paper-start 2026-10-06
} >> "$LOG" 2>&1
