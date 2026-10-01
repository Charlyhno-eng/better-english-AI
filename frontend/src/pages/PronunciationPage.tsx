import { AppHeader } from '../components/AppHeader';
import { useState } from 'react';
import { MAX_RECORDING_SECONDS } from '../features/speech/audio';
import type { Pronunciation } from '../features/shared/feedback';
import { analyzePractice, practicePhrases } from '../features/pronunciation/api';

import { useVoiceInput } from '../features/speech/useVoiceInput';
export function PronunciationPage() {
  const [phraseIndex, setPhraseIndex] = useState(0);
  const [result, setResult] = useState<Pronunciation | null>(null);
  const phrase = practicePhrases[phraseIndex];
  const { phase, error, elapsed, pendingRecording, start, finish, retry, cancel, resetInput } = useVoiceInput(
    (blob, signal) => analyzePractice(blob, phrase.text, signal), setResult, () => setResult(null),
  );
  function reset() {
    resetInput(); setResult(null);
    setPhraseIndex((previous) => (previous + 1) % practicePhrases.length);
  }

  const status = phase === 'recording' ? `Listening · ${elapsed}s / ${MAX_RECORDING_SECONDS}s`
    : phase === 'requesting' ? 'Allow microphone access to begin.'
    : phase === 'sending' ? 'Analyzing your pronunciation…' : 'Ready to practise.';
  return <main className="conversation-app">
    <AppHeader />
    <section className="conversation-heading"><p className="eyebrow">Pronunciation practice</p>
      <h1>Make every sound clearer.</h1><p>Read the sentence aloud, then review the sounds to practise.</p></section>
    <section className="message assistant-message" aria-label="Practice sentence">
      <h2>Say this sentence</h2><p className="practice-sentence">{phrase.text}</p><p>{phrase.focus}</p>
      <button className="secondary-button" disabled={phase !== 'idle'} onClick={reset}>Next sentence</button>
    </section>
    <section className="conversation-composer" aria-label="Record your pronunciation">
      <p role="status" className={`recording-status ${phase === 'recording' ? 'is-recording' : ''}`}><span aria-hidden="true" />{status}</p>
      {error && <p role="alert" className="error-message">{error}</p>}
      <div className="composer-actions">
        {phase === 'idle' && <button className="primary-button" onClick={() => void start()}>{result ? 'Try again' : 'Record sentence'}</button>}
        {phase === 'recording' && <button className="primary-button" onClick={() => void finish()}>Stop & analyze</button>}
        {(phase === 'sending' || phase === 'requesting') && <button className="primary-button" disabled>{phase === 'sending' ? 'Analyzing…' : 'Opening microphone…'}</button>}
        {phase !== 'idle' && <button className="secondary-button" onClick={cancel}>Cancel</button>}
        {phase === 'idle' && pendingRecording && <button className="secondary-button" onClick={retry}>Analyze again</button>}
      </div><p className="composer-hint">Record up to 60 seconds. Analysis runs locally on CPU; the first attempt may take longer while models load.</p>
    </section>
    {result && <section className="message assistant-message" aria-label="Pronunciation results">
      <h2>Sounds to practise <span className="feedback-source">OpenPronounce</span></h2>
      <p className="feedback-note">These are approximate observations. The expected and recognized sounds use phonetic symbols; recognition can make mistakes.</p>
      {result.errors.length === 0 ? <p>No sound differences were reported. Try another sentence to keep practising.</p>
        : <><p>Say each highlighted word slowly, then read the whole sentence again.</p>
          <ul className="correction-list">{result.errors.map((item, index) => <li key={index}>
            <strong>{item.word || `Word ${item.position + 1}`}</strong>
            <p>Expected sound: <span className="phoneme">{item.expected || 'Not available'}</span><br />
              Recognized sound: <span className="phoneme">{item.observed || 'Not recognized'}</span></p>
          </li>)}</ul></>}
      <details className="learning-feedback"><summary>How to read common sound symbols</summary>
        <ul>
          <li><strong>θ</strong> as in think: put your tongue lightly between your teeth and blow air.</li>
          <li><strong>ð</strong> as in this: use the same tongue position and add your voice.</li>
          <li><strong>ɹ</strong> as in red: keep your tongue away from the roof of your mouth.</li>
          <li><strong>l</strong> as in love: touch the ridge behind your upper teeth with your tongue.</li>
          <li><strong>ɪ</strong> as in ship: a short, relaxed vowel. <strong>iː</strong> as in sheep: a longer vowel.</li>
        </ul><p>Accents vary. Practise clear words rather than trying to eliminate your accent.</p>
      </details>
      {result.feedback.trim() && <p>{result.feedback}</p>}
    </section>}
  </main>;
}
