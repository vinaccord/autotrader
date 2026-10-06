#!/usr/bin/env bash
# Einrichtung auf einem frischen Ubuntu-VPS (22.04 oder 24.04). Als root ausfuehren, aus dem entpackten Projektordner:
#   sudo bash deploy/setup.sh
# Ungetestet auf echtem Server geschrieben. Zeile fuer Zeile lesen, bevor du es laufen laesst.
set -euo pipefail

APP_USER=autotrader
APP_DIR=/opt/autotrader
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

apt-get update
apt-get install -y python3 python3-venv

id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"

mkdir -p "$APP_DIR"
cp -a "$SRC_DIR"/. "$APP_DIR"/
mkdir -p "$APP_DIR/data/quant"

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
fi
chmod 600 "$APP_DIR/.env"
chmod +x "$APP_DIR/deploy/quant_daily.sh"
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

# Quant-Job: taeglicher Timer (Standard)
cp "$APP_DIR/deploy/quant-daily.service" /etc/systemd/system/quant-daily.service
cp "$APP_DIR/deploy/quant-daily.timer" /etc/systemd/system/quant-daily.timer
# Aelterer DEX-Paper-Agent: Dienst installieren, aber NICHT aktivieren (keine belegte Edge, siehe docs/STRATEGIE.md)
cp "$APP_DIR/deploy/autotrader.service" /etc/systemd/system/autotrader.service
systemctl daemon-reload
systemctl enable --now quant-daily.timer
systemctl start quant-daily.service || true   # erster Lauf sofort

echo
echo "Fertig. Timer:       systemctl list-timers quant-daily.timer"
echo "Log des Laufs:       tail -n 80 $APP_DIR/data/quant/daily.log"
echo "Journal bei Fehlern: journalctl -u quant-daily.service -e"
echo "DEX-Agent (optional, nicht empfohlen): systemctl enable --now autotrader"
