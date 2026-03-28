// AudioWorklet Processor with jitter buffer
class PCMProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this._buf = [];
    this._bufSamples = 0;
    this._ready = false;
    this._TARGET_MS = (options && options.processorOptions && options.processorOptions.bufferMs) || 40;
    this._MIN_MS    = Math.max(10, this._TARGET_MS / 3);

    this.port.onmessage = (e) => {
      const int16 = new Int16Array(e.data);
      const frames = int16.length / 2;
      const left  = new Float32Array(frames);
      const right = new Float32Array(frames);
      for (let i = 0; i < frames; i++) {
        left[i]  = int16[i * 2]     / 32768.0;
        right[i] = int16[i * 2 + 1] / 32768.0;
      }
      this._buf.push({ left, right });
      this._bufSamples += frames;

      // Cap buffer at 2s to avoid unbounded growth
      while (this._bufSamples > sampleRate * 2 && this._buf.length > 0) {
        this._bufSamples -= this._buf[0].left.length;
        this._buf.shift();
      }

      // Start playing once we have enough buffer
      const targetSamples = sampleRate * this._TARGET_MS / 1000;
      if (!this._ready && this._bufSamples >= targetSamples) {
        this._ready = true;
      }
    };
  }

  process(inputs, outputs) {
    const out    = outputs[0];
    const left   = out[0];
    const right  = out[1] || out[0];
    const needed = left.length;

    // Buffer ran dry — pause and wait for refill
    if (this._bufSamples < needed) {
      this._ready = false;
    }

    if (!this._ready) {
      // Output silence while buffering
      left.fill(0); right.fill(0);
      return true;
    }

    let filled = 0;
    while (filled < needed && this._buf.length > 0) {
      const chunk = this._buf[0];
      const avail = chunk.left.length;
      const take  = Math.min(needed - filled, avail);
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

    for (let i = filled; i < needed; i++) { left[i] = 0; right[i] = 0; }
    return true;
  }
}

registerProcessor('pcm-processor', PCMProcessor);
