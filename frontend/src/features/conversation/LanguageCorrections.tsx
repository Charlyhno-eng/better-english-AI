import { correctionLabels, type Corrections } from './feedback';

export function LanguageCorrections({ corrections }: { corrections: Corrections }) {
  const count = corrections.items.length;
  return <>
          {count === 0 ? <p>No language corrections suggested.</p> : <>
            <p className="corrected-text"><strong>Corrected version</strong><br />{corrections.corrected_text}</p>
            <ul className="correction-list">{corrections.items.map((item, index) => <li key={index}>
              <span className="correction-category">{correctionLabels[item.category]}</span>
              <p><span className="original-text">{item.original}</span> <span aria-label="corrected to">→</span> <strong>{item.replacement}</strong></p>
              <p>{item.explanation}</p>
            </li>)}</ul>
          </>}
  </>;
}
