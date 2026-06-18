#!/usr/bin/env python3
# BirdThing knob + control daemon (Car Thing side).
#
# 1) Reads the rotary encoder (/dev/input/eventN, auto-detected) and dispatches
#    ArrowUp/ArrowDown to the dashboard via the Chromium DevTools protocol
#    (Nocturne's start-chromium exposes --remote-debugging-port=2222).
#    The rotary has NO kbd handler, so Chromium never sees the turns natively.
# 2) Hosts a tiny HTTP control server on 127.0.0.1:8091 for the dashboard's
#    Settings (brightness / display on-off / reboot / poweroff). Chromium's
#    Private Network Access blocks page->localhost unless we send the
#    Access-Control-Allow-Private-Network header + answer the OPTIONS preflight.
#
# Pure stdlib only.
import os, glob, struct, socket, base64, hashlib, json, time, threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEVTOOLS_PORT = int(os.environ.get("BIRD_DEVTOOLS_PORT", "2222"))
CTRL_PORT     = int(os.environ.get("BIRD_CTRL_PORT", "8091"))

# input_event on 32-bit ARM: struct timeval(2*long=8) + type(H) + code(H) + value(i)
EV_FMT = "llHHi"
EV_SZ  = struct.calcsize(EV_FMT)
EV_REL = 0x02
EV_KEY = 0x01

# ---------- rotary device discovery ----------
def find_rotary():
    """Return /dev/input/eventN for the rotary encoder, or None."""
    try:
        with open("/proc/bus/input/devices") as f:
            blocks = f.read().split("\n\n")
    except OSError:
        return None
    for b in blocks:
        low = b.lower()
        if "rotary" in low or "rotenc" in low or "rot_enc" in low:
            for line in b.splitlines():
                if line.startswith("H:") and "event" in line:
                    for tok in line.split():
                        if tok.startswith("event"):
                            return "/dev/input/" + tok
    return None

# ---------- minimal websocket client (send-only + drain) ----------
def ws_connect(url):
    assert url.startswith("ws://"), url
    hostport, _, path = url[5:].partition("/")
    path = "/" + path
    host, _, port = hostport.partition(":")
    s = socket.create_connection((host, int(port or 80)), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode()
    req = ("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\n"
           "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
           "Sec-WebSocket-Version: 13\r\n\r\n" % (path, hostport, key))
    s.sendall(req.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = s.recv(1024)
        if not chunk:
            raise OSError("ws handshake closed")
        resp += chunk
    if b"101" not in resp.split(b"\r\n", 1)[0]:
        raise OSError("ws handshake failed")
    s.setblocking(False)
    return s

def ws_send(s, text):
    payload = text.encode()
    n = len(payload)
    hdr = bytearray([0x81])  # FIN + text
    mask = os.urandom(4)
    if n < 126:
        hdr.append(0x80 | n)
    elif n < 65536:
        hdr.append(0x80 | 126); hdr += struct.pack(">H", n)
    else:
        hdr.append(0x80 | 127); hdr += struct.pack(">Q", n)
    hdr += mask
    masked = bytes(payload[i] ^ mask[i % 4] for i in range(n))
    s.sendall(bytes(hdr) + masked)

def ws_drain(s):
    """Discard any pending server frames so the socket buffer can't fill up."""
    try:
        while True:
            d = s.recv(65536)
            if not d:
                break
    except OSError:
        pass

def page_ws_url():
    try:
        data = json.load(urllib.request.urlopen(
            "http://127.0.0.1:%d/json" % DEVTOOLS_PORT, timeout=3))
    except Exception:
        return None
    for t in data:
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
            return t["webSocketDebuggerUrl"]
    return None

class DevTools:
    def __init__(self):
        self.ws = None
        self.id = 1
    def ensure(self):
        if self.ws is not None:
            return True
        url = page_ws_url()
        if not url:
            return False
        try:
            self.ws = ws_connect(url)
            return True
        except OSError:
            self.ws = None
            return False
    def key(self, code, vk):
        if not self.ensure():
            return
        try:
            for typ in ("keyDown", "keyUp"):
                msg = {"id": self.id, "method": "Input.dispatchKeyEvent",
                       "params": {"type": typ, "windowsVirtualKeyCode": vk,
                                  "nativeVirtualKeyCode": vk, "code": code, "key": code}}
                ws_send(self.ws, json.dumps(msg))
                self.id += 1
            ws_drain(self.ws)
        except OSError:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

# ---------- backlight control ----------
def backlight_paths():
    base = glob.glob("/sys/class/backlight/*")
    return base[0] if base else None

def set_brightness(level):
    bl = backlight_paths()
    if not bl:
        return
    try:
        with open(bl + "/max_brightness") as f:
            mx = int(f.read().strip())
    except OSError:
        mx = 255
    table = {"low": int(mx * 0.18), "mid": int(mx * 0.51),
             "high": mx, "auto": int(mx * 0.36)}
    val = table.get(level, table["auto"])
    if val < 1:
        val = 1
    try:
        with open(bl + "/brightness", "w") as f:
            f.write(str(val))
    except OSError:
        pass

# ---------- HTTP control server ----------
class Ctrl(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()
    def do_GET(self):
        path, _, query = self.path.partition("?")
        q = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        body = b"ok"
        if path == "/bright":
            set_brightness(q.get("level", "auto"))
        elif path == "/display":
            on = q.get("on", "1")
            bl = backlight_paths()
            if bl:
                try:
                    with open(bl + "/bl_power", "w") as f:
                        f.write("0" if on == "1" else "4")
                except OSError:
                    if on == "1":
                        set_brightness("auto")
                    else:
                        try:
                            open(bl + "/brightness", "w").write("0")
                        except OSError:
                            pass
        elif path == "/reboot":
            threading.Timer(0.5, lambda: os.system("reboot")).start()
        elif path == "/poweroff":
            threading.Timer(0.5, lambda: os.system("poweroff")).start()
        else:
            body = b"unknown"
        self.send_response(200); self._cors()
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def serve_ctrl():
    while True:
        try:
            ThreadingHTTPServer(("127.0.0.1", CTRL_PORT), Ctrl).serve_forever()
        except Exception as e:
            print("[birdknob] ctrl server error: %s" % e, flush=True)
            time.sleep(2)

# ---------- rotary loop ----------
def rotary_loop():
    dt = DevTools()
    while True:
        dev = find_rotary()
        if not dev:
            time.sleep(3)
            continue
        try:
            f = open(dev, "rb", buffering=0)
        except OSError:
            time.sleep(3)
            continue
        print("[birdknob] reading rotary at %s" % dev, flush=True)
        try:
            while True:
                data = f.read(EV_SZ)
                if not data or len(data) < EV_SZ:
                    break
                _, _, typ, code, value = struct.unpack(EV_FMT, data)
                if typ == EV_REL and value != 0:
                    if value > 0:
                        dt.key("ArrowDown", 40)
                    else:
                        dt.key("ArrowUp", 38)
        except OSError:
            pass
        finally:
            try:
                f.close()
            except Exception:
                pass
        time.sleep(1)

if __name__ == "__main__":
    threading.Thread(target=serve_ctrl, daemon=True).start()
    rotary_loop()
