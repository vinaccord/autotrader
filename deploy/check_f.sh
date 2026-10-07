#!/usr/bin/env bash
# Kriterium F pruefen (siehe docs/STRATEGIE.md Abschnitt 8). Auf dem Server: sudo bash /opt/autotrader-src/deploy/check_f.sh
# Zeigt PASS/FAIL je Punkt, nie Inhalte von .env. Exit 1 bei mindestens einem FAIL.
ENVF="${ENVF:-/opt/autotrader/.env}"
fail=0
ok()  { echo "PASS  $1"; }
bad() { echo "FAIL  $1"; fail=1; }
envval() { grep -E "^$1=" "$ENVF" 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '"'"'"; }

if systemctl is-enabled quant-update.timer 2>/dev/null | grep -q '^enabled'; then bad "quant-update.timer ist noch aktiv (Auto-Update als root)"; else ok "Auto-Update-Timer ist nicht aktiv"; fi
U=/usr/local/sbin/autotrader-update
if [ -x "$U" ] && [ "$(stat -c %U "$U")" = root ] && [ -z "$(find "$U" -perm /022)" ]; then ok "autotrader-update installiert, root-eigen, nicht schreibbar fuer andere"; else bad "autotrader-update fehlt oder ist nicht root-eigen/755"; fi
if [ -s /etc/autotrader/allowed_signers ]; then ok "allowed_signers vorhanden"; else bad "/etc/autotrader/allowed_signers fehlt oder leer"; fi
topic="$(envval NTFY_TOPIC)"
if [ "${#topic}" -ge 24 ]; then ok "NTFY_TOPIC hat mindestens 24 Zeichen"; else bad "NTFY_TOPIC fehlt oder ist kuerzer als 24 Zeichen (erratbar)"; fi
if [ "$(envval NTFY_DETAIL)" = short ]; then ok "NTFY_DETAIL=short (keine Positionen im Push)"; else bad "NTFY_DETAIL ist nicht 'short'"; fi
if [ -n "$(envval HC_PING_URL)" ]; then ok "HC_PING_URL gesetzt (unabhaengiger Dead-Man-Switch)"; else bad "HC_PING_URL fehlt"; fi
if ufw status 2>/dev/null | grep -q 'Status: active'; then ok "ufw aktiv"; else bad "ufw nicht aktiv"; fi
exit $fail
