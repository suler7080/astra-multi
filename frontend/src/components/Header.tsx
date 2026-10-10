import React from 'react';
import type { RunSummary } from '../types';
import { Layers, Plus, RefreshCw, Settings, LogOut } from 'lucide-react';
import { LanguageSwitcher } from '../i18n';
import { useI18n } from '../i18nContext';

interface HeaderProps {
  runs: RunSummary[];
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
  onOpenNewRun: () => void;
  onRefresh: () => void;
  onOpenSettings: () => void;
  onLogout?: () => void;
  isLoading: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  runs,
  selectedRunId,
  onSelectRun,
  onOpenNewRun,
  onRefresh,
  onOpenSettings,
  onLogout,
  isLoading,
}) => {
  const { t } = useI18n();

  return (
    <header className="header-container">
      <div className="header-left">
        <div
          className="logo-badge"
          onClick={() => onSelectRun('')}
          style={{ cursor: 'pointer' }}
          title={t('header_all_runs')}
        >
          <Layers size={22} className="logo-icon" />
          <span className="logo-text">Astra Multi</span>
        </div>
        <span className="app-subtitle">{t('header_subtitle')}</span>
      </div>

      <div className="header-right">
        {/* Language Switcher */}
        <LanguageSwitcher />

        <div className="run-selector-group">
          <label htmlFor="run-select" className="selector-label">{t('header_run_label')}</label>
          <select
            id="run-select"
            value={selectedRunId || ''}
            onChange={(e) => onSelectRun(e.target.value)}
            className="run-select"
          >
            <option value="">{t('header_all_runs')}</option>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {r.run_id} - {r.goal.length > 28 ? r.goal.substring(0, 28) + '...' : r.goal} ({r.status})
              </option>
            ))}
          </select>
        </div>

        <button
          onClick={onRefresh}
          className="btn-icon"
          title={t('header_refresh_tooltip')}
          disabled={isLoading}
        >
          <RefreshCw size={16} className={isLoading ? 'animate-spin' : ''} />
        </button>

        <button
          onClick={onOpenSettings}
          className="btn-secondary text-xs px-2.5 py-1.5 flex items-center gap-1.5"
          title={t('header_btn_settings')}
        >
          <Settings size={14} />
          <span>{t('header_btn_settings')}</span>
        </button>

        <button
          onClick={onOpenNewRun}
          className="btn-primary"
        >
          <Plus size={16} />
          <span>{t('header_new_run')}</span>
        </button>

        {onLogout && (
          <button
            onClick={onLogout}
            className="btn-icon"
            title={t('auth_btn_logout')}
          >
            <LogOut size={16} />
          </button>
        )}
      </div>
    </header>
  );
};

