import { LanguageCorrections } from '../shared/LanguageCorrections';
import type { Corrections } from '../shared/feedback';

export function CorrectionDisclosure({ corrections }: { corrections: Corrections }) {
  const issues = corrections.items.filter((item) => item.category !== 'style');
  if (issues.length === 0) return null;
  const serious = issues.some((item) => item.category === 'grammar' || item.category === 'spelling');
  return <details className={`writing-corrections writing-corrections--${serious ? 'serious' : 'gentle'}`}>
    <summary><span>{issues.length} correction{issues.length === 1 ? '' : 's'} to review</span></summary>
    <div className="writing-corrections-content">
      <LanguageCorrections corrections={{ ...corrections, items: issues }} />
    </div>
  </details>;
}
