import { AppHeader } from '../components/AppHeader';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { CorrectionDisclosure } from '../features/writing/CorrectionDisclosure';
import { sendWritingMessage, type WritingMessage, type WritingTurn } from '../features/writing/api';

import { ConversationStarter, OpeningMessage } from '../features/conversation/ConversationStarter';
import { conversationHistory, type ConversationOpening } from '../features/conversation/start';

interface ChatTurn extends WritingTurn { text: string; }

export function WritingPage() {
  const [opening, setOpening] = useState<ConversationOpening | null>(null);
  const [starting, setStarting] = useState(false);
  const [session, setSession] = useState(0);
  const [text, setText] = useState('');
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [pendingText, setPendingText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);
  const end = useRef<HTMLDivElement | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }); }, [turns, busy]);

  function cancel() {
    request.current?.abort();
    request.current = null;
    setBusy(false); setPendingText('');
  }
  function reset() {
    cancel(); setTurns([]); setText(''); setError(''); setOpening(null); setStarting(false); setSession(value => value + 1);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (request.current || starting || !text.trim()) return;
    const controller = new AbortController();
    const submitted = text.trim();
    const history: WritingMessage[] = conversationHistory(opening, turns.flatMap((turn) => [
      { role: 'user' as const, content: turn.text },
      { role: 'assistant' as const, content: turn.reply },
    ]), 25);
    request.current = controller;
    setBusy(true); setError(''); setPendingText(submitted);
    try {
      const result = await sendWritingMessage(submitted, history, controller.signal);
      if (request.current === controller) {
        setTurns((previous) => [...previous, { text: submitted, ...result }]);
        setText('');
      }
    } catch (failure) {
      if (request.current === controller) setError(failure instanceof TypeError
        ? 'Could not reach the backend. Your message is preserved; try again.'
        : failure instanceof Error ? failure.message : 'Reply failed. Please try again.');
    } finally {
      if (request.current === controller) {
        request.current = null; setBusy(false); setPendingText('');
      }
    }
  }
  return <main className="conversation-app">
    <AppHeader />
    <section className="conversation-heading"><p className="eyebrow">Writing practice</p>
      <h1>Keep the conversation going.</h1><p>Chat in English and review your language below each reply.</p></section>
    <section className="conversation-thread" aria-label="Written conversation">
      <div className="thread-toolbar"><span className="thread-label">Your writing partner</span>
        <button type="button" className="secondary-button" onClick={reset}>New conversation</button></div>
      {!turns.length && !opening && !busy && <ConversationStarter key={session} mode="writing"
        disabled={busy} onStarted={setOpening} onBusy={setStarting} />}
      {opening && <OpeningMessage opening={opening} paused={busy} />}
      <div role="log" aria-label="Writing messages" aria-live="polite">
        {turns.map((turn, index) => <div className="conversation-turn" key={index}>
          <article className="message user-message"><h2>You</h2><p>{turn.text}</p></article>
          <article className="message assistant-message"><h2>English partner</h2><p>{turn.reply}</p>
            <CorrectionDisclosure corrections={turn.corrections} />
          </article>
        </div>)}
        {busy && <div className="conversation-turn">
          <article className="message user-message"><h2>You</h2><p>{pendingText}</p></article>
          <article className="message assistant-message"><h2>English partner</h2>
            <div className="writing-typing" role="status" aria-label="English partner is typing">
              <span /><span /><span />
            </div>
          </article>
        </div>}
      </div>
      <div ref={end} />
    </section>
    <form className="writing-form writing-composer" onSubmit={(event) => void submit(event)}>
      <label htmlFor="learner-writing">Your message</label>
      <textarea id="learner-writing" value={text} disabled={busy || starting} rows={3} maxLength={10000}
        placeholder="Write your next message in English…"
        onChange={(event) => { setText(event.target.value); setError(''); }} />
      <p className="composer-hint">{text.length} / 10,000 characters. The latest 25 messages provide conversation context. This chat stays in memory until you leave the page.</p>
      <div className="composer-actions"><button className="primary-button" disabled={busy || starting || !text.trim()}>
        Send message</button>
        {busy && <button type="button" className="secondary-button" onClick={cancel}>Cancel</button>}</div>
      {error && <p className="error-message" role="alert">{error}</p>}
    </form>
  </main>;
}
