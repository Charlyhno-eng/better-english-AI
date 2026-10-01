import { isObject } from './api.ts';

export const correctionLabels = {
  grammar: 'Grammar', spelling: 'Spelling', vocabulary: 'Vocabulary',
  word_choice: 'Word choice', style: 'Optional style',
} as const;

export interface Correction {
  category: keyof typeof correctionLabels;
  original: string;
  replacement: string;
  explanation: string;
}
export interface Corrections { corrected_text: string; items: Correction[]; }
export interface PronunciationError {
  word: string; position: number; expected: string; observed: string | null;
}
export interface Pronunciation {
  reference_inferred: boolean;
  errors: PronunciationError[];
  feedback: string;
}

/** Validate secondary fields independently: bad feedback must not discard a conversation. */
export function parseFeedback(value: Record<string, unknown>): {
  corrections: Corrections | null; pronunciation: Pronunciation | null; pronunciation_feedback: string | null;
} {
  const corrections = value.corrections;
  const pronunciation = value.pronunciation;
  const validCorrections = isObject(corrections) && typeof corrections.corrected_text === 'string'
    && Array.isArray(corrections.items) && corrections.items.every((item) => isObject(item)
      && typeof item.category === 'string' && Object.hasOwn(correctionLabels, item.category)
      && typeof item.original === 'string' && typeof item.replacement === 'string'
      && typeof item.explanation === 'string');
  const validPronunciation = isObject(pronunciation) && typeof pronunciation.reference_inferred === 'boolean'
    && typeof pronunciation.feedback === 'string' && Array.isArray(pronunciation.errors)
    && pronunciation.errors.every((item) => isObject(item) && typeof item.word === 'string'
      && typeof item.position === 'number' && Number.isInteger(item.position) && item.position >= 0
      && typeof item.expected === 'string' && (item.observed === null || typeof item.observed === 'string'));
  return {
    corrections: validCorrections ? corrections as unknown as Corrections : null,
    pronunciation: validPronunciation ? pronunciation as unknown as Pronunciation : null,
    pronunciation_feedback: validPronunciation && typeof value.pronunciation_feedback === 'string'
      ? value.pronunciation_feedback.trim() || null : null,
  };
}
