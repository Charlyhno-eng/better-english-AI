import { postJson, audioBase64 } from '../shared/api.ts';
import { parseFeedback, type Pronunciation } from '../conversation/feedback.ts';

export const practicePhrases = [
  { text: 'I think three things are worth trying.', focus: 'Practise the th sounds in think, three and things.' },
  { text: 'We really love learning new words.', focus: 'Practise the r and l sounds in really, love and learning.' },
  { text: 'The ship leaves after we finish eating.', focus: 'Compare the short vowel in ship with the long vowel in leaves.' },
  { text: 'Please bring your best friend to the park.', focus: 'Practise consonant groups in please, bring and best friend.' },
] as const;

export async function analyzePractice(recording: Blob, reference: string, signal: AbortSignal): Promise<Pronunciation> {
  const data = await postJson('/api/pronunciation/analyze', {
    audio_base64: await audioBase64(recording), media_type: 'audio/wav', reference_text: reference,
  }, signal);
  const result = parseFeedback({ pronunciation: data }).pronunciation;
  if (!result) throw new Error('The backend returned an unexpected pronunciation result. Please try again.');
  return result;
}
