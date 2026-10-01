import test from 'node:test';
import assert from 'node:assert/strict';
import { sendWritingMessage } from '../src/features/writing/api.ts';

test('writing uses the shared correction shape and sends only text', async () => {
  const previous = globalThis.fetch;
  const signal = new AbortController().signal;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/writing/turn');
    assert.equal(options.signal, signal);
    assert.deepEqual(JSON.parse(options.body), { text: 'Hello!', history: [] });
    return Response.json({ reply: 'Hi!', corrections: { corrected_text: 'Hello!', items: [] } });
  };
  try { assert.deepEqual(await sendWritingMessage('Hello!', [], signal), { reply: 'Hi!', corrections: { corrected_text: 'Hello!', items: [] } }); }
  finally { globalThis.fetch = previous; }
});

test('writing surfaces provider failures and rejects invalid correction payloads', async () => {
  const previous = globalThis.fetch;
  try {
    globalThis.fetch = async () => Response.json({ error: { message: 'GLM unavailable.' } }, { status: 503 });
    await assert.rejects(sendWritingMessage('Hello!', [], new AbortController().signal), /GLM unavailable/);
    globalThis.fetch = async () => Response.json({ reply: 'Hi!', corrections: { corrected_text: 'Hello!', items: [{ category: 'unknown' }] } });
    await assert.rejects(sendWritingMessage('Hello!', [], new AbortController().signal), /unexpected writing response/);
  } finally { globalThis.fetch = previous; }
});

test('shared transport propagates cancellation without retry', async () => {
  const previous = globalThis.fetch;
  let calls = 0;
  const controller = new AbortController();
  controller.abort();
  globalThis.fetch = async (_url, options) => { calls++; options.signal.throwIfAborted(); };
  try {
    await assert.rejects(sendWritingMessage('Hello!', [], controller.signal), { name: 'AbortError' });
    assert.equal(calls, 1);
  } finally { globalThis.fetch = previous; }
});


test('writing chat sends only the latest 25 messages and returns conversation and corrections', async (t) => {
  const history = Array.from({ length: 30 }, (_, i) => ({
    role: i % 2 ? 'assistant' : 'user', content: `Message ${i}`,
  }));
  const signal = new AbortController().signal;
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/writing/turn');
    assert.equal(options.signal, signal);
    assert.deepEqual(JSON.parse(options.body), { text: 'Hello!', history: history.slice(-25) });
    return Response.json({ reply: ' How are you? ', corrections: { corrected_text: 'Hello!', items: [] } });
  });
  assert.deepEqual(await sendWritingMessage('Hello!', history, signal), {
    reply: 'How are you?', corrections: { corrected_text: 'Hello!', items: [] },
  });
});

test('writing chat rejects incomplete replies and preserves safe provider errors', async (t) => {
  const signal = new AbortController().signal;
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json({ reply: 'Hi!' }));
  await assert.rejects(sendWritingMessage('Hello!', [], signal), /unexpected writing response/);
  fetch.mock.mockImplementation(async () => Response.json({
    error: { message: 'GLM unavailable.' },
  }, { status: 503 }));
  await assert.rejects(sendWritingMessage('Hello!', [], signal), /GLM unavailable/);
});
