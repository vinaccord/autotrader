# Signierte Updates einrichten (Kriterium F)

Einmalig, nur durch Patrick. Ohne diese Schritte bleibt das Auto-Update an (reicht fuer den Papierbetrieb, nicht fuer Live).

Hinweis: Die Befehle in Teil 1 laufen im **Windows-Terminal (PowerShell)** auf deinem PC, Teil 2 und 3 im **SSH-Fenster `ubuntu@...`**.
Der Signierschluessel bleibt auf deinem PC. Er ist ein eigener Schluessel, nicht der SSH-Login-Schluessel.

## Teil 1: Signierschluessel (Windows, PowerShell)
    ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\autotrader_signing -C "autotrader-release"
    type $env:USERPROFILE\.ssh\autotrader_signing.pub
Den Inhalt der `.pub`-Zeile (eine Zeile, beginnt mit `ssh-ed25519`) schickst du mir. Den privaten Schluessel (Datei ohne `.pub`) gibst du nie weiter.

## Teil 2: Server umstellen (SSH-Fenster, nachdem ich die Zeile eingebaut habe)
    sudo bash /opt/autotrader-src/deploy/update_setup.sh lock
Das installiert `/usr/local/sbin/autotrader-update`, schreibt `/etc/autotrader/allowed_signers` und schaltet `quant-update.timer` aus.

## Teil 3: Neuen Stand ausrollen (Windows, im Repo-Ordner)
    git tag -s v2026.12.1 -m "Release" ; git push origin v2026.12.1
(vorher `git config gpg.format ssh` und `git config user.signingkey $env:USERPROFILE\.ssh\autotrader_signing.pub`). Danach im SSH-Fenster:
    sudo autotrader-update v2026.12.1

## Pruefen
    sudo bash /opt/autotrader-src/deploy/check_f.sh
