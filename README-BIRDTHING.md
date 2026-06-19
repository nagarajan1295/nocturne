# BirdThing OS — a Terbium-flashable Car Thing firmware

A fork of [Nocturne](https://github.com/usenocturne/nocturne) turned into a clean,
flashable firmware for the **BirdThing** project. It replaces the fragile Debian
Chromium kiosk (low RAM → wedged sshd, broken apt, `/run` tmpfs bug) with a
purpose-built Buildroot image.

The Car Thing stays a **thin client**: it captures the mic and displays the
dashboard. All the heavy lifting (BirdNET inference, the database, the dashboard
web server) runs on the **Raspberry Pi**, reached over USB networking.

## What this fork changes vs. stock Nocturne

| Area | Change | File |
|------|--------|------|
| Display | Chromium auto-picks the Pi dashboard: BT `http://192.168.44.1:8090/` first, USB `http://192.168.7.1:8090/` fallback | `.../bin/start-chromium` |
| **Bluetooth** | **CT joins the Pi's BT-PAN (NAP) as a client; `bnep0` = `192.168.44.2`. BlueZ `network` plugin enabled + auto-pair/connect daemon** | `configs/nocturne_defconfig`, `.../bin/start-bluetoothd`, `.../opt/birdthing/bt-pan.sh`, `.../etc/birdthing/bt.conf` |
| Networking | `usb0` = `192.168.7.2` stays up as the fallback link, route via Pi `192.168.7.1` | `.../etc/init.d/S49usbgadget` |
| Mic | PDM capture + AGC + TCP push to the Pi `:9000` | `.../opt/birdthing/birdmic_ct.py` |
| Knob/controls | rotary → DevTools ArrowUp/Down (port 2222); brightness/display/reboot HTTP control on `:8091` | `.../opt/birdthing/birdknob_ct.py` |
| Services | run the two daemons under supervisord | `.../etc/supervisor.d/birdthing.conf` |
| Build | GitHub Actions builds the flashable zip in the cloud | `.github/workflows/build.yml` |

> The mic/knob daemons were reconstructed from the live BirdThing CT daemons.
> Before relying on them, diff against `/opt/birdthing/birdmic_ct.py` and
> `birdknob_ct.py` on the running device.

## Build (no local Linux needed)

The Buildroot compile runs on a GitHub Actions cloud runner:

1. Push to the `birdthing` branch (or run the **Build BirdThing image** workflow
   manually from the Actions tab).
2. When it goes green, download the **`birdthing-flashable-zip`** artifact.

The workflow runs `fetch-stock.sh` (loop-mounts the stock firmware to pull
proprietary blobs) then `./scripts/build.sh package`, producing
`output/package/nocturne.zip`.

## Flash (Windows, all in the browser)

1. Install the Terbium driver (PowerShell): `irm https://driver.terbium.app/get | iex`
2. Open <https://terbium.app> in Chrome/Edge.
3. Hold buttons **1 + 4** (top row) and plug in the **spare** Car Thing's USB.
4. Load the downloaded zip and flash (~5–10 min; try multiple USB ports).

## Bluetooth link (CT ⇆ Pi over BT-PAN)

This image links the Car Thing to the Pi over **Bluetooth PAN**, with USB as an
automatic fallback. No device-tree wall here: Nocturne reuses the **stock kernel
+ DTB** (which powers the Broadcom combo chip) and the stock `/lib/firmware/brcm`
blobs, and already brings the controller up at boot
(`udev: ttyS1 → attach-bt → btattach -P bcm`; `hci0 → enable-bt`).

What this fork adds for PAN:

1. **`BR2_PACKAGE_BLUEZ5_UTILS_PLUGINS_NETWORK=y`** — compiles BlueZ's `network`
   plugin (`org.bluez.Network1`, PANU/NAP).
2. **`start-bluetoothd`** now loads `--plugin=gap,deviceinfo,network` (the stock
   list excluded `network`, so PAN could never start).
3. **`bt-pan.sh`** (supervisord `bt-pan`, prio 78): waits for `hci0`, powers on,
   registers a `NoInputNoOutput` agent, pairs+trusts the Pi (JustWorks), then
   `Network1.Connect("nap")` and statically addresses `bnep0` = `192.168.44.2`.
   Self-heals: reconnects whenever the link drops.
4. **`start-chromium`** and **`birdmic_ct.py`** probe `192.168.44.1` (BT) first,
   then `192.168.7.1` (USB) — so the device works on whichever link is live.

The Pi's NAP MAC lives in `etc/birdthing/bt.conf` (`PI_BT_MAC`, default
`DC:A6:32:62:53:01`). Change it there if the Pi's adapter differs.

> Not yet verified on hardware (needs a flash + the Pi NAP running). The USB
> fallback means the device still works if BT auto-connect needs tuning.

## Pi side

The Pi must be running its existing BirdThing services: `birdthing-recv`
(TCP `:9000` → ALSA loopback → BirdNET), `birdthing-api` (dashboard on `:8090`),
and the `usb0` keeper holding `192.168.7.1/24`.

For the **Bluetooth** path the Pi must also run its NAP server
(`/opt/birdthing/bt-nap.sh`: br0 = `192.168.44.1/24`, dnsmasq, `bt-network` NAP,
discoverable + `NoInputNoOutput` agent), and the `birdthing-recv`/`birdthing-api`
services must listen on `0.0.0.0` (or `192.168.44.1`) so they're reachable over
`br0`, not only on the USB `192.168.7.1`.
