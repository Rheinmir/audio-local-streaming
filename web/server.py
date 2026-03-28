"""
AudioStream Web Server - HTTPS + AudioWorklet
Usage: python server.py [--device 5] [--https-port 8443] [--wss-port 8765]
       python server.py --list
"""
import asyncio, threading, queue, argparse, sys, ssl, gc, socket, json
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

try:
    import websockets
except ImportError:
    print("pip install websockets pyaudiowpatch"); sys.exit(1)
try:
    import pyaudiowpatch as pyaudio
except ImportError:
    print("pip install pyaudiowpatch"); sys.exit(1)

CHUNK_MS   = 10
CHANNELS   = 2
SCRIPT_DIR = Path(__file__).parent

audio_queue   = queue.Queue(maxsize=200)
clients: set  = set()
CFG           = {}
DEVICES_CACHE = []

# Signal audio thread to restart with new device
_audio_restart = threading.Event()
_target_device = [None]  # [device_index or None]
_audio_thread  = [None]

# ── Single-instance guard ──
def check_single_instance(port):
    test = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    test.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        test.bind(('127.0.0.1', port)); test.close()
    except OSError:
        print(f"[ERROR] Port {port} busy — another instance running.")
        sys.exit(1)

# ── HTTP/S server ──
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/api/devices':
            self._json(DEVICES_CACHE)
        elif path == '/api/config':
            self._json(CFG)
        elif path in ('/', '/index.html'):
            self._serve(SCRIPT_DIR / 'index.html', 'text/html; charset=utf-8')
        elif path == '/audio-processor.js':
            self._serve(SCRIPT_DIR / 'audio-processor.js', 'application/javascript')
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        path = self.path.split('?')[0]
        if path == '/api/device':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
            idx = int(body.get('index', -1))
            _target_device[0] = idx
            _audio_restart.set()
            self._json({'ok': True, 'index': idx})
        else:
            self.send_response(404); self.end_headers()

    def _serve(self, fp: Path, ct: str):
        try:
            data = fp.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', ct)
            self.send_header('Content-Length', len(data))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_response(404); self.end_headers()

    def _json(self, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(data))
        self.end_headers()
        self.wfile.write(data)

def run_https(port):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(SCRIPT_DIR / 'cert.pem', SCRIPT_DIR / 'key.pem')
    srv = HTTPServer(('0.0.0.0', port), Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    srv.serve_forever()

# ── Audio ──
def get_devices():
    p = pyaudio.PyAudio()
    try:
        devs = []
        try:
            wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_name = p.get_device_info_by_index(wasapi['defaultOutputDevice'])['name']
        except: default_name = ''
        for d in p.get_loopback_device_info_generator():
            devs.append({'index': d['index'], 'name': d['name'],
                         'default': default_name in d['name']})
        return devs
    finally:
        p.terminate()

def find_device(p, idx=None):
    if idx is not None and idx >= 0:
        try:
            return p.get_device_info_by_index(idx)
        except OSError:
            print(f"[WARN] Device {idx} invalid, auto-detecting...")
    try:
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        name = p.get_device_info_by_index(wasapi['defaultOutputDevice'])['name']
        for d in p.get_loopback_device_info_generator():
            if name in d['name']: return d
    except: pass
    return next(p.get_loopback_device_info_generator(), None)

def audio_thread(device_idx):
    import time
    while True:
        _audio_restart.clear()
        gc.disable()
        p = pyaudio.PyAudio()
        device = find_device(p, device_idx)
        if device is None:
            print("[ERROR] Khong tim duoc device!"); time.sleep(3)
            device_idx = _target_device[0]
            continue

        dev_rate = int(device.get('defaultSampleRate', 48000))
        dev_ch   = min(int(device.get('maxInputChannels', CHANNELS)), CHANNELS)
        chunk    = dev_rate * CHUNK_MS // 1000
        print(f"[audio] START [{device['index']}] {device['name']} @ {dev_rate}Hz")
        CFG.update({'device_name': device['name'], 'device_index': device['index'],
                    'device_rate': dev_rate})

        # Flush stale queue
        while not audio_queue.empty():
            try: audio_queue.get_nowait()
            except: break

        # Notify clients of new sample rate
        CFG['device_rate'] = dev_rate

        def cb(in_data, fc, ti, st):
            if _audio_restart.is_set():
                return (None, pyaudio.paComplete)
            if not audio_queue.full():
                audio_queue.put_nowait(bytes(in_data))
            return (None, pyaudio.paContinue)

        try:
            stream = p.open(format=pyaudio.paInt16, channels=dev_ch, rate=dev_rate,
                            frames_per_buffer=chunk, input=True,
                            input_device_index=device['index'], stream_callback=cb)
            stream.start_stream()
            while stream.is_active() and not _audio_restart.is_set():
                time.sleep(0.2)
            stream.stop_stream()
            stream.close()
        except Exception as e:
            print(f"[audio] Error: {e}")
        finally:
            p.terminate()

        if _audio_restart.is_set():
            device_idx = _target_device[0]
            print(f"[audio] Switching to device {device_idx}...")
        else:
            break

# ── WebSocket ──
async def broadcast_loop():
    loop = asyncio.get_running_loop()
    while True:
        try:
            data = await loop.run_in_executor(None, audio_queue.get, True, 0.5)
        except Exception:
            continue
        if not clients: continue
        dead = set()
        for ws in list(clients):
            try: await ws.send(data)
            except Exception as e:
                print(f"[send err] {e}"); dead.add(ws)
        clients.difference_update(dead)

def detect_connection_type(ip: str) -> dict:
    """Return connection type info for a given client IP."""
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip)
        # LAN ranges
        lan_ranges = ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '127.0.0.0/8']
        for r in lan_ranges:
            if addr in ipaddress.ip_network(r):
                return {'type': 'lan', 'label': 'LAN nội bộ', 'internet': False}
        # Tailscale range
        if addr in ipaddress.ip_network('100.64.0.0/10'):
            # Check if direct or relay
            relay = True
            try:
                import subprocess
                out = subprocess.check_output(
                    ['tailscale', 'status', '--json'],
                    stderr=subprocess.DEVNULL, timeout=3).decode()
                import json as _json
                data = _json.loads(out)
                for peer in data.get('Peer', {}).values():
                    peer_ips = peer.get('TailscaleIPs', [])
                    if ip in peer_ips:
                        relay = not peer.get('Direct', False)
                        break
            except: pass
            if relay:
                return {'type': 'tailscale_relay', 'label': 'Tailscale (qua relay — tốn băng thông)', 'internet': True}
            else:
                return {'type': 'tailscale_direct', 'label': 'Tailscale Direct (P2P — không tốn băng thông)', 'internet': False}
    except: pass
    return {'type': 'unknown', 'label': 'Không xác định', 'internet': None}

