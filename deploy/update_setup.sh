#!/usr/bin/env bash
# Einmalig als root: Deploy-Key erzeugen, Repo klonen, Update-Timer aktivieren.
#   Schritt 1: sudo bash update_setup.sh key      -> zeigt den oeffentlichen Schluessel (bei GitHub als Deploy key, nur Lesen, eintragen)
#   Schritt 2: sudo bash update_setup.sh install  -> klont das Repo und aktiviert den Timer
set -euo pipefail
KEY=/root/.ssh/deploy_autotrader
REPO=git@github.com:vinaccord/autotrader.git
case "${1:-}" in
  key)
    mkdir -p /root/.ssh && chmod 700 /root/.ssh
    [ -f "$KEY" ] || ssh-keygen -t ed25519 -N "" -C "autotrader-server-deploy" -f "$KEY" >/dev/null
    echo; echo "Oeffentlicher Schluessel (bei GitHub eintragen):"; cat "$KEY.pub"
    ;;
  install)
    ssh-keyscan -t ed25519 github.com >> /root/.ssh/known_hosts 2>/dev/null
    export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes"
    [ -d /opt/autotrader-src/.git ] || git clone "$REPO" /opt/autotrader-src
    bash /opt/autotrader-src/deploy/update.sh
    systemctl enable --now quant-update.timer
    systemctl list-timers quant-update.timer --no-pager
    ;;
  *) echo "Aufruf: update_setup.sh key|install"; exit 1;;
esac
