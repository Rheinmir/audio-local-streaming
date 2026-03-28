#!/bin/bash
# Chay tren Mac: bash build-app.sh
set -e
cd "$(dirname "$0")"

echo "=== Build recv ==="
go build -o recv .
echo "OK"

echo "=== Tao AudioStream.app ==="
APP="$HOME/Desktop/AudioStream.app"
MACOS="$APP/Contents/MacOS"
mkdir -p "$MACOS"

cp recv "$MACOS/recv"
chmod +x "$MACOS/recv"

cat > "$MACOS/AudioStream" << 'LAUNCHER'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
pkill -f "AudioStream.app/Contents/MacOS/recv" 2>/dev/null
sleep 0.2

osascript -e 'display notification "Dang lang nghe cong 19999..." with title "AudioStream"'

"$DIR/recv" &
RECV_PID=$!

osascript << EOF
display dialog "AudioStream dang chay
Tren Windows: python send.py 192.168.0.155 --device 18
Latency: ~80ms" buttons {"Stop"} default button "Stop" with title "AudioStream" with icon note
EOF

kill $RECV_PID 2>/dev/null
osascript -e 'display notification "Da dung" with title "AudioStream"'
LAUNCHER
chmod +x "$MACOS/AudioStream"

cat > "$APP/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>AudioStream</string>
  <key>CFBundleExecutable</key><string>AudioStream</string>
  <key>CFBundleIdentifier</key><string>com.local.audiostream</string>
  <key>CFBundleVersion</key><string>2.0</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict>
</plist>
PLIST

echo ""
echo "=== XONG ==="
echo "Double-click AudioStream.app tren Desktop"
