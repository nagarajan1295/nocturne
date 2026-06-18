#!/usr/bin/env python3
# BirdThing mic daemon (Car Thing side).
#
# Captures the Superbird PDM mic and pushes it over ONE persistent TCP
# connection to the Pi receiver (192.168.7.1:9000), which feeds it into the
# ALSA loopback -> BirdNET. This is the "TCP push" design (replaces the old
# SSH-stream that wedged the device).
#
# The PDM mic produces ZERO samples until ALSA control numid 15 "Audio In
# Source" is set to PDMIN (enum 4); numid 6 "PDM Train" then kicks the
# datapath. Both are runtime-only, re-applied on every (re)open.
#
# Pure stdlib + libasound via ctypes (no arecord/amixer on the device).
import ctypes, socket, time, array, os

PI_HOST   = os.environ.get("BIRD_PI_HOST", "192.168.7.1")
PI_PORT   = int(os.environ.get("BIRD_PI_PORT", "9000"))
RATE      = 48000
N         = 2048      # frames per read
TARGET_PEAK = 9000    # AGC target amplitude (S16)
MAX_GAIN  = 120.0
MIN_GAIN  = 1.0
NOISE_FLOOR = 25      # raw peak below this => treat as silence (gate, no false positives)
QUIET_RECOVER_SEC = 20  # reopen PDM after sustained sub-floor audio ("stuck-quiet" mic)

a = ctypes.CDLL("libasound.so.2")
a.snd_pcm_readi.restype = ctypes.c_long


def apply_pdm():
    """Select PDMIN as capture source and trigger the PDM datapath."""
    ctl = ctypes.c_void_p()
    if a.snd_ctl_open(ctypes.byref(ctl), b"hw:0", 0) < 0:
        return
    def setc(numid, v):
        eid = ctypes.c_void_p(); a.snd_ctl_elem_id_malloc(ctypes.byref(eid))
        a.snd_ctl_elem_id_set_numid(eid, numid)
        a.snd_ctl_elem_id_set_interface(eid, 2)   # SND_CTL_ELEM_IFACE_MIXER
        val = ctypes.c_void_p(); a.snd_ctl_elem_value_malloc(ctypes.byref(val))
        a.snd_ctl_elem_value_set_id(val, eid)
        a.snd_ctl_elem_value_set_enumerated(val, 0, v)
        a.snd_ctl_elem_write(ctl, val)
    setc(15, 4)   # Audio In Source = PDMIN
    setc(6, 1)    # PDM Train trigger (self-clearing)
    a.snd_ctl_close(ctl)


def open_pcm():
    apply_pdm()
    p = ctypes.c_void_p()
    if a.snd_pcm_open(ctypes.byref(p), b"hw:0,0", 1, 0) < 0:   # SND_PCM_STREAM_CAPTURE=1
        return None
    # set_params(pcm, fmt=S16_LE(2), access=RW_INTERLEAVED(3), ch=1, rate, soft_resample=1, latency_us)
    if a.snd_pcm_set_params(p, 2, 3, 1, RATE, 1, 500000) < 0:
        a.snd_pcm_close(p)
        return None
    a.snd_pcm_start(p)
    return p


def connect_pi():
    while True:
        try:
            s = socket.create_connection((PI_HOST, PI_PORT), timeout=10)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print("[birdmic] connected to %s:%d" % (PI_HOST, PI_PORT), flush=True)
            return s
        except OSError:
            time.sleep(3)


def main():
    gain = 8.0
    while True:
        p = open_pcm()
        if not p:
            print("[birdmic] PDM open failed, retry", flush=True)
            time.sleep(2)
            continue
        s = connect_pi()
        buf = ctypes.create_string_buffer(N * 2)
        quiet_since = None
        try:
            while True:
                n = a.snd_pcm_readi(p, buf, N)
                if n < 0:
                    a.snd_pcm_recover(p, n, 1)
                    continue
                if n == 0:
                    continue
                mono = array.array('h')
                mono.frombytes(buf.raw[:n * 2])
                peak = 0
                for x in mono:
                    ax = x if x >= 0 else -x
                    if ax > peak:
                        peak = ax
                now = time.time()

                # "stuck-quiet" watchdog: PDM still streaming but near-silent.
                if peak < NOISE_FLOOR:
                    if quiet_since is None:
                        quiet_since = now
                    elif now - quiet_since > QUIET_RECOVER_SEC:
                        print("[birdmic] quiet too long, reopening PDM", flush=True)
                        break
                else:
                    quiet_since = None

                # Auto-gain toward TARGET_PEAK, gated by the noise floor.
                if peak >= NOISE_FLOOR:
                    desired = TARGET_PEAK / float(peak)
                    if desired > MAX_GAIN:
                        desired = MAX_GAIN
                    if desired < MIN_GAIN:
                        desired = MIN_GAIN
                    gain += (desired - gain) * 0.1
                    g = gain
                else:
                    g = 0.0  # gate silence so it isn't blown into false positives

                st = array.array('h', bytes(4 * n))
                for i in range(n):
                    v = int(mono[i] * g)
                    if v > 32767:
                        v = 32767
                    elif v < -32768:
                        v = -32768
                    st[2 * i] = v
                    st[2 * i + 1] = v
                try:
                    s.sendall(st.tobytes())
                except OSError:
                    print("[birdmic] socket lost, reconnecting", flush=True)
                    break
        finally:
            try:
                a.snd_pcm_close(p)
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass
        time.sleep(1)


if __name__ == "__main__":
    main()
