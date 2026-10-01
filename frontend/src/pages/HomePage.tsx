import { AppHeader } from '../components/AppHeader';
import { useVoiceInput } from '../features/conversation/useVoiceInput';
import { Link } from 'react-router';
import { useEffect, useRef, useState } from 'react';
import { replyAudioBlob, streamVoiceMessage, type HistoryMessage, type VoiceTurn } from '../features/conversation/api';
import { StreamingAudio } from '../features/conversation/StreamingAudio';
import { MAX_RECORDING_SECONDS } from '../features/conversation/audio';
import { TurnFeedback } from '../features/conversation/TurnFeedback';
import { ReplyAudio } from '../features/conversation/ReplyAudio';

interface DisplayTurn { result: VoiceTurn; audio: Blob | null; autoPlay: boolean; }

export function HomePage() {
  const [turns, setTurns] = useState<DisplayTurn[]>([]);
  const [incoming, setIncoming] = useState<VoiceTurn | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [playing, setPlaying] = useState(false);
  const playback = useRef<StreamingAudio | null>(null);
  const transcriptEnd = useRef<HTMLDivElement>(null);
  const { phase, error, elapsed, pendingRecording, start, finish, retry, cancel, resetInput } = useVoiceInput(
    async (blob, signal) => {
      // Also initialize playback for a retry, which has no new recording gesture.
      if (!playback.current) { try { playback.current = new StreamingAudio(setPlaying); } catch { /* Replay remains available. */ } }
      const abort = () => { playback.current?.stop(); playback.current = null; setIncoming(null); setReviewing(false); };
      signal.addEventListener('abort', abort, { once: true });
      const history: HistoryMessage[] = turns.flatMap(({ result }) => [
        { role: 'user' as const, content: result.transcript },
        { role: 'assistant' as const, content: result.reply },
      ]);
      try {
        return await streamVoiceMessage(blob, history, signal,
          (turn, stage) => { if (!signal.aborted) { setIncoming(turn); setReviewing(stage === 'feedback'); } },
          (audio) => { if (!signal.aborted) playback.current?.append(audio); });
      } catch (failure) {
        abort();
        throw failure;
      } finally {
        signal.removeEventListener('abort', abort);
      }
    },
    (result) => {
      let audio: Blob | null = null;
      try { if (result.audio) audio = replyAudioBlob(result.audio); } catch {
        result.warnings.push({ code: 'playback_unavailable', message: 'The voice reply could not be played. The text is available below.' });
      }
      setTurns((previous) => [...previous, { result, audio, autoPlay: !playback.current }]);
      setIncoming(null);
      setReviewing(false);
    },
    () => {
      playback.current?.stop(); playback.current = null;
      setIncoming(null); setReviewing(false);
      try { playback.current = new StreamingAudio(setPlaying); } catch { /* Replay remains available. */ }
    },
  );
  useEffect(() => () => playback.current?.stop(), []);
  useEffect(() => {
    transcriptEnd.current?.scrollIntoView?.({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'end' });
  }, [turns.length, phase, incoming?.reply]);
  function reset() { resetInput(); playback.current?.stop(); playback.current = null; setIncoming(null); setReviewing(false); setTurns([]); }
  function cancelRequest() { cancel(); playback.current?.stop(); playback.current = null; setIncoming(null); setReviewing(false); }

  const status = phase === 'requesting' ? 'Allow microphone access to begin.'
    : phase === 'recording' ? `Listening · ${elapsed}s / ${MAX_RECORDING_SECONDS}s`
    : phase === 'sending' ? reviewing ? 'Reviewing your pronunciation…' : incoming ? 'Your English partner is speaking…' : 'Your English partner is preparing a reply…'
    : 'Ready when you are.';

  return (
    <main className="conversation-app">
      <AppHeader />
      <section className="conversation-heading">
        <p className="eyebrow">A little practice, every day</p>
        <h1>Let’s talk in English.</h1>
        <p>Speak naturally. Your AI partner will listen and keep the conversation going.</p>
        <p>First visit? <Link to="/setup">Set up your models and API key</Link>.</p>
      </section>
      <section className="conversation-thread" aria-label="Conversation">
        <div className="thread-toolbar">
          <span className="thread-label">Your conversation space</span>
          <button className="secondary-button" onClick={reset} disabled={!turns.length && phase === 'idle' && !pendingRecording}>
            New conversation
          </button>
        </div>
        {!turns.length && <div className="welcome-message">
          <span className="partner-avatar" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round">
              <path d="M5 13v6M12 8v16M20 4v24M27 11v10" />
            </svg>
          </span>
          <div><h2>What’s on your mind?</h2>
            <p>Tell me about your day, something you enjoy, or a place you’d love to visit.</p>
          </div>
        </div>}
        {turns.map(({ result, audio, autoPlay }, index) => <div className="conversation-turn" key={index}>
          <article className="message user-message">
            <h2>You</h2><p>{result.transcript}</p>
          </article>
          <article className="message assistant-message">
            <h2>Your English partner</h2><p>{result.reply}</p>
            {audio && <ReplyAudio blob={audio} paused={phase !== 'idle'} autoPlay={autoPlay}
              onPlayback={() => { playback.current?.stop(); playback.current = null; }} />}
            <TurnFeedback turn={result} />
            {result.warnings.length > 0 && <details className="turn-notices">
              <summary>Some feedback or audio is unavailable</summary>
              <ul>{result.warnings.map((warning, i) => <li key={i}>{warning.message}</li>)}</ul>
            </details>}
          </article>
        </div>)}
        {incoming && <div className="conversation-turn">
          <article className="message user-message"><h2>You</h2><p>{incoming.transcript}</p></article>
          <article className="message assistant-message"><h2>Your English partner</h2><p>{incoming.reply}</p>
            <p role="status" className="audio-hint">{reviewing ? 'Pronunciation feedback will appear shortly.' : 'Voice reply is arriving…'}</p>
            <TurnFeedback turn={incoming} pronunciationPending />
          </article>
        </div>}
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
          {phase !== 'idle' && <button className="secondary-button" onClick={cancelRequest}>
            {phase === 'sending' ? 'Cancel request' : 'Cancel recording'}
          </button>}
          {phase === 'idle' && pendingRecording && <button className="secondary-button" onClick={retry}>Send again</button>}
          {playing && <button className="secondary-button" onClick={() => playback.current?.stop()}>Stop voice reply</button>}
        </div>
        <p className="composer-hint">{phase === 'recording'
          ? 'Stop & send when you’re finished. Your message sends automatically at 60 seconds.'
          : 'Your microphone is used only while recording. You can replay each voice reply.'}</p>
      </section>
    </main>
  );
}
