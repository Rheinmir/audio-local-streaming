# Audio Local Streaming

Stream âm thanh từ Windows PC sang Mac qua LAN hoặc Tailscale, với độ trễ thấp (~10–30ms network).

## Cách hoạt động

```
Game/Browser → Windows Mixer → WASAPI Loopback → WebSocket (WSS) → Browser Mac → AudioWorklet → Loa
```

## Yêu cầu (Windows)

```bash
pip install pyaudiowpatch websockets
```

## Chạy server

```bash
python web/server.py            # auto-detect device
python web/server.py --device 5 # chỉ định device
python web/server.py --list     # xem danh sách device
```

## Truy cập từ Mac

1. Mở `https://<Windows-IP>:8443` trên Safari/Chrome
2. Chấp nhận cert warning (lần đầu)
3. Vào `https://<Windows-IP>:8765` → chấp nhận cert (cho WSS)
4. Quay lại trang, nhấn **PLAY**

### Tailscale
Thay IP bằng Tailscale IP của Windows (ví dụ `100.83.152.126`).

## Tạo SSL cert (Windows, dùng WSL)

```bash
wsl bash -c "openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout /mnt/d/AudioStream/web/key.pem \
  -out /mnt/d/AudioStream/web/cert.pem \
  -days 365 -sha256 -subj '/CN=AudioStream' \
  -addext 'subjectAltName=IP:<LAN-IP>,IP:<Tailscale-IP>,IP:127.0.0.1,DNS:localhost'"
```

## Shortcut Desktop (Windows)

Double-click `AudioStream.vbs` để start server ngầm + mở browser tự động.

## Cấu trúc

```
web/
  server.py          # HTTPS + WSS server, WASAPI loopback capture
  index.html         # Web player (AudioWorklet, VU meter, latency)
  audio-processor.js # AudioWorklet processor (128-sample buffer)
send.py              # UDP sender (alternative, low latency LAN only)
go-recv/             # Go receiver cho Mac (alternative UDP)
AudioStream.vbs      # Shortcut launcher (web server)
tray.ps1             # Tray icon script
```

## Ports

| Port | Dùng cho |
|------|----------|
| 8443 | HTTPS (web player) |
| 8765 | WSS (audio stream) |
