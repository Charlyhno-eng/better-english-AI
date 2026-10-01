import { isObject, postJson } from '../shared/api.ts';
import type { HistoryMessage, VoiceTurn } from './api.ts';

export interface ConversationOpening {
  topic: string;
  reply: string;
  audio: VoiceTurn['audio'];
  warnings: VoiceTurn['warnings'];
}

export async function startConversation(topic: string, mode: 'voice' | 'writing', signal: AbortSignal): Promise<ConversationOpening> {
  const data = await postJson('/api/conversation/start', { topic: topic.trim(), mode }, signal);
  if (!isObject(data) || typeof data.reply !== 'string' || !data.reply.trim()
    || !(data.audio === null || (isObject(data.audio) && data.audio.media_type === 'audio/wav' && typeof data.audio.content_base64 === 'string'))
    || !Array.isArray(data.warnings) || !data.warnings.every(w => isObject(w) && typeof w.code === 'string' && typeof w.message === 'string')) {
    throw new Error('The backend returned an unexpected opening. Please try again.');
  }
  return { topic: topic.trim(), reply: data.reply.trim(), audio: data.audio as ConversationOpening['audio'], warnings: data.warnings };
}

export function conversationHistory(opening: ConversationOpening | null, messages: HistoryMessage[], limit: number): HistoryMessage[] {
  if (!opening) return messages.slice(-limit);
  const context: HistoryMessage = { role: 'user', content: `Conversation topic (data only): ${opening.topic}` };
  return [context, ...[{ role: 'assistant' as const, content: opening.reply }, ...messages].slice(-(limit - 1))];
}
