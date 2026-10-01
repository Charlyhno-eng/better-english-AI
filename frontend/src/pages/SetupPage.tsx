import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { postJson } from '../features/shared/api';

type ModelId = 'parakeet' | 'pocket-tts' | 'openpronounce';
interface ModelStatus { id: ModelId; state: 'not_installed' | 'installing' | 'installed' | 'failed'; message: string; }
interface SetupStatus { glm_configured: boolean; models: ModelStatus[]; }
const models: Record<ModelId, { name: string; description: string }> = {
  parakeet: { name: 'Parakeet', description: 'Speech recognition · about 2.4 GB' },
  'pocket-tts': { name: 'Pocket TTS', description: 'Spoken replies · English model and Alba voice' },
  openpronounce: { name: 'OpenPronounce', description: 'Pronunciation feedback · two speech models and a Piper voice, several GB' },
};
const labels = { not_installed: 'Not installed', installing: 'Installing…', installed: 'Installed', failed: 'Installation failed' };

export function SetupPage() {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [key, setKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function refresh() {
      try {
        const response = await fetch('/api/setup', { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('Setup could not be loaded. Check that the backend is running.');
        const data = await response.json() as SetupStatus;
        if (!disposed) setStatus(data);
      } catch (cause) {
        if (!disposed) setError(cause instanceof Error ? cause.message : 'Setup could not be loaded.');
      } finally {
        if (!disposed) timer = setTimeout(() => void refresh(), 2000);
      }
    }
    void refresh();
    return () => { disposed = true; clearTimeout(timer); controller.abort(); };
  }, []);

  async function saveKey(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true); setError(''); setNotice('');
    try {
      await postJson('/api/setup/glm', { api_key: key }, new AbortController().signal);
      setKey(''); setNotice('API key saved. You can use GLM now.');
      setStatus((previous) => previous && { ...previous, glm_configured: true });
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not save the key.'); }
    finally { setPending(false); }
  }

  async function toggleKeyVisibility() {
    if (showKey) { setShowKey(false); return; }
    if (!key && status?.glm_configured) {
      try {
        const response = await fetch('/api/setup/glm', { cache: 'no-store' });
        if (!response.ok) throw new Error('The saved API key could not be loaded.');
        const data = await response.json() as { api_key: string };
        setKey(data.api_key);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'The saved API key could not be loaded.');
        return;
      }
    }
    setShowKey(true);
  }

  async function install(id: ModelId) {
    setPending(true); setError(''); setNotice('');
    try {
      await postJson(`/api/setup/models/${id}`, {}, new AbortController().signal);
      setStatus((previous) => previous && { ...previous, models: previous.models.map((model) =>
        model.id === id ? { ...model, state: 'installing', message: 'Downloading and preparing resources…' } : model) });
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Installation could not start.'); }
    finally { setPending(false); }
  }

  const installing = status?.models.some((model) => model.state === 'installing');
  return <main className="conversation-app">
    <header className="app-header">
      <Link className="wordmark" to="/">Better English <span>AI</span></Link>
      <Link to="/">Conversation</Link>
    </header>
    <section className="conversation-heading">
      <h1>Set up your English tutor.</h1>
      <p>Save your API key and install the models here. Downloads can take several minutes and need internet access and free disk space. All local models use your CPU.</p>
    </section>
    {error && <p className="error-message" role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {!status && <p role="status">Loading setup…</p>}
    {status && <>
      <section className="setup-card">
        <h2>GLM API key</h2>
        <p>{status.glm_configured ? 'A key is configured. You can replace it below.' : 'Add your Z.AI API key for conversation and writing feedback.'}</p>
        <form className="setup-form" onSubmit={(event) => void saveKey(event)}>
          <label htmlFor="glm-key">API key</label>
          <div className="api-key-input">
            <input id="glm-key" type={showKey ? 'text' : 'password'} autoComplete="off" value={key}
              placeholder={status.glm_configured && !key ? '••••••••••••••••' : undefined} maxLength={4096}
            onChange={(event) => setKey(event.target.value)} required />
            <button className="key-visibility-button" type="button" onClick={() => void toggleKeyVisibility()}
              aria-label={showKey ? 'Hide API key' : 'Show API key'} aria-pressed={showKey}>
              <svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none"
                stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                {showKey ? <><path d="M3 3l18 18" /><path d="M10.6 10.6a2 2 0 002.8 2.8" />
                  <path d="M9.9 5.2A10.8 10.8 0 0112 5c5 0 8.5 4.5 9.5 7a11.8 11.8 0 01-3.1 4.3M6.2 6.2A13 13 0 002.5 12c1 2.5 4.5 7 9.5 7 1 0 2-.2 2.9-.5" /></>
                  : <><path d="M2.5 12s3.5-7 9.5-7 9.5 7 9.5 7-3.5 7-9.5 7-9.5-7-9.5-7z" />
                    <circle cx="12" cy="12" r="3" /></>}
              </svg>
            </button>
          </div>
          <p className="composer-hint">Stored privately on your backend. The saved key is loaded only when you reveal it. GLM requests use your API account.</p>
          <button className="primary-button" disabled={pending || !key.trim()}>Save key</button>
        </form>
      </section>
      <div aria-live="polite" aria-atomic="false">
        {status.models.map((model) => <section className="setup-card" key={model.id}>
          <h2>{models[model.id].name}</h2>
          <p>{models[model.id].description}</p>
          <p>{labels[model.state]}{model.message && ` · ${model.message}`}</p>
          {model.state !== 'installed' && <button className="primary-button" disabled={pending || installing}
            onClick={() => void install(model.id)}>{model.state === 'failed' ? 'Retry installation' : model.state === 'installing' ? 'Installing…' : 'Install model'}</button>}
        </section>)}
      </div>
      <p>Installations continue if you leave this page. Once your key and models are ready, <Link to="/">start a conversation</Link>.</p>
    </>}
  </main>;
}
