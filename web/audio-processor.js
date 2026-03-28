// AudioWorklet Processor — nhận PCM Int16 từ main thread, output float32
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buf = [];          // mảng Float32Array chunks
    this._bufSamples = 0;    // tổng số sample đang chờ

    this.port.onmessage = (e) => {
      const int16 = new Int16Array(e.data);
      const frames = int16.length / 2; // stereo
      const left  = new Float32Array(frames);
      const right = new Float32Array(frames);
      for (let i = 0; i < frames; i++) {
        left[i]  = int16[i * 2]     / 32768.0;
        right[i] = int16[i * 2 + 1] / 32768.0;
      }
      this._buf.push({ left, right });
      this._bufSamples += frames;
      // giới hạn buffer ~2s
      while (this._bufSamples > sampleRate * 2 && this._buf.length > 0) {
        this._bufSamples -= this._buf[0].left.length;
        this._buf.shift();
      }
    };
  }

  process(inputs, outputs) {
    const out    = outputs[0];
    const left   = out[0];
    const right  = out[1] || out[0];
    const needed = left.length; // thường là 128 samples

    let filled = 0;
    while (filled < needed && this._buf.length > 0) {
      const chunk  = this._buf[0];
      const avail  = chunk.left.length;
      const take   = Math.min(needed - filled, avail);
      left.set(chunk.left.subarray(0, take), filled);
      right.set(chunk.right.subarray(0, take), filled);
      filled += take;

      if (take === avail) {
        this._buf.shift();
        this._bufSamples -= avail;
      } else {
        this._buf[0] = {
          left:  chunk.left.subarray(take),
          right: chunk.right.subarray(take),
        };
        this._bufSamples -= take;
      }
    }
    // silence nếu buffer cạn
    for (let i = filled; i < needed; i++) {
      left[i] = 0;
      right[i] = 0;
    }
    return true;
  }
}

registerProcessor('pcm-processor', PCMProcessor);
