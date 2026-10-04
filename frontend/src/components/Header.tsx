import React from 'react';
import type { RunSummary } from '../types';
import { Layers, Plus, RefreshCw } from 'lucide-react';

interface HeaderProps {
  runs: RunSummary[];
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
  onOpenNewRun: () => void;
  onRefresh: () => void;
  isLoading: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  runs,
  selectedRunId,
  onSelectRun,
  onOpenNewRun,
  onRefresh,
  isLoading,
}) => {
  return (
    <header className="header-container">
      <div className="header-left">
        <div className="logo-badge">
          <Layers size={22} className="logo-icon" />
          <span className="logo-text">Astra Multi</span>
        </div>
        <span className="app-subtitle">Architecture Planner</span>
      </div>

      <div className="header-right">
        <div className="run-selector-group">
          <label htmlFor="run-select" className="selector-label">Run:</label>
          <select
            id="run-select"
            value={selectedRunId || ''}
            onChange={(e) => onSelectRun(e.target.value)}
            className="run-select"
          >
            <option value="" disabled>Select a run...</option>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.run_id} - {r.goal.length > 32 ? r.goal.substring(0, 32) + '...' : r.goal} ({r.status})
              </option>
            ))}
          </select>
        </div>

        <button
          onClick={onRefresh}
          className="btn-icon"
          title="Refresh runs and details"
          disabled={isLoading}
        >
          <RefreshCw size={16} className={isLoading ? 'animate-spin' : ''} />
        </button>

        <button
          onClick={onOpenNewRun}
          className="btn-primary"
        >
          <Plus size={16} />
          <span>New Run</span>
        </button>
      </div>
    </header>
  );
};
