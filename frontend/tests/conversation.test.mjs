import assert from 'node:assert/strict';
import test from 'node:test';
import { encodeWav } from '../src/features/speech/audio.ts';
import { replyAudioBlob, streamVoiceMessage } from '../src/features/conversation/api.ts';

const voiceMessage = (recording, history, signal) => streamVoiceMessage(recording, history, signal, () => {}, () => {});

const turn = { transcript: 'Hello!', reply: 'How are you?', audio: null, warnings: [], corrections: null, pronunciation: null, pronunciation_feedback: null };

test('voice API encodes audio losslessly and sends only recent history', async (t) => {
  const wav = encodeWav(new Float32Array(10000));
  const signal = new AbortController().signal;
  const history = Array.from({ length: 14 }, (_, i) => ({ role: 'user', content: String(i) }));
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/conversation/turn/stream');
    assert.equal(options.signal, signal);
    assert.equal(options.method, 'POST');
    const payload = JSON.parse(options.body);
    assert.equal(payload.media_type, 'audio/wav');
    assert.deepEqual(payload.history, history.slice(-10));
    assert.deepEqual(Buffer.from(payload.audio_base64, 'base64'), Buffer.from(await wav.arrayBuffer()));
    return new Response(JSON.stringify({ type: 'done', data: turn }) + '\n');
  });
  assert.deepEqual(await voiceMessage(wav, history, signal), turn);
});

test('safe backend and non-JSON proxy errors are readable', async (t) => {
  const wav = encodeWav(new Float32Array([0]));
  const mock = t.mock.method(globalThis, 'fetch', async () =>
    Response.json({ error: { code: 'provider_unavailable', message: 'The provider is unavailable.' } }, { status: 503 }));
  await assert.rejects(voiceMessage(wav, [], new AbortController().signal), /provider is unavailable/);
  mock.mock.mockImplementation(async () => new Response('Bad Gateway', { status: 502 }));
  await assert.rejects(voiceMessage(wav, [], new AbortController().signal), /HTTP 502/);
});

test('unexpected successful responses are rejected and aborts propagate', async (t) => {
  const mock = t.mock.method(globalThis, 'fetch', async () => Response.json({ transcript: 'Hi' }));
  const wav = encodeWav(new Float32Array([0]));
  await assert.rejects(voiceMessage(wav, [], new AbortController().signal), /unexpected voice reply/);
  mock.mock.mockImplementation(async () => { throw new DOMException('Aborted', 'AbortError'); });
  await assert.rejects(voiceMessage(wav, [], new AbortController().signal), { name: 'AbortError' });
});

test('reply audio preserves WAV bytes', async () => {
  const wav = encodeWav(new Float32Array([0, 1]));
  const bytes = Buffer.from(await wav.arrayBuffer());
  const decoded = replyAudioBlob({ media_type: 'audio/wav', content_base64: bytes.toString('base64') });
  assert.equal(decoded.type, 'audio/wav');
  assert.deepEqual(Buffer.from(await decoded.arrayBuffer()), bytes);
});

test('stream delivers reply and WAV fragments before optional feedback completes', async (t) => {
  const { streamVoiceMessage } = await import('../src/features/conversation/api.ts');
  const wav = encodeWav(new Float32Array([0, 1]));
  const audio = { media_type: 'audio/wav', content_base64: Buffer.from(await wav.arrayBuffer()).toString('base64') };
  const encoder = new TextEncoder();
  let writer;
  const stream = new ReadableStream({ start(controller) { writer = controller; } });
  const signal = new AbortController().signal;
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    assert.equal(path, '/api/conversation/turn/stream');
    assert.equal(options.signal, signal);
    assert.equal(JSON.parse(options.body).history.length, 10);
    return new Response(stream, { headers: { 'Content-Type': 'application/x-ndjson' } });
  });
  const received = [];
  const pending = streamVoiceMessage(wav, Array.from({ length: 12 }, () => ({ role: 'user', content: 'Hi' })), signal,
    (value, stage) => received.push([stage, value]), (value) => received.push(['audio', value]));
  const reply = JSON.stringify({ type: 'reply', data: { ...turn, reply: 'Café?' } }) + '\n';
  const bytes = encoder.encode(reply);
  // Fragment both the JSON and a multi-byte Unicode character across reads.
  const split = bytes.indexOf(0xc3) + 1;
  writer.enqueue(bytes.slice(0, split));
  writer.enqueue(bytes.slice(split));
  writer.enqueue(encoder.encode(JSON.stringify({ type: 'audio', data: audio }) + '\n'));
  for (let i = 0; i < 30 && received.length < 2; i++) await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(received.map(([stage]) => stage), ['reply', 'audio']);
  assert.equal(received[0][1].reply, 'Café?');
  assert.deepEqual(received[1][1], audio);
  const final = { ...turn, reply: 'Café?', audio };
  writer.enqueue(encoder.encode(JSON.stringify({ type: 'feedback', data: final }) + '\n'
    + JSON.stringify({ type: 'done', data: final }) + '\n'));
  writer.close();
  assert.deepEqual(await pending, final);
  assert.deepEqual(received.map(([stage]) => stage), ['reply', 'audio', 'feedback']);
});

