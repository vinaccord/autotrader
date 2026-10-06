#!/usr/bin/env bash
# Holt den neuesten Code aus dem privaten GitHub-Repo und legt ihn nach /opt/autotrader.
# Fasst weder data/ noch .env noch venv/ an (nur im Repo versionierte Dateien werden ersetzt).
# Nur fuer die Paper-Phase gedacht. Vor Live-Betrieb abschalten: systemctl disable --now quant-update.timer
set -euo pipefail
SRC=/opt/autotrader-src
APP=/opt/autotrader
export GIT_SSH_COMMAND="ssh -i /root/.ssh/deploy_autotrader -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes"
cd "$SRC"
git fetch --quiet origin main
git reset --hard --quiet origin/main
git archive HEAD | tar -x -C "$APP"
chmod +x "$APP/deploy/quant_daily.sh"
chown -R autotrader:autotrader "$APP"
# Units aktuell halten
cp "$APP/deploy/quant-daily.service" "$APP/deploy/quant-daily.timer" /etc/systemd/system/
cp "$APP/deploy/quant-update.service" "$APP/deploy/quant-update.timer" /etc/systemd/system/
systemctl daemon-reload
echo "update ok: $(git rev-parse --short HEAD) $(date -u +%FT%TZ)"
