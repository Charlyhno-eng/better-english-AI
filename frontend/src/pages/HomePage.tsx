import { useVoiceInput } from '../features/conversation/useVoiceInput';
import { Link } from 'react-router';
import { useEffect, useRef, useState } from 'react';
import { replyAudioBlob, sendVoiceMessage, type HistoryMessage, type VoiceTurn } from '../features/conversation/api';
import { MAX_RECORDING_SECONDS } from '../features/conversation/audio';
import { TurnFeedback } from '../features/conversation/TurnFeedback';
import { ReplyAudio } from '../features/conversation/ReplyAudio';

interface DisplayTurn { result: VoiceTurn; audio: Blob | null; }

export function HomePage() {
  const [turns, setTurns] = useState<DisplayTurn[]>([]);
  const transcriptEnd = useRef<HTMLDivElement>(null);
  const { phase, error, elapsed, pendingRecording, start, finish, retry, cancel, resetInput } = useVoiceInput(
    (blob, signal) => {
      const history: HistoryMessage[] = turns.flatMap(({ result }) => [
        { role: 'user' as const, content: result.transcript },
        { role: 'assistant' as const, content: result.reply },
      ]);
      return sendVoiceMessage(blob, history, signal);
    },
    (result) => {
      let audio: Blob | null = null;
      try { if (result.audio) audio = replyAudioBlob(result.audio); } catch {
        result.warnings.push({ code: 'playback_unavailable', message: 'The voice reply could not be played. The text is available below.' });
      }
      setTurns((previous) => [...previous, { result, audio }]);
    },
  );
  useEffect(() => {
    transcriptEnd.current?.scrollIntoView?.({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'end' });
  }, [turns.length, phase]);
  function reset() { resetInput(); setTurns([]); }

  const status = phase === 'requesting' ? 'Allow microphone access to begin.'
    : phase === 'recording' ? `Listening · ${elapsed}s / ${MAX_RECORDING_SECONDS}s`
    : phase === 'sending' ? 'Your English partner is preparing a reply…'
    : 'Ready when you are.';

  return (
    <main className="conversation-app">
      <header className="app-header">
        <a className="wordmark" href="/">Better English <span>AI</span></a>
        <Link to="/setup">Setup</Link>
        <Link to="/writing">Writing practice</Link>
        <Link to="/pronunciation">Pronunciation practice</Link>
        <button className="secondary-button" onClick={reset} disabled={!turns.length && phase === 'idle' && !pendingRecording}>
          New conversation
        </button>
      </header>
      <section className="conversation-heading">
        <p className="eyebrow">A little practice, every day</p>
        <h1>Let’s talk in English.</h1>
        <p>Speak naturally. Your AI partner will listen and keep the conversation going.</p>
        <p>First visit? <Link to="/setup">Set up your models and API key</Link>.</p>
      </section>
      <section className="conversation-thread" aria-label="Conversation">
        {!turns.length && <div className="welcome-message">
          <span className="partner-avatar" aria-hidden="true">AI</span>
          <div><h2>What’s on your mind?</h2>
            <p>Tell me about your day, something you enjoy, or a place you’d love to visit.</p>
          </div>
        </div>}
        {turns.map(({ result, audio }, index) => <div className="conversation-turn" key={index}>
          <article className="message user-message">
            <h2>You</h2><p>{result.transcript}</p>
          </article>
          <article className="message assistant-message">
            <h2>Your English partner</h2><p>{result.reply}</p>
            {audio && <ReplyAudio blob={audio} paused={phase !== 'idle'} />}
            <TurnFeedback turn={result} />
            {result.warnings.length > 0 && <details className="turn-notices">
              <summary>Some feedback or audio is unavailable</summary>
              <ul>{result.warnings.map((warning, i) => <li key={i}>{warning.message}</li>)}</ul>
            </details>}
          </article>
        </div>)}
        <div ref={transcriptEnd} />
      </section>
      <section className="conversation-composer" aria-label="Record a message">
        <p className={`recording-status ${phase === 'recording' ? 'is-recording' : ''}`} role="status" aria-live="polite">
          <span aria-hidden="true" />{status}
        </p>
        {error && <p className="error-message" role="alert">{error}</p>}
        <div className="composer-actions">
          {phase === 'idle' && <button className="primary-button" onClick={() => void start()}>
            {turns.length ? 'Record a reply' : 'Start speaking'}
          </button>}
          {phase === 'recording' && <button className="primary-button" onClick={() => void finish()}>Stop & send</button>}
          {phase === 'sending' && <button className="primary-button" disabled>Preparing reply…</button>}
          {phase === 'requesting' && <button className="primary-button" disabled>Opening microphone…</button>}
          {phase !== 'idle' && <button className="secondary-button" onClick={cancel}>
            {phase === 'sending' ? 'Cancel request' : 'Cancel recording'}
          </button>}
          {phase === 'idle' && pendingRecording && <button className="secondary-button" onClick={retry}>Send again</button>}
        </div>
        <p className="composer-hint">{phase === 'recording'
          ? 'Stop & send when you’re finished. Your message sends automatically at 60 seconds.'
          : 'Your microphone is used only while recording. You can replay each voice reply.'}</p>
      </section>
    </main>
  );
}
