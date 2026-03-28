"""
AudioStream Web Server - HTTPS + AudioWorklet
Usage: python server.py [--device 17] [--https-port 8443] [--wss-port 8765]
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

SAMPLE_RATE  = 48000
CHANNELS     = 2
CHUNK_MS     = 10
CHUNK_FRAMES = SAMPLE_RATE * CHUNK_MS // 1000
SCRIPT_DIR   = Path(__file__).parent

audio_queue  = queue.Queue(maxsize=200)
clients: set = set()

# Runtime config (set in main())
CFG = {}
DEVICES_CACHE = []  # populated once at startup before audio thread starts

# ── Single-instance guard ──
def check_single_instance(port):
    test = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    test.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        test.bind(('127.0.0.1', port)); test.close()
    except OSError:
        print(f"[ERROR] Port {port} busy — another instance running. Kill it first.")
        sys.exit(1)

# ── HTTP/S server ──
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        path = self.path.split('?')[0]
        routes = {
            '/':                (SCRIPT_DIR / 'index.html',          'text/html; charset=utf-8'),
            '/index.html':      (SCRIPT_DIR / 'index.html',          'text/html; charset=utf-8'),
            '/audio-processor.js': (SCRIPT_DIR / 'audio-processor.js', 'application/javascript'),
        }
        if path == '/api/devices':
            self._json(DEVICES_CACHE)
        elif path == '/api/config':
            self._json(CFG)
        elif path in routes:
            fp, ct = routes[path]
            self._serve(fp, ct)
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
            devs.append({
                'index':   d['index'],
                'name':    d['name'],
                'default': default_name in d['name'],
            })
        return devs
    finally:
        p.terminate()

def find_device(p, idx=None):
    if idx is not None:
        try:
            return p.get_device_info_by_index(idx)
        except OSError: pass
        print(f"[WARN] Device {idx} invalid, auto-detecting...")
    # fallback: default loopback
    try:
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        name = p.get_device_info_by_index(wasapi['defaultOutputDevice'])['name']
        for d in p.get_loopback_device_info_generator():
            if name in d['name']: return d
    except: pass
    return next(p.get_loopback_device_info_generator(), None)

def audio_thread(device_idx):
    gc.disable()
    p = pyaudio.PyAudio()
    device = find_device(p, device_idx)
    if device is None:
        print("Khong tim duoc input device!"); import os; os._exit(1)
    dev_rate = int(device.get('defaultSampleRate', SAMPLE_RATE))
    dev_ch   = min(int(device.get('maxInputChannels', CHANNELS)), CHANNELS)
    chunk    = dev_rate * CHUNK_MS // 1000
    print(f"Audio: [{device['index']}] {device['name']} @ {dev_rate}Hz ch={dev_ch}")
    CFG['device_name']   = device['name']
    CFG['device_index']  = device['index']
    CFG['device_rate']   = dev_rate

    cb_count = [0]
    def cb(in_data, fc, ti, st):
        cb_count[0] += 1
        if cb_count[0] <= 5 or cb_count[0] % 500 == 0:
            print(f"[audio cb #{cb_count[0]}] frames={fc} qsize={audio_queue.qsize()} full={audio_queue.full()}")
        if not audio_queue.full():
            audio_queue.put_nowait(bytes(in_data))
        return (None, pyaudio.paContinue)

    stream = p.open(format=pyaudio.paInt16, channels=dev_ch, rate=dev_rate,
                    frames_per_buffer=chunk, input=True,
                    input_device_index=device['index'], stream_callback=cb)
    stream.start_stream()
    import time
    while stream.is_active(): time.sleep(1)

# ── WebSocket ──
async def broadcast_loop():
    loop = asyncio.get_running_loop()
    sent_total = 0
    last_report = asyncio.get_event_loop().time()
    while True:
        try:
            data = await loop.run_in_executor(None, audio_queue.get, True, 0.5)
        except Exception:
            continue

        now = loop.time()
        if now - last_report >= 3.0:
            print(f"[stats] queue={audio_queue.qsize()} clients={len(clients)} sent={sent_total} pkts")
            last_report = now

        if not clients:
            continue
        dead = set()
        for ws in list(clients):
            try:
                await ws.send(data)
                sent_total += 1
            except Exception as e:
                print(f"[send err] {e}")
                dead.add(ws)
        clients.difference_update(dead)

async def ws_handler(websocket):
    clients.add(websocket)
    addr = getattr(websocket, 'remote_address', '?')
    print(f"Client +: {addr}  (total={len(clients)})")
    try:
        async for msg in websocket:
            if isinstance(msg, str) and msg.startswith('ping:'):
                await websocket.send(msg)  # echo back for RTT measurement
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
    parser.add_argument('--device',     type=int, default=5)
    parser.add_argument('--https-port', type=int, default=8443)
    parser.add_argument('--wss-port',   type=int, default=8765)
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()

    if args.list:
        for d in get_devices():
            star = ' *' if d['default'] else ''
            print(f"  [{d['index']}] {d['name']}{star}")
        return

    check_single_instance(args.wss_port)

    # Cache device list before audio thread starts (avoid PyAudio conflict)
    global DEVICES_CACHE
    DEVICES_CACHE = get_devices()

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80)); lan_ip = s.getsockname()[0]; s.close()
    except: lan_ip = 'localhost'

    # Detect Tailscale IP (100.x.x.x range)
    tailscale_ip = None
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ip.startswith('100.') and not ip.startswith('100.0.') and not ip.startswith('100.128.'):
                tailscale_ip = ip
                break
    except: pass
    if not tailscale_ip:
        try:
            import subprocess
            out = subprocess.check_output(['powershell', '-Command',
                "(Get-NetIPAddress -InterfaceAlias 'Tailscale' -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress"],
                stderr=subprocess.DEVNULL).decode().strip()
            if out: tailscale_ip = out
        except: pass

    CFG.update({
        'https_port':   args.https_port,
        'wss_port':     args.wss_port,
        'lan_ip':       lan_ip,
        'tailscale_ip': tailscale_ip,
    })

    print("=" * 50)
    print(f"  AudioStream")
    print(f"  LAN      : https://{ip}:{args.https_port}")
    print(f"  Tailscale: thay {ip} bang Tailscale IP")
    print("=" * 50)

    threading.Thread(target=run_https,    args=(args.https_port,), daemon=True).start()
    threading.Thread(target=audio_thread, args=(args.device,),     daemon=True).start()
    print(f"HTTPS: https://0.0.0.0:{args.https_port}")

    asyncio.run(main_async(args.wss_port))

if __name__ == '__main__':
    main()
