#!/bin/bash
# AudioStream Receiver - Mac setup

# Cài Homebrew nếu chưa có
if ! command -v brew &>/dev/null; then
    echo "Cài Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# Apple Silicon path
eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null || true
eval "$(/usr/local/bin/brew shellenv)" 2>/dev/null || true

# Cài Go nếu chưa có
if ! command -v go &>/dev/null; then
    echo "Cài Go..."
    brew install go
    # Load Go path ngay sau khi cài
    export PATH="$PATH:$(brew --prefix go)/bin"
fi

echo "Go version: $(go version)"

cd "$(dirname "$0")"

# Reset go.mod để tránh version conflict
echo "Setup module..."
rm -f go.mod go.sum
go mod init audiostream-recv
go get github.com/hajimehoshi/oto/v2@latest
go mod tidy

echo "Build..."
go build -o recv . && echo "Build OK: $(pwd)/recv" || {
    echo "Build thất bại. Thử chạy trực tiếp:"
    echo "  go run recv.go"
    exit 1
}

echo ""
echo "=== XONG ==="
echo "Chạy: $(pwd)/recv"
