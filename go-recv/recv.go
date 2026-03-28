// AudioStream Receiver — diagnostic mode: log Read() size từ oto
package main

import (
	"encoding/binary"
	"fmt"
	"net"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/hajimehoshi/oto/v2"
)

const (
	sampleRate = 48000
	channels   = 2
	port       = 19999
)

type ringBuf struct {
	mu      sync.Mutex
	data    []byte
	maxSize int
	reads   int
}

func newRingBuf(maxBytes int) *ringBuf {
	return &ringBuf{maxSize: maxBytes}
}

func (r *ringBuf) push(b []byte) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if len(r.data)+len(b) > r.maxSize {
		r.data = r.data[len(r.data)+len(b)-r.maxSize:]
	}
	r.data = append(r.data, b...)
}

func (r *ringBuf) lenBytes() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.data)
}

func (r *ringBuf) Read(p []byte) (int, error) {
	r.mu.Lock()
	r.reads++
	readN := r.reads
	have := len(r.data)
	r.mu.Unlock()

	// Log 5 lan dau de biet oto request bao nhieu
	if readN <= 5 {
		bpms := sampleRate * channels * 2 / 1000
		fmt.Fprintf(os.Stderr, "[Read #%d] requested=%d bytes (%.1fms) | have=%d bytes (%.1fms)\n",
			readN, len(p), float64(len(p))/float64(bpms),
			have, float64(have)/float64(bpms))
	}

	r.mu.Lock()
	n := copy(p, r.data)
	r.data = r.data[n:]
	r.mu.Unlock()

	for i := n; i < len(p); i++ {
		p[i] = 0
	}
	return len(p), nil
}

func main() {
	bpms := sampleRate * channels * 2 / 1000

	ctx, ready, err := oto.NewContext(sampleRate, channels, 2)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Loi audio:", err)
		os.Exit(1)
	}
	<-ready

	// Pre-fill 3 giay de chac chan du cho bat ky buffer size nao
	preFill := 3000 * bpms
	buf := newRingBuf(5000 * bpms)
	player := ctx.NewPlayer(buf)

	conn, _ := net.ListenPacket("udp", fmt.Sprintf("0.0.0.0:%d", port))
	defer conn.Close()

	fmt.Fprintf(os.Stderr, "Pre-filling 3s (%d bytes)...\n", preFill)
	pkt := make([]byte, 65536)
	conn.SetReadDeadline(time.Now().Add(20 * time.Second))
	for buf.lenBytes() < preFill {
		n, _, err := conn.ReadFrom(pkt)
		if err != nil {
			if ne, ok := err.(net.Error); ok && ne.Timeout() {
				fmt.Fprintln(os.Stderr, "Timeout.")
				os.Exit(1)
			}
			continue
		}
		if n > 4 {
			buf.push(pkt[4:n])
			pct := buf.lenBytes() * 100 / preFill
			fmt.Fprintf(os.Stderr, "\r%d%%", pct)
		}
	}
	conn.SetReadDeadline(time.Time{})
	fmt.Fprintf(os.Stderr, "\nBat dau play (buf=%dms)\n", buf.lenBytes()/bpms)

	player.Play()

	go func() {
		for {
			time.Sleep(200 * time.Millisecond)
			if !player.IsPlaying() {
				player.Play()
			}
		}
	}()

	go func() {
		for {
			conn.SetReadDeadline(time.Now().Add(time.Second))
			n, _, err := conn.ReadFrom(pkt)
			if err != nil {
				continue
			}
			if n > 4 {
				_ = binary.BigEndian.Uint32(pkt[:4])
				buf.push(pkt[4:n])
			}
		}
	}()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	player.Close()
}
