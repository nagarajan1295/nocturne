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
| Display | Chromium points at the Pi dashboard `http://192.168.7.1:8090/` | `external/board/nocturne/rootfs_overlay/etc/supervisord.conf` (chromium `environment=`) |
| Networking | `usb0` = `192.168.7.2`, route via Pi `192.168.7.1` (matches the Pi's existing host side) | `.../etc/init.d/S49usbgadget` |
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

## Pi side (unchanged)

The Pi must be running its existing BirdThing services: `birdthing-recv`
(TCP `:9000` → ALSA loopback → BirdNET), `birdthing-api` (dashboard on `:8090`),
and the `usb0` keeper holding `192.168.7.1/24`.
