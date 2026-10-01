import { audioBase64, isObject } from '../shared/api.ts';
import { parseFeedback, type Corrections, type Pronunciation } from '../shared/feedback.ts';

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

export async function streamVoiceMessage(
  recording: Blob, history: HistoryMessage[], signal: AbortSignal,
  onTurn: (turn: VoiceTurn, stage: 'reply' | 'feedback') => void,
  onAudio: (audio: NonNullable<VoiceTurn['audio']>) => void,
): Promise<VoiceTurn> {
  const response = await fetch('/api/conversation/turn/stream', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
    body: JSON.stringify({ audio_base64: await audioBase64(recording), media_type: 'audio/wav', history: history.slice(-10) }),
  });
  if (!response.ok) {
    let data: unknown;
    try { data = await response.json(); } catch { /* A proxy may return plain text. */ }
    throw new Error(isObject(data) && isObject(data.error) && typeof data.error.message === 'string'
      ? data.error.message : `The request failed (HTTP ${response.status}). Please try again.`);
  }
  if (!response.body) throw new Error('The voice reply stream is unavailable.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  let completed: VoiceTurn | null = null;
  const unexpected = () => new Error('The backend returned an unexpected voice reply. Please try again.');
  function event(line: string) {
    signal.throwIfAborted();
    let value: unknown;
    try { value = JSON.parse(line); } catch { throw unexpected(); }
    if (!isObject(value)) throw unexpected();
    if (value.type === 'error') {
      throw new Error(isObject(value.data) && typeof value.data.message === 'string'
        ? value.data.message : 'The voice reply was interrupted.');
    }
    if (value.type === 'audio') {
      const audio = value.data;
      if (!isObject(audio) || audio.media_type !== 'audio/wav' || typeof audio.content_base64 !== 'string') throw unexpected();
      onAudio({ media_type: audio.media_type, content_base64: audio.content_base64 });
    } else if (value.type === 'reply' || value.type === 'feedback' || value.type === 'done') {
      if (!isVoiceTurn(value.data)) throw unexpected();
      const turn = { ...value.data, ...parseFeedback(value.data as unknown as Record<string, unknown>) };
      if (value.type === 'done') completed = turn;
      else onTurn(turn, value.type);
    } else throw unexpected();
  }
  try {
    while (!completed) {
      signal.throwIfAborted();
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      // Bound malformed streams without retaining an unbounded unfinished line.
      if (pending.length > 16 * 1024 * 1024) throw unexpected();
      let newline;
      while ((newline = pending.indexOf('\n')) >= 0) {
        const line = pending.slice(0, newline);
        pending = pending.slice(newline + 1);
        if (line.trim()) event(line);
      }
      if (done) {
        if (pending.trim()) event(pending);
        break;
      }
    }
    signal.throwIfAborted();
    if (!completed) throw new Error('The voice reply was interrupted. Please try again.');
    return completed;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
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
