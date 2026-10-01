import { useEffect, useRef, useState } from 'react';
import { startConversation, type ConversationOpening } from './start';
import { replyAudioBlob } from './api';
import { ReplyAudio } from './ReplyAudio';

export function ConversationStarter({ mode, disabled, onStarted, onBusy }: {
  mode: 'voice' | 'writing'; disabled: boolean;
  onStarted: (opening: ConversationOpening) => void; onBusy: (busy: boolean) => void;
}) {
  const [topic, setTopic] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => { request.current?.abort(); request.current = null; }, []);
  function cancel() { request.current?.abort(); request.current = null; setBusy(false); onBusy(false); }
  async function submit() {
    if (request.current || disabled || !topic.trim()) return;
    const controller = new AbortController();
    request.current = controller; setBusy(true); onBusy(true); setError('');
    try {
      const opening = await startConversation(topic, mode, controller.signal);
      if (request.current === controller) onStarted(opening);
    } catch (failure) {
      if (request.current === controller) setError(failure instanceof TypeError
        ? 'Could not reach the backend. Your topic is saved here; try again.'
        : failure instanceof Error ? failure.message : 'Could not start the conversation. Try again.');
    } finally {
      if (request.current === controller) { request.current = null; setBusy(false); onBusy(false); }
    }
  }
  return <form className="conversation-starter" onSubmit={event => { event.preventDefault(); void submit(); }}>
    <div className="starter-intro">
      <span className="starter-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z" /></svg></span>
      <div><p className="starter-kicker">You choose the topic · AI goes first</p>
        <h2>A good conversation starts with curiosity.</h2>
        <p>Pick something you’d love to talk about. Your English partner will break the ice.</p></div>
    </div>
    <label htmlFor="conversation-topic">What shall we talk about?</label>
    <textarea id="conversation-topic" rows={2} maxLength={500} value={topic} disabled={busy || disabled}
      aria-describedby="topic-hint" placeholder="A trip to Japan, my favourite films, a job interview…"
      onChange={event => { setTopic(event.target.value); setError(''); }} />
    <div className="topic-suggestions" aria-label="Suggested topics">
      {['Travel & adventures', 'Everyday life', 'Films & music', 'Job interview'].map(suggestion =>
        <button type="button" key={suggestion} aria-pressed={topic === suggestion} disabled={busy || disabled}
          onClick={() => { setTopic(suggestion); setError(''); }}>{suggestion}</button>)}
    </div>
    <div className="starter-footer"><p id="topic-hint">{busy ? 'Your partner is preparing the first question…' : 'Just a topic. No perfect English needed.'}</p>
      <div className="starter-actions"><button className="primary-button" disabled={busy || disabled || !topic.trim()}>
        {busy ? 'Starting conversation…' : 'Let AI start'}<span aria-hidden="true">→</span></button>
        {busy && <button className="secondary-button" type="button" onClick={cancel}>Cancel</button>}</div>
    </div>
    {busy && <p className="sr-only" role="status">Starting your conversation.</p>}
    {error && <p className="error-message" role="alert">{error}</p>}
  </form>;
}

export function OpeningMessage({ opening, paused }: { opening: ConversationOpening; paused: boolean }) {
  const [audio, setAudio] = useState<Blob | null>(null);
  const [audioError, setAudioError] = useState(false);
  useEffect(() => {
    try { setAudio(opening.audio ? replyAudioBlob(opening.audio) : null); setAudioError(false); }
    catch { setAudio(null); setAudioError(true); }
  }, [opening]);
  return <div className="conversation-turn">
    <p className="conversation-topic"><span>Talking about</span> {opening.topic}</p>
    <article className="message assistant-message"><h2>Your English partner</h2><p>{opening.reply}</p>
      {audio && <ReplyAudio blob={audio} paused={paused} />}
      {opening.warnings.map((warning, i) => <p key={i} className="audio-hint">{warning.message}</p>)}
      {audioError && <p className="audio-hint">Press on with the text reply; audio playback is unavailable.</p>}
    </article>
  </div>;
}
