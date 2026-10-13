import React, { useState } from 'react';
import type { Issue } from '../types';
import { AlertOctagon, AlertTriangle, Info, CheckCircle2, Filter } from 'lucide-react';
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
        return <span className="severity-badge badge-blocking"><AlertOctagon size={12} /> {t('issue_sev_blocking')}</span>;
      case 'warning':
        return <span className="severity-badge badge-warning"><AlertTriangle size={12} /> {t('issue_sev_warning')}</span>;
      case 'info':
        return <span className="severity-badge badge-info"><Info size={12} /> {t('issue_sev_info')}</span>;
      default:
        return <span className="severity-badge">{severity}</span>;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'OPEN':
        return <span className="status-badge badge-running">{t('issue_status_open')}</span>;
      case 'RESOLVED':
        return <span className="status-badge badge-final"><CheckCircle2 size={12} /> {t('issue_status_resolved')}</span>;
      case 'REJECTED':
        return <span className="status-badge badge-failed">{t('issue_status_rejected')}</span>;
      case 'DUPLICATE':
        return <span className="status-badge badge-partial">{t('issue_status_duplicate')}</span>;
      default:
        return <span className="status-badge">{status}</span>;
    }
  };

  return (
    <div className="section-card">
      <div className="flex-between mb-4">
        <div className="flex-align-center gap-2">
          <AlertOctagon size={18} className="text-amber-400" />
          <h3 className="card-title">{t('issues_title')} ({issues.length})</h3>
        </div>

        <div className="flex-align-center gap-2">
          <Filter size={14} className="text-slate-400" />
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            className="form-select-sm"
          >
            <option value="all">{t('issue_filter_all_sev')}</option>
            <option value="blocking">{t('issue_filter_blocking')}</option>
            <option value="warning">{t('issue_filter_warning')}</option>
            <option value="info">{t('issue_filter_info')}</option>
          </select>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="form-select-sm"
          >
            <option value="all">{t('issue_filter_all_status')}</option>
            <option value="OPEN">{t('issue_status_open')}</option>
            <option value="RESOLVED">{t('issue_status_resolved')}</option>
            <option value="REJECTED">{t('issue_status_rejected')}</option>
          </select>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="empty-state">
          <p className="text-slate-400 text-sm">{t('issues_empty')}</p>
        </div>
      ) : (
        <div className="data-table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>{t('issue_col_severity')}</th>
                <th>{t('issue_col_status')}</th>
                <th>{t('issue_col_concern')}</th>
                <th>{t('issue_col_impact')}</th>
                <th>{t('issue_col_resolution')}</th>
                <th>{t('issue_col_covered_reqs')}</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((iss) => (
                <tr key={iss.id}>
                  <td><span className="code-id">{iss.id}</span></td>
                  <td>{getSeverityBadge(iss.severity)}</td>
                  <td>{getStatusBadge(iss.status)}</td>
                  <td className="max-w-xs">
                    <p className="text-sm font-medium text-slate-100">{iss.claim}</p>
                    {iss.verification_request && (
                      <p className="text-xs text-slate-400 mt-1 italic">{t('issue_verify_prefix')}{iss.verification_request}</p>
                    )}
                  </td>
                  <td className="max-w-xs text-sm text-slate-300">{iss.impact}</td>
                  <td className="max-w-xs text-sm text-slate-300">{iss.suggested_resolution}</td>
                  <td>
                    <div className="flex-wrap gap-1">
                      {iss.requirement_ids.map((r) => (
                        <span key={r} className="badge-subtle text-xs">{r}</span>
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
