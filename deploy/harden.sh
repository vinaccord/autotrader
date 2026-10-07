#!/usr/bin/env bash
# Server-Haertung (Phase 0). Als root auf dem VPS: sudo bash /opt/autotrader-src/deploy/harden.sh
# Idempotent. Reihenfolge schuetzt vor Aussperren: erst Firewall mit Port 22, Passwort-Login nur aus,
# wenn fuer 'ubuntu' ein SSH-Schluessel hinterlegt ist. Ungetestet auf echtem Server: Zeilen lesen, danach pruefen.
set -euo pipefail

# 1. Pakete
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y ufw fail2ban curl python3

# 2. Firewall: nur SSH eingehend
ufw allow 22/tcp
ufw default deny incoming
ufw default allow outgoing
ufw --force enable

# 3. SSH: Passwort-Login aus (nur wenn ein Schluessel da ist)
if [ -s /home/ubuntu/.ssh/authorized_keys ]; then
  cat > /etc/ssh/sshd_config.d/99-hardening.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
CONF
  sshd -t && systemctl reload ssh
else
  echo "WARNUNG: kein SSH-Schluessel fuer ubuntu gefunden, Passwort-Login bleibt an." >&2
fi

# 4. fail2ban: sshd-Jail
cat > /etc/fail2ban/jail.d/sshd.local <<'CONF'
[sshd]
enabled = true
maxretry = 5
findtime = 10m
bantime = 1h
CONF
systemctl enable --now fail2ban
systemctl restart fail2ban

# 5. GitHub-Host-Key aus der offiziellen API (HTTPS, TLS-geprueft) statt ssh-keyscan
umask 077
mkdir -p /root/.ssh
curl -fsS https://api.github.com/meta | python3 -c '
import json, sys
keys = json.load(sys.stdin)["ssh_keys"]
print("\n".join("github.com " + k for k in keys))
' > /root/.ssh/known_hosts.github.new
if [ -s /root/.ssh/known_hosts.github.new ]; then
  mv /root/.ssh/known_hosts.github.new /root/.ssh/known_hosts
else
  echo "WARNUNG: GitHub-Keys nicht abrufbar, known_hosts unveraendert." >&2
fi

# 6. Logrotate fuer die Quant-Logs
cat > /etc/logrotate.d/autotrader <<'CONF'
/opt/autotrader/data/quant/daily.log /opt/autotrader/data/quant/signals.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    copytruncate
}
CONF

echo
echo "Kontrolle:"
ufw status | head -5
sshd -T | grep -i -E '^(passwordauthentication|permitrootlogin)'
fail2ban-client status sshd | head -5
cd /opt/autotrader-src && git -c core.sshCommand="ssh -i /root/.ssh/deploy_autotrader -o StrictHostKeyChecking=yes" ls-remote origin HEAD >/dev/null && echo "GitHub-Zugriff OK (Host-Key geprueft)"
