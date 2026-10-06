import React, { useState } from 'react';
import type { Issue } from '../types';
import { AlertOctagon, AlertTriangle, Info, CheckCircle2, Filter } from 'lucide-react';
import { useI18n } from '../i18n';

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
        return <span className="severity-badge badge-blocking"><AlertOctagon size={12} /> Blocking</span>;
      case 'warning':
        return <span className="severity-badge badge-warning"><AlertTriangle size={12} /> Warning</span>;
      case 'info':
        return <span className="severity-badge badge-info"><Info size={12} /> Info</span>;
      default:
        return <span className="severity-badge">{severity}</span>;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'OPEN':
        return <span className="status-badge badge-running">Open</span>;
      case 'RESOLVED':
        return <span className="status-badge badge-final"><CheckCircle2 size={12} /> Resolved</span>;
      case 'REJECTED':
        return <span className="status-badge badge-failed">Rejected</span>;
      case 'DUPLICATE':
        return <span className="status-badge badge-partial">Duplicate</span>;
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
            <option value="all">All Severities</option>
            <option value="blocking">Blocking Only</option>
            <option value="warning">Warning Only</option>
            <option value="info">Info Only</option>
          </select>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="form-select-sm"
          >
            <option value="all">All Statuses</option>
            <option value="OPEN">Open</option>
            <option value="RESOLVED">Resolved</option>
            <option value="REJECTED">Rejected</option>
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
                <th>Severity</th>
                <th>Status</th>
                <th>Claim & Concern</th>
                <th>Impact</th>
                <th>Suggested Resolution</th>
                <th>Covered Reqs</th>
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
                      <p className="text-xs text-slate-400 mt-1 italic">Verify: {iss.verification_request}</p>
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
