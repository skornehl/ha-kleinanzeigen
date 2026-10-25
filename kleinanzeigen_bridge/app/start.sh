#!/bin/bash
# Starts the browser desktop (KasmVNC + openbox, only reachable on
# 127.0.0.1 - the bridge proxies it into HA ingress) and then the bridge.
# Modelled on docker/image/run.sh of kleinanzeigen-bot, minus the parts we
# do not need (privilege drop, password banner, running the bot directly).
set -euo pipefail

export HOME=/root
export DISPLAY=:99
# No GPU in the add-on: Chromium needs SwiftShader for WebGL.
export KLEINANZEIGEN_BOT_CHROMIUM_FLAGS="--enable-unsafe-swiftshader"

# KasmVNC insists on a user database even with basic auth disabled.
# Access control is HA ingress (only the Supervisor proxy may connect).
pw=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 20)
printf '%s\n%s\n' "$pw" "$pw" | kasmvncpasswd -u user -w -o >/dev/null

mkdir -p /tmp/.X11-unix
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
Xvnc :99 \
  -geometry 1440x900 -depth 24 \
  -websocketPort 6080 -interface 127.0.0.1 \
  -PublicIP 127.0.0.1 \
  -SecurityTypes None -sslOnly 0 -disableBasicAuth \
  -httpd /usr/share/kasmvnc/www >/tmp/xvnc.log 2>&1 &
xvnc_pid=$!
for _ in $(seq 100); do
  [ -S /tmp/.X11-unix/X99 ] && break
  kill -0 "$xvnc_pid" 2>/dev/null || break
  sleep 0.1
done
if [ ! -S /tmp/.X11-unix/X99 ]; then
  echo "KasmVNC startet nicht:" >&2
  cat /tmp/xvnc.log >&2
  exit 1
fi
openbox >/tmp/openbox.log 2>&1 &

exec python3 /opt/bridge/bridge.py
