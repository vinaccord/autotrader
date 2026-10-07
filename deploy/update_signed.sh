#!/usr/bin/env bash
# Update nur auf einen signierten Tag. Wird ausserhalb des Repos nach /usr/local/sbin/autotrader-update installiert
# (root-eigen, nicht vom Update selbst ueberschreibbar), siehe deploy/README_signed_update.md.
#   sudo autotrader-update v2026.12.1
# Ablauf: Tags holen, SSH-Signatur gegen /etc/autotrader/allowed_signers pruefen, erst dann ausrollen. Kein Auto-Update.
set -euo pipefail
TAG="${1:-}"
SRC="${SRC:-/opt/autotrader-src}"
APP="${APP:-/opt/autotrader}"
SIGNERS="${SIGNERS:-/etc/autotrader/allowed_signers}"
SKIP_SYSTEM="${AUTOTRADER_SKIP_SYSTEM:-}"   # nur fuer Tests: kein chown, kein systemctl
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -i /root/.ssh/deploy_autotrader -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes}"

if ! [[ "$TAG" =~ ^v[0-9]+(\.[0-9]+)*$ ]]; then
  echo "Aufruf: autotrader-update vJAHR.MONAT.N (z.B. v2026.12.1)" >&2
  exit 2
fi
if [ ! -s "$SIGNERS" ]; then
  echo "FEHLER: $SIGNERS fehlt oder ist leer, kein Update." >&2
  exit 3
fi
cd "$SRC"
git fetch --quiet --force --tags origin
if ! git rev-parse -q --verify "refs/tags/$TAG^{tag}" >/dev/null; then
  echo "FEHLER: $TAG ist kein annotierter Tag." >&2
  exit 4
fi
if ! git -c gpg.format=ssh -c gpg.ssh.allowedSignersFile="$SIGNERS" verify-tag "$TAG" 2>&1; then
  echo "FEHLER: Signatur von $TAG nicht gueltig, nichts ausgerollt." >&2
  exit 5
fi
git checkout --quiet --force "refs/tags/$TAG^{commit}"
git archive HEAD | tar -x -C "$APP"
chmod +x "$APP/deploy/quant_daily.sh"
if [ -z "$SKIP_SYSTEM" ]; then
  chown -R autotrader:autotrader "$APP"
  cp "$SRC/deploy/quant-daily.service" "$SRC/deploy/quant-daily.timer" /etc/systemd/system/
  systemctl daemon-reload
fi
echo "update ok: $TAG $(git rev-parse --short HEAD) $(date -u +%FT%TZ)"
