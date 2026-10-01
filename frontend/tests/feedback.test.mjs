import assert from 'node:assert/strict';
import test from 'node:test';
import { parseFeedback, correctionLabels } from '../src/features/conversation/feedback.ts';
import { sendVoiceMessage } from '../src/features/conversation/api.ts';

const corrections = { corrected_text: 'I went there.', items: [
  { category: 'grammar', original: 'goed', replacement: 'went', explanation: 'Use the irregular past tense.' },
  { category: 'spelling', original: 'teh', replacement: 'the', explanation: 'Check the spelling.' },
  { category: 'vocabulary', original: 'big rain', replacement: 'heavy rain', explanation: 'Use this collocation.' },
  { category: 'word_choice', original: 'make homework', replacement: 'do homework', explanation: 'Use do.' },
  { category: 'style', original: 'very good', replacement: 'excellent', explanation: 'An optional alternative.' },
] };
const pronunciation = { reference_inferred: true, feedback: 'A possible sound difference.', errors: [
  { word: 'there', position: 2, expected: 'ð', observed: null },
] };

test('all language correction categories and independent pronunciation sources survive parsing', () => {
  assert.deepEqual(parseFeedback({ corrections, pronunciation, pronunciation_feedback: ' Practise this sound. ' }),
    { corrections, pronunciation, pronunciation_feedback: 'Practise this sound.' });
  assert.equal(correctionLabels.style, 'Optional style');
});

test('empty analyses remain distinct from unavailable analyses', () => {
  const result = parseFeedback({ corrections: { corrected_text: 'Hello', items: [] },
    pronunciation: { reference_inferred: false, feedback: '', errors: [] }, pronunciation_feedback: null });
  assert.deepEqual(result.corrections.items, []);
  assert.deepEqual(result.pronunciation.errors, []);
  assert.deepEqual(parseFeedback({}), { corrections: null, pronunciation: null, pronunciation_feedback: null });
});

test('malformed language feedback preserves valid independent pronunciation data', () => {
  const result = parseFeedback({ corrections: { corrected_text: 'Hello', items: [{ category: 'invented' }] },
    pronunciation, pronunciation_feedback: 'Practice tip' });
  assert.equal(result.corrections, null);
  assert.deepEqual(result.pronunciation, pronunciation);
});

test('malformed pronunciation data and non-string feedback do not crash rendering', () => {
  assert.deepEqual(parseFeedback({ corrections, pronunciation: { errors: 'bad' }, pronunciation_feedback: {} }),
    { corrections, pronunciation: null, pronunciation_feedback: null });
  assert.equal(parseFeedback({ pronunciation, pronunciation_feedback: {} }).pronunciation_feedback, null);
});

test('voice response exposes validated teaching fields without dropping useful conversation', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => Response.json({
    transcript: 'I goed there.', reply: 'What did you do?', audio: null, warnings: [],
    corrections, pronunciation, pronunciation_feedback: 'Practice tip',
  }));
  const result = await sendVoiceMessage(new Blob(['wav']), [], new AbortController().signal);
  assert.deepEqual(result.corrections, corrections);
  assert.deepEqual(result.pronunciation, pronunciation);
  assert.equal(result.pronunciation_feedback, 'Practice tip');
});
