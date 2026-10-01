import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import { encodeWav, microphoneError } from '../src/features/speech/audio.ts';

test('WAV encoding writes mono 16 kHz PCM16 and clips extreme samples', async () => {
  const blob = encodeWav(new Float32Array([-2, -0.5, 0, 0.5, 2]));
  const buffer = await blob.arrayBuffer();
  const data = new DataView(buffer);
  assert.equal(blob.type, 'audio/wav');
  assert.equal(new TextDecoder().decode(buffer.slice(0, 4)), 'RIFF');
  assert.equal(new TextDecoder().decode(buffer.slice(8, 12)), 'WAVE');
  assert.equal(data.getUint32(4, true), buffer.byteLength - 8);
  assert.equal(data.getUint16(20, true), 1);
  assert.equal(data.getUint16(22, true), 1);
  assert.equal(data.getUint32(24, true), 16000);
  assert.equal(data.getUint16(34, true), 16);
  assert.equal(data.getUint32(40, true), 10);
  assert.deepEqual(Array.from({ length: 5 }, (_, i) => data.getInt16(44 + i * 2, true)),
    [-32768, -16384, 0, 16384, 32767]);
  assert.throws(() => encodeWav(new Float32Array()), /No audio/);
});

test('worklet mixes channels, caps the recording and flushes its final batch', async () => {
  let Processor;
  const messages = [];
  const context = vm.createContext({
    sampleRate: 16000, Float32Array,
    AudioWorkletProcessor: class { port = { postMessage: (data) => messages.push(data) }; },
    registerProcessor: (_, value) => { Processor = value; },
  });
  vm.runInContext(await readFile(new URL('../public/pcm-recorder.worklet.js', import.meta.url), 'utf8'), context);
  const recorder = new Processor({ processorOptions: { maxSeconds: 0.01 } });
  assert.equal(recorder.process([[new Float32Array(128).fill(1), new Float32Array(128).fill(-0.5)]]), true);
  assert.equal(recorder.process([[new Float32Array(128).fill(1), new Float32Array(128).fill(-0.5)]]), false);
  assert.equal(messages[0].samples.length, 160);
  assert.equal(messages[0].samples[0], 0.25);
  assert.equal(messages[1].type, 'done');
  assert.equal(messages[1].atLimit, true);
  recorder.port.onmessage({ data: 'stop' });
  assert.equal(messages.length, 2);
});

test('manual stop flushes PCM once even before a full batch', async () => {
  let Processor;
  const messages = [];
  const context = vm.createContext({ sampleRate: 48000, Float32Array,
    AudioWorkletProcessor: class { port = { postMessage: (data) => messages.push(data) }; },
    registerProcessor: (_, value) => { Processor = value; },
  });
  vm.runInContext(await readFile(new URL('../public/pcm-recorder.worklet.js', import.meta.url), 'utf8'), context);
  const recorder = new Processor({ processorOptions: { maxSeconds: 60 } });
  recorder.process([[new Float32Array(128).fill(0.1)]]);
  recorder.port.onmessage({ data: 'stop' });
  assert.equal(messages[0].samples.length, 128);
  assert.equal(messages[1].atLimit, false);
  assert.equal(recorder.process([]), false);
});

test('microphone permission and missing device errors explain recovery', () => {
  assert.match(microphoneError(new DOMException('', 'NotAllowedError')), /Allow it/);
  assert.match(microphoneError(new DOMException('', 'NotFoundError')), /Connect one/);
  assert.match(microphoneError(new DOMException('', 'NotReadableError')), /Close other apps/);
});

function fakeCapture(t, permission) {
  const track = { stopped: false, onended: null, stop() { this.stopped = true; } };
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
  const contexts = [];
  const nodes = [];
  class Context {
    sampleRate = 16000;
    state = 'running';
    closed = false;
    source = { connect() {}, disconnect() {} };
    audioWorklet = { addModule: async () => {} };
    constructor() { contexts.push(this); }
    async resume() {}
    async close() { this.closed = true; }
    createMediaStreamSource() { return this.source; }
  }
  class Node {
    port = {
      onmessage: null,
      close() {},
      postMessage: () => {
        this.port.onmessage({ data: { type: 'chunk', samples: new Float32Array([0.1, -0.1]) } });
        this.port.onmessage({ data: { type: 'done', atLimit: false } });
      },
    };
    constructor() { nodes.push(this); }
    connect() {}
    disconnect() {}
  }
  const values = { window: { isSecureContext: true, AudioWorkletNode: Node }, AudioContext: Context, AudioWorkletNode: Node };
  for (const [key, value] of Object.entries(values)) {
    const original = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { configurable: true, value });
    t.after(() => { if (original) Object.defineProperty(globalThis, key, original); else delete globalThis[key]; });
  }
  t.mock.getter(globalThis, 'navigator', () => ({ mediaDevices: {
    getUserMedia: permission ?? (async () => stream),
  } }));
  return { stream, track, contexts, nodes };
}

test('stopping a recorder releases tracks and the audio context', async (t) => {
  const { VoiceRecorder } = await import('../src/features/speech/audio.ts');
  const capture = fakeCapture(t);
  const recorder = await VoiceRecorder.start(() => {}, () => {}, new AbortController().signal);
  const wav = await recorder.stop();
  assert.equal(wav.size, 48);
  assert(capture.track.stopped && capture.contexts[0].closed);
  assert.equal(capture.track.onended, null);
  assert.equal(capture.nodes[0].port.onmessage, null);
  recorder.cancel(); // Safe even after a completed stop.
});

test('cancelling a recorder releases resources and rejects pending stop', async (t) => {
  const { VoiceRecorder } = await import('../src/features/speech/audio.ts');
  const capture = fakeCapture(t);
  const recorder = await VoiceRecorder.start(() => {}, () => {}, new AbortController().signal);
  recorder.cancel();
  await assert.rejects(recorder.stop(), { name: 'AbortError' });
  assert(capture.track.stopped && capture.contexts[0].closed);
});

test('microphone denial closes the context', async (t) => {
  const { VoiceRecorder } = await import('../src/features/speech/audio.ts');
  const capture = fakeCapture(t, async () => { throw new DOMException('Denied', 'NotAllowedError'); });
  await assert.rejects(VoiceRecorder.start(() => {}, () => {}, new AbortController().signal), { name: 'NotAllowedError' });
  assert(capture.contexts[0].closed);
});

test('cancel during permission prompt closes any microphone granted later', async (t) => {
  const { VoiceRecorder } = await import('../src/features/speech/audio.ts');
  let grant;
  const permission = new Promise(resolve => { grant = resolve; });
  const capture = fakeCapture(t, () => permission);
  const controller = new AbortController();
  const pending = VoiceRecorder.start(() => {}, () => {}, controller.signal);
  await Promise.resolve();
  controller.abort();
  grant(capture.stream);
  await assert.rejects(pending, { name: 'AbortError' });
  assert(capture.track.stopped && capture.contexts[0].closed);
  assert.equal(capture.nodes.length, 0);
});
