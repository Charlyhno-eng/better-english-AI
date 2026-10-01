import { AppHeader } from '../components/AppHeader';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { LanguageCorrections } from '../features/conversation/LanguageCorrections';
import type { Corrections } from '../features/conversation/feedback';
import { correctWriting } from '../features/writing/api';

export function WritingPage() {
  const [text, setText] = useState('');
  const [result, setResult] = useState<Corrections | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  function cancel() {
    request.current?.abort();
    request.current = null;
    setBusy(false);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (request.current || !text.trim()) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(''); setResult(null);
    try {
      const corrections = await correctWriting(text, controller.signal);
      if (request.current === controller) setResult(corrections);
    } catch (failure) {
      if (request.current === controller) setError(failure instanceof TypeError
        ? 'Could not reach the backend. Your writing is preserved; try again.'
        : failure instanceof Error ? failure.message : 'Correction failed. Please try again.');
    } finally {
      if (request.current === controller) { request.current = null; setBusy(false); }
    }
  }
  return <main className="conversation-app">
    <AppHeader />
    <section className="conversation-heading"><p className="eyebrow">Writing practice</p>
      <h1>Find the words you need.</h1><p>Write in English and get clear corrections with short explanations.</p></section>
    <form className="writing-form" onSubmit={(event) => void submit(event)}>
      <label htmlFor="learner-writing">Your English writing</label>
      <textarea id="learner-writing" value={text} disabled={busy} rows={8} maxLength={10000}
        placeholder="Tell us about your day, or write something you want to improve…"
        onChange={(event) => { setText(event.target.value); setResult(null); setError(''); }} />
      <p className="composer-hint">{text.length} / 10,000 characters. Your text is sent to GLM for correction.</p>
      <div className="composer-actions"><button className="primary-button" disabled={busy || !text.trim()}>
        {busy ? 'Checking your writing…' : 'Check my English'}</button>
        {busy && <button type="button" className="secondary-button" onClick={cancel}>Cancel</button>}</div>
      <p role="status">{busy ? 'GLM is reviewing your writing…' : result ? 'Corrections ready.' : ''}</p>
      {error && <p className="error-message" role="alert">{error}</p>}
    </form>
    {result && <section className="message assistant-message writing-results" aria-label="Writing corrections">
      <h2>Your corrections <span className="feedback-source">GLM</span></h2>
      <LanguageCorrections corrections={result} />
    </section>}
  </main>;
}
