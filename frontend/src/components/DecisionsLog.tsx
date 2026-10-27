import React from 'react';
import type { Decision } from '../types';
import { Compass, CheckCircle2 } from 'lucide-react';
import { useI18n } from '../i18nContext';

interface DecisionsLogProps {
  decisions: Decision[];
}

export const DecisionsLog: React.FC<DecisionsLogProps> = ({ decisions }) => {
  const { t } = useI18n();

  return (
    <div className="bg-[var(--bg)] border border-[var(--border)] rounded-[28px] p-6 sm:p-7 shadow-sm">
      <div className="flex items-center gap-2.5 mb-6 pb-4 border-b border-[var(--border)]">
        <Compass size={20} className="text-[var(--accent)]" />
        <h3 className="text-[20px] font-medium text-[var(--text)] tracking-tight">{t('tab_decisions')}</h3>
        <span className="font-mono text-[12px] font-medium px-2.5 py-0.5 rounded-full bg-[var(--surface-tonal)] text-[var(--text-2)]">
          {decisions.length}
        </span>
      </div>

      {decisions.length === 0 ? (
        <div className="text-center py-12 text-[var(--text-2)]">
          <Compass size={36} className="mx-auto mb-2 opacity-40 text-[var(--text-2)]" />
          <p className="text-[14px] font-medium">{t('decisions_empty')}</p>
        </div>
      ) : (
        <div className="space-y-4">
          {decisions.map((dec) => (
            <div
              key={dec.id}
              className="p-6 rounded-[20px] bg-[var(--bg-alt)] border border-[var(--border)] hover:border-[var(--accent)]/30 transition-all shadow-sm space-y-3"
            >
              <div className="flex items-center gap-2.5">
                <span className="font-mono text-[12px] px-2.5 py-0.5 rounded-full border border-[var(--border-strong)] text-[var(--text)] font-medium">
                  {dec.id}
                </span>
                <h4 className="text-[16px] font-medium text-[var(--text)]">{dec.question}</h4>
              </div>

              <div className="p-4 rounded-[16px] bg-[var(--success-tonal)] text-[var(--success-on-tonal)] border border-[var(--success)]/20">
                <div className="flex items-center gap-1.5 text-[var(--success)] mb-1">
                  <CheckCircle2 size={15} />
                  <span className="text-[11px] font-semibold uppercase tracking-wider">{t('decisions_chosen_alternative')}</span>
                </div>
                <p className="text-[15px] font-medium">{dec.chosen}</p>
              </div>

              <div className="p-4 rounded-[16px] bg-[var(--surface-tonal)] text-[var(--text)] space-y-1">
                <strong className="text-[11px] font-mono text-[var(--text-2)] uppercase tracking-wider block">{t('decisions_rationale')}</strong>
                <p className="text-[13px] text-[var(--text-2)] leading-relaxed">{dec.rationale}</p>
              </div>

              {dec.alternatives && dec.alternatives.length > 0 && (
                <div className="pt-2 border-t border-[var(--border)]">
                  <strong className="text-[11px] font-mono text-[var(--text-2)] uppercase tracking-wider block mb-1.5">{t('decisions_rejected_alternatives')}</strong>
                  <ul className="flex flex-wrap gap-1.5">
                    {dec.alternatives.map((alt, i) => (
                      <li key={i} className="text-[11px] font-mono text-[var(--text-2)] bg-[var(--surface-tonal)] px-2.5 py-1 rounded-full">{alt}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
