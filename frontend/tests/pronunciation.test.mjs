import test from 'node:test';
import assert from 'node:assert/strict';
import { analyzePractice, practicePhrases } from '../src/features/pronunciation/api.ts';

test('practice sends the displayed reference and WAV directly to OpenPronounce', async () => {
  const previous = globalThis.fetch;
  const signal = new AbortController().signal;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/pronunciation/analyze');
    assert.equal(options.signal, signal);
    const payload = JSON.parse(options.body);
    assert.equal(payload.reference_text, practicePhrases[0].text);
    assert.equal(payload.audio_base64, 'AQID');
    assert.equal(payload.media_type, 'audio/wav');
    assert.equal(payload.history, undefined);
    return Response.json({ reference_inferred: false, errors: [], feedback: 'Keep practising.' });
  };
  try {
    const result = await analyzePractice(new Blob([new Uint8Array([1, 2, 3])]), practicePhrases[0].text, signal);
    assert.equal(result.feedback, 'Keep practising.');
  } finally { globalThis.fetch = previous; }
});

test('unavailable or malformed analysis is surfaced for retry', async () => {
  const previous = globalThis.fetch;
  try {
    globalThis.fetch = async () => Response.json({ error: { message: 'Analysis unavailable.' } }, { status: 503 });
    await assert.rejects(analyzePractice(new Blob(['audio']), 'Hello.', new AbortController().signal), /Analysis unavailable/);
    globalThis.fetch = async () => Response.json({ errors: 'bad' });
    await assert.rejects(analyzePractice(new Blob(['audio']), 'Hello.', new AbortController().signal), /unexpected pronunciation/);
  } finally { globalThis.fetch = previous; }
});
