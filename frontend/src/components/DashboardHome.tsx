import React from 'react';
import type { RunSummary } from '../types';
import { useI18n } from '../i18nContext';
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
  Sparkles,
  Settings,
} from 'lucide-react';

interface DashboardHomeProps {
  runs: RunSummary[];
  onSelectRun: (runId: string) => void;
  onDeleteRun: (runId: string) => void;
  onOpenNewRun: () => void;
  onOpenSettings?: () => void;
  onRefresh: () => void;
  isLoading: boolean;
  isDeletingId?: string | null;
  isBackendOffline?: boolean;
  hasConfiguredProvider?: boolean;
}

export const DashboardHome: React.FC<DashboardHomeProps> = ({
  runs,
  onSelectRun,
  onDeleteRun,
  onOpenNewRun,
  onOpenSettings,
  onRefresh,
  isLoading,
  isDeletingId,
  isBackendOffline,
  hasConfiguredProvider,
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
        <button
          onClick={onOpenNewRun}
          disabled={isBackendOffline}
          title={isBackendOffline ? t('onboarding_offline_tooltip') : undefined}
          className="btn-primary hero-btn"
        >
          <Plus size={16} />
          <span>{t('header_new_run')}</span>
        </button>
      </div>

      {/* Either Onboarding Block (when 0 runs) or 4 Stat Overview Cards */}
      {totalRuns === 0 ? (
        <div className="onboarding-card">
          <div className="onboarding-header">
            <div className="flex items-center justify-between gap-4">
              <div className="onboarding-badge">
                <Sparkles size={20} className="text-sky-400" />
                <h2 className="text-lg font-bold text-slate-100">{t('onboarding_title')}</h2>
              </div>
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
            <p className="onboarding-desc">{t('onboarding_desc')}</p>
          </div>

          {/* Checklist 3 bước có trạng thái tick */}
          <div className="onboarding-steps">
            {/* Bước 1: Cấu hình nhà cung cấp LLM */}
            <div className={`onboarding-step-item ${hasConfiguredProvider ? 'step-completed' : 'step-current'}`}>
              <div className="onboarding-step-status">
                {hasConfiguredProvider ? (
                  <div className="step-icon-done" title={t('onboarding_step1_done')}>
                    <CheckCircle2 size={22} className="text-emerald-400" />
                  </div>
                ) : (
                  <div className="step-icon-number">1</div>
                )}
              </div>
              <div className="onboarding-step-body">
                <div className="onboarding-step-title-row">
                  <h3 className="onboarding-step-title">{t('onboarding_step1_title')}</h3>
                  {hasConfiguredProvider ? (
                    <span className="badge-final text-[11px] flex items-center gap-1">
                      <CheckCircle2 size={11} /> {t('onboarding_step1_done')}
                    </span>
                  ) : onOpenSettings ? (
                    <button
                      type="button"
                      onClick={onOpenSettings}
                      disabled={isBackendOffline}
                      title={isBackendOffline ? t('onboarding_offline_tooltip') : undefined}
                      className="btn-secondary-sm text-xs"
                    >
                      <Settings size={12} />
                      <span>{t('onboarding_step1_action')}</span>
                    </button>
                  ) : null}
                </div>
                <p className="onboarding-step-desc">{t('onboarding_step1_desc')}</p>
              </div>
            </div>

            {/* Bước 2: Tạo phiên đầu tiên */}
            <div className={`onboarding-step-item ${totalRuns > 0 ? 'step-completed' : hasConfiguredProvider ? 'step-current' : 'step-pending'}`}>
              <div className="onboarding-step-status">
                {totalRuns > 0 ? (
                  <div className="step-icon-done">
                    <CheckCircle2 size={22} className="text-emerald-400" />
                  </div>
                ) : (
                  <div className="step-icon-number">2</div>
                )}
              </div>
              <div className="onboarding-step-body">
                <div className="onboarding-step-title-row">
                  <h3 className="onboarding-step-title">{t('onboarding_step2_title')}</h3>
                </div>
                <p className="onboarding-step-desc">{t('onboarding_step2_desc')}</p>
              </div>
            </div>

            {/* Bước 3: Xem kết quả */}
            <div className={`onboarding-step-item ${finalRuns > 0 ? 'step-completed' : 'step-pending'}`}>
              <div className="onboarding-step-status">
                {finalRuns > 0 ? (
                  <div className="step-icon-done">
                    <CheckCircle2 size={22} className="text-emerald-400" />
                  </div>
                ) : (
                  <div className="step-icon-number">3</div>
                )}
              </div>
              <div className="onboarding-step-body">
                <div className="onboarding-step-title-row">
                  <h3 className="onboarding-step-title">{t('onboarding_step3_title')}</h3>
                </div>
                <p className="onboarding-step-desc">{t('onboarding_step3_desc')}</p>
              </div>
            </div>
          </div>

          {/* CTA Footer */}
          <div className="onboarding-footer">
            <button
              type="button"
              onClick={onOpenNewRun}
              disabled={isBackendOffline}
              title={isBackendOffline ? t('onboarding_offline_tooltip') : undefined}
              className="btn-primary btn-onboarding-cta"
            >
              <Plus size={16} />
              <span>{t('onboarding_btn_create_first_run')}</span>
              <ArrowRight size={14} />
            </button>

            {isBackendOffline && (
              <div className="onboarding-offline-banner" role="status">
                <AlertTriangle size={15} className="text-amber-400 flex-shrink-0" />
                <span>{t('onboarding_offline_notice')}</span>
              </div>
            )}
          </div>
        </div>
      ) : (
        <>
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

            <div className="dashboard-table-wrapper">
              <table className="dashboard-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>{t('dash_col_goal')}</th>
                    <th>{t('dash_col_status')}</th>
                    <th>{t('dash_col_revision')}</th>
                    <th>{t('dash_col_created')}</th>
                    <th className="text-right">{t('dash_col_action')}</th>
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
                          {t('dash_phase_prefix').replace('{phase}', r.phase)}
                        </span>
                      </td>
                      <td>{getStatusBadge(r.status)}</td>
                      <td className="font-mono text-xs text-slate-300 whitespace-nowrap">
                        {t('dash_revision_prefix').replace('{revision}', String(r.revision))}
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
          </div>
        </>
      )}
    </div>
  );
};
