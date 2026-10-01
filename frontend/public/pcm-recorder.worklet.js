// Capture mono PCM in bounded batches without playing microphone audio back.
class PCMRecorder extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.limit = Math.floor(options.processorOptions.maxSeconds * sampleRate);
    this.frames = 0;
    this.buffer = new Float32Array(2048);
    this.offset = 0;
    this.finished = false;
    this.port.onmessage = ({ data }) => {
      if (data === 'stop') this.finish(false);
    };
  }

  flush() {
    if (!this.offset) return;
    const chunk = this.buffer.slice(0, this.offset);
    this.port.postMessage({ type: 'chunk', samples: chunk }, [chunk.buffer]);
    this.offset = 0;
  }

  finish(atLimit) {
    if (this.finished) return;
    this.finished = true;
    this.flush();
    this.port.postMessage({ type: 'done', atLimit });
  }

  process(inputs) {
    if (this.finished) return false;
    const channels = inputs[0];
    if (!channels?.length) return true;
    for (let i = 0; i < channels[0].length && this.frames < this.limit; i++) {
      let sample = 0;
      for (const channel of channels) sample += channel[i];
      this.buffer[this.offset++] = sample / channels.length;
      this.frames++;
      if (this.offset === this.buffer.length) this.flush();
    }
    if (this.frames >= this.limit) this.finish(true);
    return !this.finished;
  }
}
registerProcessor('pcm-recorder', PCMRecorder);
