"""
AudioStream - Sender (Windows)
Usage:
  python send.py <MAC_IP>
  python send.py <IP> --device 17
  python send.py --list
"""
import socket
import struct
import sys
import argparse
import time
import queue
import threading
import gc

try:
    import pyaudiowpatch as pyaudio
except ImportError:
    print("pip install pyaudiowpatch")
    sys.exit(1)

SAMPLE_RATE  = 48000
CHANNELS     = 2
CHUNK_MS     = 20                                  # 20ms chunk - on dinh hon 10ms
CHUNK_FRAMES = SAMPLE_RATE * CHUNK_MS // 1000      # 960 frames
PORT         = 19999

send_queue = queue.Queue(maxsize=200)


def get_loopback_devices(p):
    try:
        return list(p.get_loopback_device_info_generator())
    except Exception:
        return []


def find_default_loopback(p):
    try:
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_name = p.get_device_info_by_index(wasapi['defaultOutputDevice'])['name']
        for d in p.get_loopback_device_info_generator():
            if default_name in d['name']:
                return d
        devs = get_loopback_devices(p)
        return devs[0] if devs else None
    except Exception:
        return None


def list_devices(p):
    devs = get_loopback_devices(p)
    if not devs:
        print("Khong tim thay WASAPI loopback device.")
        return
    print("\n=== WASAPI Loopback devices ===")
    for d in devs:
        print(f"  [{d['index']}] {d['name']}")
    try:
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        name = p.get_device_info_by_index(wasapi['defaultOutputDevice'])['name']
        print(f"\nDefault output: {name}")
    except Exception:
        pass


def sender_thread(sock, target, port):
    """Thread rieng chi lam nhiem vu send UDP — raw PCM, no header."""
    while True:
        data = send_queue.get()
        if data is None:
            break
        try:
            sock.sendto(data, (target, port))
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('target', nargs='?', default='255.255.255.255')
    parser.add_argument('--device', type=int, default=None)
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()

    p = pyaudio.PyAudio()

    if args.list:
        list_devices(p)
        p.terminate()
        return

    device = (p.get_device_info_by_index(args.device)
              if args.device is not None else find_default_loopback(p))
    if device is None:
        print("Khong tim duoc loopback device.")
        list_devices(p)
        p.terminate()
        return

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)  # 1MB send buffer
    if args.target == '255.255.255.255':
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    print(f"Device  : [{device['index']}] {device['name']}")
    print(f"Target  : {args.target}:{PORT}")
    print(f"Format  : {SAMPLE_RATE}Hz stereo {CHUNK_MS}ms/chunk")
    print("Ctrl+C de dung\n")

    # Giam GIL switching va tat GC de tranh pause
    sys.setswitchinterval(0.0001)
    gc.disable()

    # Start send thread
    t = threading.Thread(target=sender_thread, args=(sock, args.target, PORT), daemon=True)
    t.start()

    # Audio callback chi push vao queue, khong lam gi nang
    def audio_callback(in_data, frame_count, time_info, status):
        if not send_queue.full():
            send_queue.put_nowait(bytes(in_data))
        return (None, pyaudio.paContinue)

    try:
        stream = p.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            frames_per_buffer=CHUNK_FRAMES,
            input=True,
            input_device_index=device['index'],
            stream_callback=audio_callback,
        )
        stream.start_stream()
        seq_report = 0
        while stream.is_active():
            time.sleep(5)
            seq_report += 1
            print(f"Streaming... q={send_queue.qsize()}")
    except KeyboardInterrupt:
        print("\nDa dung.")
    finally:
        try:
            stream.stop_stream()
            stream.close()
        except Exception:
            pass
        send_queue.put(None)
        p.terminate()
        sock.close()


if __name__ == '__main__':
    main()
