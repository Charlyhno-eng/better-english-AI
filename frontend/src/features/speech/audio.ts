export const MAX_RECORDING_SECONDS = 60;
const TARGET_SAMPLE_RATE = 16_000;

/** Encode mono samples as the PCM16 WAV accepted by the backend. */
export function encodeWav(samples: Float32Array): Blob {
  if (!samples.length) throw new Error('No audio was recorded. Please try again.');
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
  };
  text(0, 'RIFF');
  view.setUint32(4, buffer.byteLength - 8, true);
  text(8, 'WAVE');
  text(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, TARGET_SAMPLE_RATE, true);
  view.setUint32(28, TARGET_SAMPLE_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const sample = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
  }
  return new Blob([buffer], { type: 'audio/wav' });
}

export class VoiceRecorder {
  private chunks: Float32Array[] = [];
  private finished = false;
  private cancelled = false;
  private released = false;
  private stream: MediaStream;
  private context: AudioContext;
  private source: MediaStreamAudioSourceNode;
  private node: AudioWorkletNode;
  private resolveDone!: () => void;
  private done = new Promise<void>((resolve) => { this.resolveDone = resolve; });

  private constructor(
    stream: MediaStream,
    context: AudioContext,
    source: MediaStreamAudioSourceNode,
    node: AudioWorkletNode,
    onLimit: () => void,
    onFailure: () => void,
  ) {
    this.stream = stream;
    this.context = context;
    this.source = source;
    this.node = node;
    node.port.onmessage = ({ data }) => {
      if (this.cancelled) return;
      if (data.type === 'chunk') this.chunks.push(data.samples);
      if (data.type === 'done') {
        this.finished = true;
        this.resolveDone();
        if (data.atLimit) onLimit();
      }
    };
    node.onprocessorerror = onFailure;
    for (const track of stream.getAudioTracks()) track.onended = onFailure;
    context.onstatechange = () => {
      if (context.state === 'suspended' && !this.finished && !this.cancelled) onFailure();
    };
  }

  static async start(onLimit: () => void, onFailure: () => void, signal: AbortSignal): Promise<VoiceRecorder> {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
      throw new Error('Microphone recording needs HTTPS or localhost and a browser with Web Audio support.');
    }
    // Create/resume during the button gesture, before awaiting microphone permission.
    const context = new AudioContext();
    let stream: MediaStream | undefined;
    const abort = () => {
      stream?.getTracks().forEach((track) => track.stop());
      void context.close().catch(() => {});
    };
    signal.addEventListener('abort', abort, { once: true });
    try {
      signal.throwIfAborted();
      await context.resume();
      signal.throwIfAborted();
      const permission = navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      // Permission prompts cannot be dismissed programmatically. Release any late grant.
      void permission.then((granted) => {
        if (signal.aborted) granted.getTracks().forEach((track) => track.stop());
      }, () => {});
      stream = await permission;
      signal.throwIfAborted();
      await context.audioWorklet.addModule(`${import.meta.env?.BASE_URL ?? '/'}pcm-recorder.worklet.js`);
      signal.throwIfAborted();
      const source = context.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(context, 'pcm-recorder', {
        processorOptions: { maxSeconds: MAX_RECORDING_SECONDS },
      });
      const recorder = new VoiceRecorder(stream, context, source, node, onLimit, onFailure);
      source.connect(node);
      // The processor writes no output: destination drives capture without microphone echo.
      node.connect(context.destination);
      return recorder;
    } catch (error) {
      stream?.getTracks().forEach((track) => track.stop());
      await context.close().catch(() => {});
      throw error;
    } finally {
      signal.removeEventListener('abort', abort);
    }
  }

  private release() {
    if (this.released) return;
    this.released = true;
    this.context.onstatechange = null;
    this.node.onprocessorerror = null;
    this.node.port.onmessage = null;
    this.source.disconnect();
    this.node.disconnect();
    this.node.port.close();
    for (const track of this.stream.getTracks()) {
      track.onended = null;
      track.stop();
    }
    void this.context.close().catch(() => {});
  }

  cancel() {
    if (this.cancelled) return;
    this.cancelled = true;
    this.chunks = [];
    this.resolveDone();
    this.release();
  }

  async stop(): Promise<Blob> {
    if (!this.finished && !this.cancelled) this.node.port.postMessage('stop');
    await this.done;
    if (this.cancelled) throw new DOMException('Recording cancelled', 'AbortError');
    this.finished = true;
    this.release();
    const length = this.chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    if (!length) throw new Error('No audio was recorded. Please try again.');
    const samples = new Float32Array(length);
    let offset = 0;
    for (const chunk of this.chunks) {
      samples.set(chunk, offset);
      offset += chunk.length;
    }
    this.chunks = [];
    if (this.context.sampleRate === TARGET_SAMPLE_RATE) return encodeWav(samples);
    // Let the browser resample with its audio resampler rather than changing a WAV header.
    const outputLength = Math.min(TARGET_SAMPLE_RATE * MAX_RECORDING_SECONDS,
      Math.floor(length * TARGET_SAMPLE_RATE / this.context.sampleRate));
    if (!outputLength) throw new Error('The recording was too short. Please try again.');
    const offline = new OfflineAudioContext(1, outputLength, TARGET_SAMPLE_RATE);
    const input = offline.createBuffer(1, length, this.context.sampleRate);
    input.copyToChannel(samples, 0);
    const source = offline.createBufferSource();
    source.buffer = input;
    source.connect(offline.destination);
    source.start();
    const result = await offline.startRendering();
    if (this.cancelled) throw new DOMException('Recording cancelled', 'AbortError');
    return encodeWav(result.getChannelData(0));
  }
}

export function microphoneError(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError') return 'Microphone access was denied. Allow it in your browser and try again.';
    if (error.name === 'NotFoundError') return 'No microphone was found. Connect one and try again.';
    if (error.name === 'NotReadableError') return 'Your microphone is unavailable. Close other apps using it and try again.';
  }
  return error instanceof Error ? error.message : 'Recording failed. Please try again.';
}
