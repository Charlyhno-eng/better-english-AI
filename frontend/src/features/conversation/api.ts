import { postJson, audioBase64, isObject } from '../shared/api.ts';
import { parseFeedback, type Corrections, type Pronunciation } from './feedback.ts';

export interface HistoryMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface VoiceTurn {
  corrections: Corrections | null;
  pronunciation: Pronunciation | null;
  pronunciation_feedback: string | null;
  transcript: string;
  reply: string;
  audio: { media_type: string; content_base64: string } | null;
  warnings: { code: string; message: string }[];
}

export async function sendVoiceMessage(
  recording: Blob, history: HistoryMessage[], signal: AbortSignal,
): Promise<VoiceTurn> {
  const data = await postJson('/api/conversation/turn', {
    audio_base64: await audioBase64(recording), media_type: 'audio/wav', history: history.slice(-10),
  }, signal);
  if (!isVoiceTurn(data)) throw new Error('The backend returned an unexpected response. Please try again.');
  return { ...data, ...parseFeedback(data as unknown as Record<string, unknown>) };
}

function isVoiceTurn(value: unknown): value is VoiceTurn {
  return isObject(value) && typeof value.transcript === 'string' && typeof value.reply === 'string'
    && (value.audio === null || (isObject(value.audio) && value.audio.media_type === 'audio/wav'
      && typeof value.audio.content_base64 === 'string'))
    && Array.isArray(value.warnings) && value.warnings.every((warning) =>
      isObject(warning) && typeof warning.code === 'string' && typeof warning.message === 'string');
}

export function replyAudioBlob(audio: NonNullable<VoiceTurn['audio']>): Blob {
  const binary = atob(audio.content_base64);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return new Blob([bytes], { type: audio.media_type });
}
