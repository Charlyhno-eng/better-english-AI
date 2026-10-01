import test from 'node:test';
import assert from 'node:assert/strict';
import { correctWriting } from '../src/features/writing/api.ts';

test('writing uses the shared correction shape and sends only text', async () => {
  const previous = globalThis.fetch;
  const signal = new AbortController().signal;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/writing/corrections');
    assert.equal(options.signal, signal);
    assert.deepEqual(JSON.parse(options.body), { text: 'Hello!' });
    return Response.json({ corrected_text: 'Hello!', items: [] });
  };
  try { assert.deepEqual(await correctWriting('Hello!', signal), { corrected_text: 'Hello!', items: [] }); }
  finally { globalThis.fetch = previous; }
});

test('writing surfaces provider failures and rejects invalid correction payloads', async () => {
  const previous = globalThis.fetch;
  try {
    globalThis.fetch = async () => Response.json({ error: { message: 'GLM unavailable.' } }, { status: 503 });
    await assert.rejects(correctWriting('Hello!', new AbortController().signal), /GLM unavailable/);
    globalThis.fetch = async () => Response.json({ corrected_text: 'Hello!', items: [{ category: 'unknown' }] });
    await assert.rejects(correctWriting('Hello!', new AbortController().signal), /unexpected corrections/);
  } finally { globalThis.fetch = previous; }
});

test('shared transport propagates cancellation without retry', async () => {
  const previous = globalThis.fetch;
  let calls = 0;
  const controller = new AbortController();
  controller.abort();
  globalThis.fetch = async (_url, options) => { calls++; options.signal.throwIfAborted(); };
  try {
    await assert.rejects(correctWriting('Hello!', controller.signal), { name: 'AbortError' });
    assert.equal(calls, 1);
  } finally { globalThis.fetch = previous; }
});
