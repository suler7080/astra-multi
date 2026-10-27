import React, { useState } from 'react';
import type { Issue } from '../types';
import { AlertOctagon, Filter } from 'lucide-react';
import { useI18n } from '../i18nContext';

interface IssuesTableProps {
  issues: Issue[];
}

export const IssuesTable: React.FC<IssuesTableProps> = ({ issues }) => {
  const { t } = useI18n();
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  const filtered = issues.filter((iss) => {
    if (severityFilter !== 'all' && iss.severity !== severityFilter) return false;
    if (statusFilter !== 'all' && iss.status !== statusFilter) return false;
    return true;
  });

  const getSeverityBadge = (severity: string) => {
    switch (severity) {
      case 'blocking':
        return <span className="chip chip-error text-[11px] py-0.5 px-2">{t('issue_sev_blocking')}</span>;
      case 'warning':
        return <span className="chip chip-warn text-[11px] py-0.5 px-2">{t('issue_sev_warning')}</span>;
      case 'info':
        return <span className="chip chip-neutral text-[11px] py-0.5 px-2">{t('issue_sev_info')}</span>;
      default:
        return <span className="chip chip-neutral text-[11px] py-0.5 px-2">{severity}</span>;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'OPEN':
        return <span className="chip chip-error text-[11px] py-0.5 px-2">{t('issue_status_open')}</span>;
      case 'RESOLVED':
        return <span className="chip chip-success text-[11px] py-0.5 px-2">{t('issue_status_resolved')}</span>;
      case 'REJECTED':
        return <span className="chip chip-neutral text-[11px] py-0.5 px-2">{t('issue_status_rejected')}</span>;
      case 'DUPLICATE':
        return <span className="chip chip-neutral text-[11px] py-0.5 px-2">{t('issue_status_duplicate')}</span>;
      default:
        return <span className="chip chip-neutral text-[11px] py-0.5 px-2">{status}</span>;
    }
  };

  return (
    <div className="bg-[var(--bg)] border border-[var(--border)] rounded-[28px] p-6 sm:p-7 shadow-sm">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6 pb-4 border-b border-[var(--border)]">
        <div className="flex items-center gap-2.5">
          <AlertOctagon size={20} className="text-[var(--accent)]" />
          <h3 className="text-[20px] font-medium text-[var(--text)] tracking-tight">{t('tab_issues')}</h3>
          <span className="font-mono text-[12px] font-medium px-2.5 py-0.5 rounded-full bg-[var(--surface-tonal)] text-[var(--text-2)]">
            {issues.length}
          </span>
        </div>

        <div className="flex items-center gap-2.5">
          <Filter size={14} className="text-[var(--text-2)]" />
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            className="h-9 text-[13px] rounded-full py-1 px-3.5 bg-[var(--surface-tonal)] border border-[var(--border-strong)] text-[var(--text)] outline-none cursor-pointer"
          >
            <option value="all">{t('issue_filter_all_sev')}</option>
            <option value="blocking">{t('issue_filter_blocking')}</option>
            <option value="warning">{t('issue_filter_warning')}</option>
            <option value="info">{t('issue_filter_info')}</option>
          </select>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="h-9 text-[13px] rounded-full py-1 px-3.5 bg-[var(--surface-tonal)] border border-[var(--border-strong)] text-[var(--text)] outline-none cursor-pointer"
          >
            <option value="all">{t('issue_filter_all_status')}</option>
            <option value="OPEN">{t('issue_status_open')}</option>
            <option value="RESOLVED">{t('issue_status_resolved')}</option>
            <option value="REJECTED">{t('issue_status_rejected')}</option>
          </select>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="text-center py-12 text-[var(--text-2)]">
          <AlertOctagon size={36} className="mx-auto mb-2 opacity-40 text-[var(--text-2)]" />
          <p className="text-[14px] font-medium">{t('issues_empty')}</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-[20px] border border-[var(--border)]">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-[var(--border)] bg-[var(--surface-tonal)] text-[11px] font-medium uppercase tracking-wider text-[var(--text-2)] font-mono">
                <th className="py-3 px-4">ID</th>
                <th className="py-3 px-4">{t('issue_col_severity')}</th>
                <th className="py-3 px-4">{t('issue_col_status')}</th>
                <th className="py-3 px-4">{t('issue_col_concern')}</th>
                <th className="py-3 px-4">{t('issue_col_impact')}</th>
                <th className="py-3 px-4">{t('issue_col_resolution')}</th>
                <th className="py-3 px-4">{t('issue_col_covered_reqs')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)] text-[13px]">
              {filtered.map((iss) => (
                <tr key={iss.id} className="hover:bg-[var(--bg-alt)] transition-colors">
                  <td className="py-3.5 px-4 whitespace-nowrap">
                    <span className="font-mono text-[12px] px-2 py-0.5 rounded-full border border-[var(--border-strong)] text-[var(--text)]">
                      {iss.id}
                    </span>
                  </td>
                  <td className="py-3.5 px-4 whitespace-nowrap">{getSeverityBadge(iss.severity)}</td>
                  <td className="py-3.5 px-4 whitespace-nowrap">{getStatusBadge(iss.status)}</td>
                  <td className="py-3.5 px-4 max-w-xs">
                    <p className="font-medium text-[var(--text)]">{iss.claim}</p>
                    {iss.verification_request && (
                      <p className="text-[11px] text-[var(--text-2)] mt-1 italic font-mono">
                        {t('issue_verify_prefix')}{iss.verification_request}
                      </p>
                    )}
                  </td>
                  <td className="py-3.5 px-4 max-w-xs text-[var(--text-2)]">{iss.impact}</td>
                  <td className="py-3.5 px-4 max-w-xs text-[var(--success-on-tonal)] font-medium">{iss.suggested_resolution}</td>
                  <td className="py-3.5 px-4 whitespace-nowrap">
                    <div className="flex flex-wrap gap-1">
                      {iss.requirement_ids.map((r) => (
                        <span key={r} className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-[var(--surface-tonal)] text-[var(--text-2)]">
                          {r}
                        </span>
                      ))}
                    </div>
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