async def ws_handler(websocket):
    clients.add(websocket)
    addr = getattr(websocket, 'remote_address', ('?', 0))
    ip = addr[0] if isinstance(addr, tuple) else str(addr)
    print(f"Client +: {addr}  (total={len(clients)})")
    try:
        # Send connection type info immediately
        conn_info = detect_connection_type(ip)
        conn_info['ip'] = ip
        await websocket.send(json.dumps({'type': 'conn_info', **conn_info}))

        async for msg in websocket:
            if isinstance(msg, str) and msg.startswith('ping:'):
                await websocket.send(msg)
    finally:
        clients.discard(websocket)
        print(f"Client -: {addr}  (total={len(clients)})")

async def main_async(wss_port):
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(SCRIPT_DIR / 'cert.pem', SCRIPT_DIR / 'key.pem')
    asyncio.create_task(broadcast_loop())
    async with websockets.serve(ws_handler, '0.0.0.0', wss_port, ssl=ssl_ctx):
        print(f"WSS  : wss://0.0.0.0:{wss_port}")
        await asyncio.Future()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--device',     type=int, default=-1)
    parser.add_argument('--https-port', type=int, default=8443)
    parser.add_argument('--wss-port',   type=int, default=8765)
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()

    if args.list:
        for d in get_devices():
            print(f"  [{d['index']}] {d['name']}{'  *' if d['default'] else ''}")
        return

    check_single_instance(args.wss_port)

    global DEVICES_CACHE
    DEVICES_CACHE = get_devices()

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80)); lan_ip = s.getsockname()[0]; s.close()
    except: lan_ip = 'localhost'

    tailscale_ip = None
    try:
        import subprocess
        out = subprocess.check_output(
            ['powershell', '-Command',
             "(Get-NetIPAddress -InterfaceAlias 'Tailscale' -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress"],
            stderr=subprocess.DEVNULL).decode().strip()
        if out: tailscale_ip = out
    except: pass

    CFG.update({'https_port': args.https_port, 'wss_port': args.wss_port,
                'lan_ip': lan_ip, 'tailscale_ip': tailscale_ip})

    print("=" * 50)
    print(f"  AudioStream")
    print(f"  LAN      : https://{lan_ip}:{args.https_port}")
    if tailscale_ip:
        print(f"  Tailscale: https://{tailscale_ip}:{args.https_port}")
    print("=" * 50)

    _target_device[0] = args.device
    threading.Thread(target=run_https,    args=(args.https_port,), daemon=True).start()
    threading.Thread(target=audio_thread, args=(args.device,),     daemon=True).start()

    asyncio.run(main_async(args.wss_port))

if __name__ == '__main__':
    main()
