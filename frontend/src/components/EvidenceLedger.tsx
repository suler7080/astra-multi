import React, { useState } from 'react';
import type { Evidence } from '../types';
import { FileSearch, CheckCircle, XCircle, Clock } from 'lucide-react';

interface EvidenceLedgerProps {
  evidence: Evidence[];
}

export const EvidenceLedger: React.FC<EvidenceLedgerProps> = ({ evidence }) => {
  const [sourceFilter, setSourceFilter] = useState<string>('all');

  const filtered = evidence.filter((e) => {
    if (sourceFilter !== 'all' && e.source_type !== sourceFilter) return false;
    return true;
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'PASS':
        return <span className="status-badge badge-final"><CheckCircle size={12} /> PASS</span>;
      case 'FAIL':
        return <span className="status-badge badge-failed"><XCircle size={12} /> FAIL</span>;
      case 'NOT_RUN':
      default:
        return <span className="status-badge badge-default"><Clock size={12} /> NOT_RUN</span>;
    }
  };

  const getSourceBadge = (source: string) => {
    switch (source) {
      case 'repo':
        return <span className="badge-subtle text-xs">Repo Code</span>;
      case 'tool':
        return <span className="badge-subtle text-xs">Tool Exec</span>;
      case 'document':
        return <span className="badge-subtle text-xs">Doc</span>;
      case 'user':
        return <span className="badge-subtle text-xs">Operator</span>;
      default:
        return <span className="badge-subtle text-xs">{source}</span>;
    }
  };

  return (
    <div className="section-card">
      <div className="flex-between mb-4">
        <div className="flex-align-center gap-2">
          <FileSearch size={18} className="text-sky-400" />
          <h3 className="card-title">Evidence & Verification Ledger ({evidence.length})</h3>
        </div>

        <select
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value)}
          className="form-select-sm"
        >
          <option value="all">All Sources</option>
          <option value="repo">Repo Code</option>
          <option value="tool">Tool Exec</option>
          <option value="document">Document</option>
          <option value="user">Operator</option>
        </select>
      </div>

      {filtered.length === 0 ? (
        <div className="empty-state">
          <p className="text-slate-400 text-sm">No evidence records captured yet.</p>
        </div>
      ) : (
        <div className="data-table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Source Type</th>
                <th>Verification Status</th>
                <th>Locator / Path</th>
                <th>Content Hash (SHA-256)</th>
                <th>Captured At</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <tr key={item.id}>
                  <td><span className="code-id">{item.id}</span></td>
                  <td>{getSourceBadge(item.source_type)}</td>
                  <td>{getStatusBadge(item.status)}</td>
                  <td className="font-mono text-xs text-slate-200">{item.locator}</td>
                  <td className="font-mono text-xs text-slate-400" title={item.content_hash}>
                    {item.content_hash.substring(0, 16)}...
                  </td>
                  <td className="text-xs text-slate-400">
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
