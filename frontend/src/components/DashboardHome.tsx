import React from 'react';
import type { RunSummary } from '../types';
import { useI18n } from '../i18n';
import {
  Layers,
  Plus,
  RefreshCw,
  Activity,
  CheckCircle2,
  AlertTriangle,
  FolderGit2,
  ArrowRight,
  Clock,
  CircleDot,
  XCircle,
  Trash2,
} from 'lucide-react';

interface DashboardHomeProps {
  runs: RunSummary[];
  onSelectRun: (runId: string) => void;
  onDeleteRun: (runId: string) => void;
  onOpenNewRun: () => void;
  onRefresh: () => void;
  isLoading: boolean;
  isDeletingId?: string | null;
}

export const DashboardHome: React.FC<DashboardHomeProps> = ({
  runs,
  onSelectRun,
  onDeleteRun,
  onOpenNewRun,
  onRefresh,
  isLoading,
  isDeletingId,
}) => {
  const { t } = useI18n();

  const totalRuns = runs.length;
  const activeRuns = runs.filter(
    (r) => r.status === 'RUNNING' || r.status === 'WAITING_FOR_INPUT'
  ).length;
  const finalRuns = runs.filter((r) => r.status === 'FINAL').length;
  const failedRuns = runs.filter(
    (r) => r.status === 'FAILED' || r.status === 'PARTIAL'
  ).length;

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'FINAL':
        return (
          <span className="status-badge badge-final">
            <CheckCircle2 size={12} /> {t('status_final')}
          </span>
        );
      case 'RUNNING':
        return (
          <span className="status-badge badge-running">
            <CircleDot size={12} className="animate-pulse" /> {t('status_running')}
          </span>
        );
      case 'WAITING_FOR_INPUT':
        return (
          <span className="status-badge badge-waiting">
            <AlertTriangle size={12} /> {t('status_waiting')}
          </span>
        );
      case 'PARTIAL':
        return (
          <span className="status-badge badge-partial">
            <AlertTriangle size={12} /> {t('status_partial')}
          </span>
        );
      case 'CANCELLED':
        return (
          <span className="status-badge badge-cancelled">
            <XCircle size={12} /> {t('status_cancelled')}
          </span>
        );
      case 'FAILED':
        return (
          <span className="status-badge badge-failed">
            <XCircle size={12} /> {t('status_failed')}
          </span>
        );
      default:
        return <span className="status-badge badge-default">{status}</span>;
    }
  };

  const formatDate = (isoStr: string) => {
    try {
      const date = new Date(isoStr);
      return date.toLocaleString();
    } catch {
      return isoStr;
    }
  };

  return (
    <div className="dashboard-container">
      {/* Welcome Banner */}
      <div className="dashboard-hero">
        <div className="hero-content">
          <div className="hero-icon-box">
            <Layers size={28} className="text-sky-400" />
          </div>
          <div>
            <h1 className="hero-title">{t('dash_welcome_title')}</h1>
            <p className="hero-subtitle">{t('dash_welcome_subtitle')}</p>
          </div>
        </div>
        <button onClick={onOpenNewRun} className="btn-primary hero-btn">
          <Plus size={16} />
          <span>{t('header_new_run')}</span>
        </button>
      </div>

      {/* 4 Stat Overview Cards */}
      <div className="dashboard-metrics-grid">
        <div className="metric-box metric-total">
          <div className="metric-header">
            <span className="metric-label">{t('dash_total_runs')}</span>
            <FolderGit2 size={18} className="text-sky-400" />
          </div>
          <span className="metric-number">{totalRuns}</span>
        </div>

        <div className="metric-box metric-active">
          <div className="metric-header">
            <span className="metric-label">{t('dash_active_runs')}</span>
            <Activity size={18} className="text-amber-400" />
          </div>
          <span className="metric-number text-amber-300">{activeRuns}</span>
        </div>

        <div className="metric-box metric-final">
          <div className="metric-header">
            <span className="metric-label">{t('dash_final_runs')}</span>
            <CheckCircle2 size={18} className="text-emerald-400" />
          </div>
          <span className="metric-number text-emerald-300">{finalRuns}</span>
        </div>

        <div className="metric-box metric-failed">
          <div className="metric-header">
            <span className="metric-label">{t('dash_failed_runs')}</span>
            <AlertTriangle size={18} className="text-rose-400" />
          </div>
          <span className="metric-number text-rose-300">{failedRuns}</span>
        </div>
      </div>

      {/* Runs Table Card */}
      <div className="dashboard-runs-card">
        <div className="dashboard-card-header">
          <h2 className="dashboard-card-title">{t('dash_recent_runs')}</h2>
          <button
            onClick={onRefresh}
            disabled={isLoading}
            className="btn-secondary btn-sm"
            title={t('header_refresh_tooltip')}
          >
            <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} />
            <span>{isLoading ? '...' : ''}</span>
          </button>
        </div>

        {runs.length === 0 ? (
          <div className="empty-dashboard-state">
            <FolderGit2 size={36} className="text-slate-600 mb-2" />
            <p className="text-sm text-slate-400 mb-3">{t('dash_no_runs_desc')}</p>
            <button onClick={onOpenNewRun} className="btn-primary btn-sm">
              <Plus size={14} />
              <span>{t('header_new_run')}</span>
            </button>
          </div>
        ) : (
          <div className="dashboard-table-wrapper">
            <table className="dashboard-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>{t('dash_col_goal')}</th>
                  <th>{t('dash_col_status')}</th>
                  <th>{t('dash_col_revision')}</th>
                  <th>{t('dash_col_created')}</th>
                  <th className="text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr
                    key={r.run_id}
                    className="dashboard-table-row"
                    onClick={() => onSelectRun(r.run_id)}
                  >
                    <td className="font-mono text-sky-400 font-semibold whitespace-nowrap text-xs">
                      {r.run_id}
                    </td>
                    <td>
                      <span className="line-clamp-1 font-medium text-slate-100 text-sm">
                        {r.goal}
                      </span>
                      <span className="text-xs text-slate-400 uppercase tracking-wider block font-mono mt-0.5">
                        Phase: {r.phase}
                      </span>
                    </td>
                    <td>{getStatusBadge(r.status)}</td>
                    <td className="font-mono text-xs text-slate-300 whitespace-nowrap">
                      Rev {r.revision}
                    </td>
                    <td className="text-xs text-slate-400 whitespace-nowrap">
                      <span className="inline-flex items-center gap-1">
                        <Clock size={11} /> {formatDate(r.created_at)}
                      </span>
                    </td>
                    <td className="text-right whitespace-nowrap">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectRun(r.run_id);
                        }}
                        className="btn-secondary btn-sm"
                      >
                        <span>{t('dash_btn_open_run')}</span>
                        <ArrowRight size={12} />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteRun(r.run_id);
                        }}
                        className="btn-danger-sm ml-2"
                        title={t('dash_btn_delete_run')}
                        disabled={isDeletingId === r.run_id}
                      >
                        <Trash2 size={12} />
                        <span>{isDeletingId === r.run_id ? '...' : t('dash_btn_delete_run')}</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
