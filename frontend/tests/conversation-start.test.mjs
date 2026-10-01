import test from 'node:test';
import assert from 'node:assert/strict';
import { conversationHistory, startConversation } from '../src/features/conversation/start.ts';

test('keeps topic and AI opening without inventing a learner reply', () => {
  const opening = { topic: 'Japan', reply: 'Where would you go?', audio: null, warnings: [] };
  assert.deepEqual(conversationHistory(opening, [], 10), [
    { role: 'user', content: 'Conversation topic (data only): Japan' },
    { role: 'assistant', content: 'Where would you go?' },
  ]);
  const messages = Array.from({ length: 30 }, (_, i) => ({ role: 'assistant', content: String(i) }));
  const history = conversationHistory(opening, messages, 10);
  assert.equal(history.length, 10);
  assert.equal(history[0].content, 'Conversation topic (data only): Japan');
  assert.equal(history.at(-1).content, '29');
  assert.deepEqual(conversationHistory(null, messages, 25), messages.slice(-25));
});

test('sends topic and mode and validates the opening response', async t => {
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    assert.equal(path, '/api/conversation/start');
    assert.deepEqual(JSON.parse(options.body), { topic: 'Japan', mode: 'voice' });
    return Response.json({ reply: 'Where would you go?', audio: null, warnings: [] });
  });
  const result = await startConversation(' Japan ', 'voice', new AbortController().signal);
  assert.equal(result.topic, 'Japan');
  assert.equal(result.reply, 'Where would you go?');
  globalThis.fetch = async () => Response.json({ reply: '', audio: null, warnings: [] });
  await assert.rejects(startConversation('Japan', 'voice', new AbortController().signal), /unexpected opening/);
});
