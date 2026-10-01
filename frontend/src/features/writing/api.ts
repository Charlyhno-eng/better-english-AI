import { postJson } from '../shared/api.ts';
import { parseFeedback, type Corrections } from '../conversation/feedback.ts';

export interface WritingMessage { role: 'user' | 'assistant'; content: string; }
export interface WritingTurn { reply: string; corrections: Corrections; }

export async function sendWritingMessage(text: string, history: WritingMessage[], signal: AbortSignal): Promise<WritingTurn> {
  const data = await postJson('/api/writing/turn', { text, history: history.slice(-25) }, signal);
  if (typeof data !== 'object' || data === null || Array.isArray(data)) {
    throw new Error('The backend returned an unexpected writing response. Please try again.');
  }
  const payload = data as Record<string, unknown>;
  const corrections = parseFeedback(payload).corrections;
  if (typeof payload.reply !== 'string' || !payload.reply.trim() || !corrections) {
    throw new Error('The backend returned an unexpected writing response. Please try again.');
  }
  return { reply: payload.reply.trim(), corrections };
}

export async function correctWriting(text: string, signal: AbortSignal): Promise<Corrections> {
  const data = await postJson('/api/writing/corrections', { text }, signal);
  const corrections = parseFeedback({ corrections: data }).corrections;
  if (!corrections) throw new Error('The backend returned unexpected corrections. Please try again.');
  return corrections;
}
