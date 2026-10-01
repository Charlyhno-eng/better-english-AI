import { postJson } from '../shared/api.ts';
import { parseFeedback, type Corrections } from '../conversation/feedback.ts';

export async function correctWriting(text: string, signal: AbortSignal): Promise<Corrections> {
  const data = await postJson('/api/writing/corrections', { text }, signal);
  const corrections = parseFeedback({ corrections: data }).corrections;
  if (!corrections) throw new Error('The backend returned unexpected corrections. Please try again.');
  return corrections;
}
