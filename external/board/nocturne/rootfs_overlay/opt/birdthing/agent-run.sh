#!/bin/sh
# BirdThing OTA launcher. Fetches the freshest copy of a Car Thing daemon from
# the Pi (which hosts them at http://192.168.44.1:8092/) and execs it, falling
# back to the baked-in copy if the Pi isn't reachable. This is how updates are
# pushed WITHOUT reflashing: edit the file in the Pi's /opt/birdthing/ct-agent/
# and reboot the Car Thing (or `supervisorctl restart <prog>`).
#
# bt-pan.sh is deliberately NOT fetched this way -- it's what brings the BT link
# up, so it must stay baked (otherwise OTA couldn't reach the Pi at all).
NAME="$1"
PI="${BIRD_PI_HOST:-192.168.44.1}"
PORT="${BIRD_OTA_PORT:-8092}"
BAKED="/opt/birdthing/${NAME}"
DEST="/tmp/ct-agent/${NAME}"
mkdir -p /tmp/ct-agent

# Wait for the Pi over the BT link (up to ~70s) so we can fetch the latest.
i=0
while ! ping -c 1 -W 2 "$PI" >/dev/null 2>&1; do
  i=$((i + 1)); [ "$i" -ge 35 ] && break
  sleep 2
done

if wget -q -T 10 -O "${DEST}.new" "http://${PI}:${PORT}/${NAME}" 2>/dev/null && [ -s "${DEST}.new" ]; then
  mv "${DEST}.new" "$DEST"
  echo "[agent-run] ${NAME}: fetched latest from Pi"
else
  rm -f "${DEST}.new" 2>/dev/null
  cp "$BAKED" "$DEST" 2>/dev/null
  echo "[agent-run] ${NAME}: Pi unreachable, using baked copy"
fi

case "$NAME" in
  *.py) exec python3 "$DEST" ;;
  *)    exec sh "$DEST" ;;
esac
