import { LanguageCorrections } from './LanguageCorrections';
import type { VoiceTurn } from './api';

export function TurnFeedback({ turn }: { turn: VoiceTurn }) {
  const { corrections, pronunciation, pronunciation_feedback: feedback } = turn;
  const count = corrections?.items.length ?? 0;
  return <details className="learning-feedback">
    <summary>Review your English{count > 0 ? ` · ${count} suggestion${count === 1 ? '' : 's'}` : ''}</summary>
    <section aria-label="GLM language corrections">
      <h3>Language corrections <span className="feedback-source">GLM</span></h3>
      <p className="feedback-note">Based on your transcript. Speech recognition can affect these suggestions.</p>
      {!corrections ? <p>Language corrections are unavailable for this turn.</p>
        : <>
          <LanguageCorrections corrections={corrections} />
        </>}
    </section>
    <section aria-label="OpenPronounce pronunciation observations">
      <h3>Pronunciation observations <span className="feedback-source">OpenPronounce</span></h3>
      {!pronunciation ? <p>Pronunciation analysis is unavailable or was skipped for this turn.</p> : <>
        <p className="feedback-note">Approximate sound observations, not a definitive diagnosis.
          {pronunciation.reference_inferred && ' The reference comes from speech recognition, so your intended words may differ.'}</p>
        {pronunciation.errors.length === 0 ? <p>No pronunciation differences reported.</p> :
          <ul className="correction-list">{pronunciation.errors.map((item, index) => <li key={index}>
            <strong>{item.word || `Word ${item.position + 1}`}</strong>
            <p>Expected sound: <span className="phoneme">{item.expected || 'Not available'}</span><br />
              Recognized sound: <span className="phoneme">{item.observed || 'Not recognized'}</span></p>
          </li>)}</ul>}
        {pronunciation.feedback.trim() && <p>{pronunciation.feedback}</p>}
      </>}
    </section>
    <section aria-label="GLM pronunciation coaching">
      <h3>Pronunciation coaching <span className="feedback-source">GLM</span></h3>
      <p>{feedback ?? 'Pronunciation coaching is unavailable for this turn.'}</p>
    </section>
  </details>;
}
