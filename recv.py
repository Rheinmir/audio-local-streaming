"""
AudioStream - Receiver (chạy trên Mac)
Usage: python recv.py
       python recv.py --buffer 30   # tăng buffer nếu bị giật (ms)
"""
import sounddevice as sd
import socket
import struct
import numpy as np
import threading
import argparse
import time
from collections import deque

SAMPLE_RATE = 48000
CHANNELS = 2
CHUNK_MS = 10
CHUNK_SAMPLES = SAMPLE_RATE * CHUNK_MS // 1000  # 480 samples
PORT = 19999


def main():
    parser = argparse.ArgumentParser(description='AudioStream Receiver')
    parser.add_argument('--buffer', type=int, default=30,
                        help='Jitter buffer size (ms, mặc định 30ms)')
    parser.add_argument('--device', type=int, default=None,
                        help='Output device index')
    parser.add_argument('--list', action='store_true', help='Liệt kê output devices')
    args = parser.parse_args()

    if args.list:
        print("\n=== Output devices ===")
        for i, d in enumerate(sd.query_devices()):
            if d['max_output_channels'] > 0:
                print(f"  [{i}] {d['name']}")
        return

    # Jitter buffer: số chunks = buffer_ms / chunk_ms
    buffer_chunks = max(1, args.buffer // CHUNK_MS)
    buffer = deque(maxlen=buffer_chunks * 4)
    buffer_lock = threading.Lock()

    # Setup UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', PORT))
    sock.settimeout(0.1)

    stats = {'recv': 0, 'drop': 0, 'underrun': 0}
    running = True

    def recv_thread():
        expected_seq = None
        while running:
            try:
                data, addr = sock.recvfrom(65536)
                if len(data) < 4:
                    continue
                seq = struct.unpack('>I', data[:4])[0]
                pcm16 = np.frombuffer(data[4:], dtype=np.int16)

                # Reshape và convert to float32
                if len(pcm16) == CHUNK_SAMPLES * CHANNELS:
                    chunk = pcm16.reshape(CHUNK_SAMPLES, CHANNELS).astype(np.float32) / 32767.0
                    with buffer_lock:
                        buffer.append(chunk)
                    stats['recv'] += 1
                    expected_seq = (seq + 1) & 0xFFFFFFFF
            except socket.timeout:
                continue
            except Exception as e:
                print(f"recv error: {e}")

    recv_t = threading.Thread(target=recv_thread, daemon=True)
    recv_t.start()

    # Pre-fill jitter buffer trước khi bắt đầu play
    print(f"Listening on port {PORT}...")
    print(f"Jitter buffer: {args.buffer}ms ({buffer_chunks} chunks)")
    print("Chờ audio...", end='', flush=True)

    timeout = time.time() + 10
    while len(buffer) < buffer_chunks and time.time() < timeout:
        time.sleep(0.01)

    if len(buffer) == 0:
        print("\nKhông nhận được audio. Kiểm tra IP và firewall máy Windows.")
        running = False
        return

    print(f"\nĐang phát audio... Ctrl+C để dừng\n")

    silence = np.zeros((CHUNK_SAMPLES, CHANNELS), dtype=np.float32)

    def playback_callback(outdata, frames, time_info, status):
        with buffer_lock:
            if buffer:
                outdata[:] = buffer.popleft()
            else:
                outdata[:] = silence
                stats['underrun'] += 1

    try:
        with sd.OutputStream(
            device=args.device,
            channels=CHANNELS,
            samplerate=SAMPLE_RATE,
            blocksize=CHUNK_SAMPLES,
            dtype='float32',
            callback=playback_callback,
            latency='low',
        ):
            last_print = time.time()
            while True:
                sd.sleep(1000)
                now = time.time()
                if now - last_print >= 5:
                    buf_ms = len(buffer) * CHUNK_MS
                    print(f"recv={stats['recv']} | underrun={stats['underrun']} | buf={buf_ms}ms")
                    last_print = now
    except KeyboardInterrupt:
        print("\nĐã dừng.")
    finally:
        running = False
        sock.close()


if __name__ == '__main__':
    main()
