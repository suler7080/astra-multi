import React, { useState } from 'react';
import type { Evidence } from '../types';
import { FileSearch, CheckCircle, XCircle, Clock } from 'lucide-react';
import { useI18n } from '../i18nContext';

interface EvidenceLedgerProps {
  evidence: Evidence[];
}

export const EvidenceLedger: React.FC<EvidenceLedgerProps> = ({ evidence }) => {
  const { t } = useI18n();
  const [sourceFilter, setSourceFilter] = useState<string>('all');

  const filtered = evidence.filter((e) => {
    if (sourceFilter !== 'all' && e.source_type !== sourceFilter) return false;
    return true;
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'PASS':
        return <span className="chip chip-success text-[11px] py-0.5 px-2"><CheckCircle size={12} /> PASS</span>;
      case 'FAIL':
        return <span className="chip chip-error text-[11px] py-0.5 px-2"><XCircle size={12} /> FAIL</span>;
      case 'NOT_RUN':
      default:
        return <span className="chip chip-neutral text-[11px] py-0.5 px-2"><Clock size={12} /> NOT_RUN</span>;
    }
  };

  const getSourceBadge = (source: string) => {
    switch (source) {
      case 'repo':
        return <span className="chip chip-neutral text-[11px]">{t('evidence_source_repo')}</span>;
      case 'tool':
        return <span className="chip chip-neutral text-[11px]">{t('evidence_source_tool')}</span>;
      case 'document':
        return <span className="chip chip-neutral text-[11px]">{t('evidence_source_doc')}</span>;
      case 'user':
        return <span className="chip chip-neutral text-[11px]">{t('evidence_source_operator')}</span>;
      default:
        return <span className="chip chip-neutral text-[11px]">{source}</span>;
    }
  };

  return (
    <div className="bg-[var(--bg)] border border-[var(--border)] rounded-[28px] p-6 sm:p-7 shadow-sm">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6 pb-4 border-b border-[var(--border)]">
        <div className="flex items-center gap-2.5">
          <FileSearch size={20} className="text-[var(--accent)]" />
          <h3 className="text-[20px] font-medium text-[var(--text)] tracking-tight">{t('tab_evidence')}</h3>
          <span className="font-mono text-[12px] font-medium px-2.5 py-0.5 rounded-full bg-[var(--surface-tonal)] text-[var(--text-2)]">
            {evidence.length}
          </span>
        </div>

        <select
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
          className="h-9 text-[13px] rounded-full py-1 px-3.5 bg-[var(--surface-tonal)] border border-[var(--border-strong)] text-[var(--text)] outline-none cursor-pointer"
        >
          <option value="all">{t('evidence_filter_all_sources')}</option>
          <option value="repo">{t('evidence_source_repo')}</option>
          <option value="tool">{t('evidence_source_tool')}</option>
          <option value="document">{t('evidence_source_doc')}</option>
          <option value="user">{t('evidence_source_operator')}</option>
        </select>
      </div>

      {filtered.length === 0 ? (
        <div className="text-center py-12 text-[var(--text-2)]">
          <FileSearch size={36} className="mx-auto mb-2 opacity-40 text-[var(--text-2)]" />
          <p className="text-[14px] font-medium">{t('evidence_empty')}</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-[20px] border border-[var(--border)]">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--surface-tonal)] text-[11px] font-medium uppercase tracking-wider text-[var(--text-2)] font-mono">
                <th className="py-3 px-4">ID</th>
                <th className="py-3 px-4">{t('evidence_col_source_type')}</th>
                <th className="py-3 px-4">{t('evidence_col_status')}</th>
                <th className="py-3 px-4">{t('evidence_col_locator')}</th>
                <th className="py-3 px-4">{t('evidence_col_hash')}</th>
                <th className="py-3 px-4">{t('evidence_col_captured_at')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)] text-[13px]">
              {filtered.map((item) => (
                <tr key={item.id} className="hover:bg-[var(--bg-alt)] transition-colors">
                  <td className="py-3.5 px-4 whitespace-nowrap">
                    <span className="font-mono text-[12px] px-2 py-0.5 rounded-full border border-[var(--border-strong)] text-[var(--text)]">
                      {item.id}
                    </span>
                  </td>
                  <td className="py-3.5 px-4 whitespace-nowrap">{getSourceBadge(item.source_type)}</td>
                  <td className="py-3.5 px-4 whitespace-nowrap">{getStatusBadge(item.status)}</td>
                  <td className="py-3.5 px-4 font-mono text-[var(--text)] max-w-xs truncate">{item.locator}</td>
                  <td className="py-3.5 px-4 font-mono text-[var(--text-2)]" title={item.content_hash}>
                    {item.content_hash.substring(0, 16)}...
                  </td>
                  <td className="py-3.5 px-4 text-[var(--text-2)] font-mono tabular-nums whitespace-nowrap">
                    {new Date(item.captured_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
