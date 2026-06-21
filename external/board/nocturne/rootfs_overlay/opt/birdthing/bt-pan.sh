#!/bin/sh
# BirdThing: maintain a Bluetooth PAN (PANU) link from the Car Thing to the Pi.
#
# The Car Thing is the PAN client; the Pi (bt-nap.sh) is the NAP server and the
# 192.168.44.1 gateway. Nocturne brings up the controller at boot (udev: ttyS1
# -> attach-bt -> btattach -P bcm; hci0 -> enable-bt) and runs bluetoothd with
# the `network` plugin (-> org.bluez.Network1).
#
# CRITICAL: the Pi NAP is classic Bluetooth (BR/EDR). bluetoothctl's default
# `scan on` discovers LE only, so the Pi is NEVER found unless we set the
# discovery filter transport to "bredr" first. That single detail is what made
# pairing impossible before. We set it via the `menu scan` submenu, hold the
# bluetoothctl session open with sleeps (fire-and-forget subcommands don't keep
# a scan running), and let a persistent NoInputNoOutput agent auto-confirm the
# JustWorks pairing.
#
# USB (usb0 = 192.168.7.2) stays up as a fallback; start-chromium and
# birdmic_ct.py prefer BT (192.168.44.1) and fall back to USB (192.168.7.1).
#
# NOTE: BT range is ~10m and much less through walls. If pairing keeps failing
# with "ConnectionAttemptFailed" while the Pi is occasionally discovered, the
# Pi is simply too far from the Car Thing -- move them closer.
set -u

CONF=/etc/birdthing/bt.conf
[ -f "$CONF" ] && . "$CONF"
: "${PI_BT_MAC:=DC:A6:32:62:53:01}"
: "${CT_BT_IP:=192.168.44.2/24}"

ADAPTER=hci0
DEV_PATH="/org/bluez/${ADAPTER}/dev_$(echo "$PI_BT_MAC" | tr ':' '_')"
CT_IP="${CT_BT_IP%/*}"

log() { echo "[bt-pan] $*"; }
paired()      { bluetoothctl info "$PI_BT_MAC" 2>/dev/null | grep -q 'Paired: yes'; }
bnep_up()     { [ -e /sys/class/net/bnep0 ]; }
bnep_has_ip() {
  { ip -o -4 addr show bnep0 2>/dev/null | grep -q 'inet '; } \
    || { ifconfig bnep0 2>/dev/null | grep -q 'inet '; }
}
set_bnep_ip() {
  ip addr add "$CT_BT_IP" dev bnep0 2>/dev/null && ip link set bnep0 up 2>/dev/null && return 0
  ifconfig bnep0 "$CT_IP" netmask 255.255.255.0 up 2>/dev/null
}

# --- wait for the controller (attach-bt runs from udev at boot) -------------
i=0
while [ ! -d "/sys/class/bluetooth/${ADAPTER}" ]; do
  i=$((i + 1)); [ "$i" -ge 90 ] && { log "no ${ADAPTER} after 90s; exiting (supervisord will retry)"; exit 1; }
  sleep 1
done
log "${ADAPTER} present; Pi NAP = ${PI_BT_MAC}"

# --- wait for bluetoothd to own the adapter ---------------------------------
i=0
while ! bluetoothctl show >/dev/null 2>&1; do
  i=$((i + 1)); [ "$i" -ge 60 ] && break
  sleep 1
done

# --- persistent JustWorks agent (auto-confirms NoInputNoOutput pairing) -----
( printf 'agent NoInputNoOutput\ndefault-agent\n'; while :; do sleep 3600; done ) | bluetoothctl >/dev/null 2>&1 &

bluetoothctl power on >/dev/null 2>&1

# --- discover (BR/EDR!) + pair the Pi NAP -----------------------------------
discover_and_pair() {
  log "scanning (BR/EDR transport) for ${PI_BT_MAC} and pairing"
  { echo "menu scan"; echo "transport bredr"; echo "back";
    echo "scan on"; sleep 18;
    echo "pair ${PI_BT_MAC}";  sleep 10;
    echo "pair ${PI_BT_MAC}";  sleep 10;
    echo "trust ${PI_BT_MAC}"; sleep 2;
    echo "scan off";
    echo "quit"; } | bluetoothctl >/dev/null 2>&1
}

connect_nap() {
  # Establish the ACL (paging the known device; no discovery needed), then
  # bring up the PANU role over D-Bus.
  bluetoothctl connect "${PI_BT_MAC}" >/dev/null 2>&1
  dbus-send --system --type=method_call --print-reply \
    --dest=org.bluez "${DEV_PATH}" \
    org.bluez.Network1.Connect string:'nap' >/dev/null 2>&1
}

# --- keep the PAN link up ----------------------------------------------------
while :; do
  bluetoothctl power on >/dev/null 2>&1

  if ! paired; then
    discover_and_pair
    if ! paired; then
      log "not paired yet (Pi out of range / RF?), will retry"
      sleep 5; continue
    fi
    log "paired to ${PI_BT_MAC}"
  fi

  if ! bnep_up; then
    log "connecting NAP"
    connect_nap
  fi

  if bnep_up && ! bnep_has_ip; then
    log "configuring bnep0 = ${CT_BT_IP}"
    set_bnep_ip
  fi

  if bnep_has_ip; then
    log "BT link up: bnep0 ${CT_IP} -> Pi 192.168.44.1"
    while bnep_has_ip; do sleep 10; done
    log "BT link dropped; reconnecting"
  fi

  sleep 5
done