test('stream rejects incomplete, malformed and safely reported failures', async (t) => {
  const { streamVoiceMessage } = await import('../src/features/conversation/api.ts');
  const wav = encodeWav(new Float32Array([0]));
  const mock = t.mock.method(globalThis, 'fetch', async () => new Response(''));
  const send = () => streamVoiceMessage(wav, [], new AbortController().signal, () => {}, () => {});
  await assert.rejects(send(), /interrupted/);
  for (const line of ['not json', JSON.stringify({ type: 'audio', data: {} }), JSON.stringify({ type: 'done', data: {} })]) {
    mock.mock.mockImplementation(async () => new Response(line + '\n'));
    await assert.rejects(send(), /unexpected voice reply/);
  }
  mock.mock.mockImplementation(async () => new Response(JSON.stringify({ type: 'error', data: { message: 'Safe error' } }) + '\n'));
  await assert.rejects(send(), /Safe error/);
  mock.mock.mockImplementation(async () => Response.json({ error: { message: 'Missing key' } }, { status: 503 }));
  await assert.rejects(send(), /Missing key/);
  mock.mock.mockImplementation(async () => new Response('Bad Gateway', { status: 502 }));
  await assert.rejects(send(), /HTTP 502/);
});

test('stream cancellation prevents late turn updates and cancels the reader', async (t) => {
  const { streamVoiceMessage } = await import('../src/features/conversation/api.ts');
  const controller = new AbortController();
  let cancelled = false;
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(writer) { writer.enqueue(encoder.encode(JSON.stringify({ type: 'reply', data: turn }) + '\n')); },
    cancel() { cancelled = true; },
  });
  t.mock.method(globalThis, 'fetch', async () => new Response(stream));
  const pending = streamVoiceMessage(encodeWav(new Float32Array([0])), [], controller.signal,
    () => controller.abort(), () => assert.fail('No audio after cancellation'));
  await assert.rejects(pending, { name: 'AbortError' });
  assert(cancelled);
});

test('streamed playback schedules fragments consecutively and stops queued audio', async (t) => {
  const { StreamingAudio } = await import('../src/features/conversation/StreamingAudio.ts');
  const sources = [];
  let context;
  class Context {
    state = 'running'; currentTime = 0; destination = {};
    constructor() { context = this; }
    async resume() {}
    async close() { this.state = 'closed'; }
    async decodeAudioData() { return { duration: .1 }; }
    createBufferSource() {
      const source = { connect() {}, disconnect() {}, start(time) { this.time = time; }, stop() { this.stopped = true; } };
      sources.push(source);
      return source;
    }
  }
  const original = Object.getOwnPropertyDescriptor(globalThis, 'AudioContext');
  Object.defineProperty(globalThis, 'AudioContext', { configurable: true, value: Context });
  t.after(() => { if (original) Object.defineProperty(globalThis, 'AudioContext', original); else delete globalThis.AudioContext; });
  const states = [];
  const playback = new StreamingAudio((playing) => states.push(playing));
  const audio = { media_type: 'audio/wav', content_base64: 'AAAA' };
  playback.append(audio); playback.append(audio);
  for (let i = 0; i < 30 && sources.length < 2; i++) await new Promise(resolve => setImmediate(resolve));
  assert.equal(sources.length, 2);
  assert.equal(sources[1].time, sources[0].time + .1);
  playback.stop(); playback.stop(); playback.append(audio);
  await new Promise(resolve => setImmediate(resolve));
  assert(sources.every(source => source.stopped));
  assert.equal(context.state, 'closed');
  assert.equal(sources.length, 2);
  assert.equal(states.at(-1), false);
});
