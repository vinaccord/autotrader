#!/usr/bin/env bash
# Taeglicher Lauf: Daten holen, Signale beider Profile berechnen, Tagesbericht, Alarm bei Fehlern.
# quant_40.yaml = Hauptprofil. quant.yaml = Vergleichsprofil.
# Jeder Schritt laeuft auch, wenn ein frueherer scheitert. Fehlgeschlagene Schritte loesen eine ntfy-Meldung aus.
set -uo pipefail
cd /opt/autotrader
PY=/opt/autotrader/venv/bin/python
LOG=/opt/autotrader/data/quant/daily.log
SIG=/opt/autotrader/data/quant/signals.log
PAPER_START="${PAPER_START:-2026-10-06}"
mkdir -p /opt/autotrader/data/quant
FAILED=()

step() {  # step NAME KOMMANDO...
  local name="$1"; shift
  echo "--- $name ---"
  if ! "$@"; then
    echo "!!! Schritt fehlgeschlagen: $name"
    FAILED+=("$name")
  fi
}

{
  echo "=== $(date -u +%FT%TZ) ==="
  step "Daten" $PY -m autotrader.quant.cli --config quant_40.yaml fetch
  step "Backtest Profil 40" $PY -m autotrader.quant.cli --config quant_40.yaml backtest
  step "Signal Profil 40" bash -o pipefail -c "$PY -m autotrader.quant.cli --config quant_40.yaml signal | tee -a '$SIG'"
  step "Signal Kernprofil" bash -o pipefail -c "$PY -m autotrader.quant.cli --config quant.yaml signal | tee -a '$SIG'"
  step "Trockenlauf Ausfuehrung" $PY -m autotrader.quant.hl_exec --config quant_40.yaml --plan live_plan.yaml
  $PY -m autotrader.quant.macro --config quant_40.yaml fetch || echo "Makro-Abruf fehlgeschlagen (nicht kritisch)"
  step "Tagesbericht" $PY -m autotrader.quant.report --main quant_40.yaml --core quant.yaml --paper-start "$PAPER_START"
  if [ ${#FAILED[@]} -gt 0 ]; then
    echo "FEHLER in: ${FAILED[*]}"
  fi
} >> "$LOG" 2>&1

# Dead-Man-Switch: Healthchecks.io meldet sich selbst, wenn der Ping ausbleibt (Server aus, Timer tot).
# HC_PING_URL steht in /opt/autotrader/.env, z.B. https://hc-ping.com/<uuid>
hc() {  # hc "" | hc /fail
  [ -n "${HC_PING_URL:-}" ] && curl -fsS -m 15 --retry 3 "${HC_PING_URL}$1" >/dev/null 2>&1 || true
}

if [ ${#FAILED[@]} -gt 0 ]; then
  hc /fail
  if [ -n "${NTFY_TOPIC:-}" ]; then
    curl -s -m 20 -H "Title: Autotrader: FEHLER" -H "Priority: urgent" \
      -d "Fehlgeschlagen: ${FAILED[*]}. Details: sudo tail -n 80 $LOG" "https://ntfy.sh/$NTFY_TOPIC" >/dev/null || true
  fi
  exit 1
fi
hc ""
