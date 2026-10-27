import React, { useState } from 'react';
import type { RunSummary } from '../types';
import { useI18n } from '../i18nContext';
import { useReveal } from '../hooks/useReveal';
import { ServerOfflinePanel } from './ServerOfflinePanel';
import {
  Plus,
  RefreshCw,
  Settings,
  Server,
  ServerOff,
  Cpu,
  Sparkles,
  Compass,
  CheckCircle2,
  Trash2,
  Search,
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
  retryCountdown?: number;
  onRetry?: () => void;
  isRetrying?: boolean;
}

const PHASES_11 = [
  { num: '01', name: 'INTAKE' },
  { num: '02', name: 'DECOMPOSE' },
  { num: '03', name: 'DRAFT' },
  { num: '04', name: 'CHALLENGE' },
  { num: '05', name: 'SYNTHESIZE' },
  { num: '06', name: 'EXECUTE' },
  { num: '07', name: 'VERIFY' },
  { num: '08', name: 'CRITIQUE' },
  { num: '09', name: 'CONVERGE' },
  { num: '10', name: 'GATE_CHECK' },
  { num: '11', name: 'EXPORT' },
];

const BACKEND_PHASE_ORDER = [
  'INTAKE',
  'SNAPSHOT',
  'INVESTIGATE',
  'INDEPENDENT_ANALYSIS',
  'PROPOSE',
  'REVIEW',
  'VERIFY',
  'REVISE',
  'SEMANTIC_REVIEW',
  'QUALITY_GATE',
  'EXPORT',
];

export const DashboardHome: React.FC<DashboardHomeProps> = ({
  runs,
  onSelectRun,
  onDeleteRun,
  onOpenNewRun,
  onOpenSettings,
  isBackendOffline = false,
  hasConfiguredProvider = false,
  retryCountdown = 10,
  onRetry,
  isRetrying = false,
}) => {
  const { t, lang } = useI18n();
  const setupRef = useReveal<HTMLDivElement>();
  const phasesRef = useReveal<HTMLDivElement>();

  const [searchTerm, setSearchTerm] = useState('');
  const [filterStatus, setFilterStatus] = useState<'ALL' | 'RUNNING' | 'FINAL'>('ALL');

  const totalRuns = runs.length;

  const getPhaseIndex = (phaseName: string, status: string): number => {
    if (status === 'FINAL') return 11;
    const idx = BACKEND_PHASE_ORDER.indexOf(phaseName);
    return idx >= 0 ? idx + 1 : 1;
  };

  const filteredRuns = runs.filter((r) => {
    const matchesSearch =
      r.run_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      r.goal.toLowerCase().includes(searchTerm.toLowerCase());
    if (!matchesSearch) return false;
    if (filterStatus === 'RUNNING') return r.status === 'RUNNING' || r.status === 'WAITING_FOR_INPUT';
    if (filterStatus === 'FINAL') return r.status === 'FINAL';
    return true;
  });

  const formatDate = (isoStr: string) => {
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString(lang === 'VN' ? 'vi-VN' : 'en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoStr;
    }
  };

  return (
    <div className="w-full bg-[var(--bg)] min-h-screen overflow-x-hidden">
      {/* 1. Hero Section (Image 1) */}
      <section className="max-w-[1280px] mx-auto px-6 sm:px-10 lg:px-16 py-12 lg:py-16 flex flex-col lg:flex-row items-center justify-between gap-10 lg:gap-12 w-full">
        {/* Left Column: Title, Subtitle, CTA buttons */}
        <div className="flex-1 max-w-xl rise">
          {/* Breadcrumb Chip */}
          <div className="mb-5 inline-flex">
            <span className="chip chip-neutral font-medium text-[13px] px-3.5 py-1">
              {t('dash_home_breadcrumb').replace('{count}', String(totalRuns))}
            </span>
          </div>

          {/* Big H1 */}
          <h1 className="text-[clamp(32px,3.8vw,54px)] font-medium text-[#202124] tracking-[-0.025em] leading-[1.12] mb-5">
            {lang === 'VN' ? (
              <>
                {t('dash_hero_title_1')}{' '}
                <span className="text-[#1967D2]">{t('dash_hero_title_2')}</span>
              </>
            ) : (
              <>
                <span className="text-[#1967D2]">{t('dash_hero_title_1')}</span>{' '}
                {t('dash_hero_title_2')}
              </>
            )}
          </h1>

          {/* Subtitle */}
          <p className="text-[17px] sm:text-[18px] text-[#5F6368] leading-relaxed mb-8 font-normal max-w-lg">
            {t('dash_welcome_subtitle')}
          </p>

          {/* Action Pills */}
          <div className="flex items-center flex-wrap gap-3.5">
            {isBackendOffline ? (
              <button
                type="button"
                onClick={onRetry}
                disabled={isRetrying}
                className="h-[48px] sm:h-[52px] px-6 sm:px-7 rounded-full bg-[#1967D2] text-white hover:brightness-95 btn-fill font-medium text-[15px] flex items-center gap-2.5 shadow-sm cursor-pointer"
              >
                <RefreshCw size={17} className={isRetrying ? 'animate-spin' : ''} />
                <span>{t('dash_retry_conn_btn')}</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={onOpenNewRun}
                className="h-[48px] sm:h-[52px] px-6 sm:px-7 rounded-full bg-[#1967D2] text-white hover:brightness-95 btn-fill font-medium text-[15px] flex items-center gap-2.5 shadow-sm cursor-pointer"
              >
                <Plus size={18} />
                <span>{totalRuns === 0 ? t('dash_first_run_btn') : t('header_new_run')}</span>
              </button>
            )}

            <button
              type="button"
              onClick={onOpenSettings}
              disabled={isBackendOffline}
              className={`h-[48px] sm:h-[52px] px-6 sm:px-7 rounded-full border border-[#DADCE0] font-medium text-[15px] flex items-center gap-2.5 transition-colors ${
                isBackendOffline
                  ? 'bg-[#F1F3F4] text-[#5F6368] opacity-60 cursor-not-allowed'
                  : 'bg-white text-[#202124] hover:bg-[#F8F9FA] cursor-pointer'
              }`}
            >
              <Settings size={17} />
              <span>{t('dash_config_provider_btn')}</span>
            </button>
          </div>
        </div>

        {/* Right Column: Gradient Aura & Server Panel */}
        <div className="flex-1 max-w-lg w-full rise delay-100">
          <div className="relative rounded-[32px] p-6 sm:p-8 overflow-hidden flex items-center justify-center min-h-[360px] bg-gradient-to-br from-[#EBF3FE] via-[#F4EDFC] to-[#FEF7E6] border border-[#E8EAED]">
            {/* Blurry drift decorative circles */}
            <div
              className="absolute -top-10 -left-10 w-56 h-56 rounded-full bg-[#C2D7FB] filter blur-[42px] opacity-70 drift pointer-events-none"
              aria-hidden="true"
            />
            <div
              className="absolute -bottom-10 -right-10 w-56 h-56 rounded-full bg-[#FDE7A8] filter blur-[42px] opacity-70 drift pointer-events-none"
              style={{ animationDelay: '4s' }}
              aria-hidden="true"
            />

            {/* Inner Content Card */}
            {isBackendOffline ? (
              <ServerOfflinePanel
                countdown={retryCountdown}
                totalCountdown={10}
                onRetry={onRetry}
                isRetrying={isRetrying}
              />
            ) : (
              <div className="bg-white border border-[#DADCE0] rounded-[24px] p-6 sm:p-7 shadow-[0_1px_3px_rgba(60,64,67,.12),0_10px_28px_rgba(60,64,67,.10)] w-full relative z-10">
                <div className="flex items-center justify-between gap-3 mb-4">
                  <h3 className="text-[19px] font-medium text-[#202124] tracking-tight">
                    {t('dash_server_running_card')}
                  </h3>
                  <span className="chip chip-success font-mono text-[11px] py-0.5 px-2.5">
                    <span className="w-2 h-2 rounded-full bg-[var(--success)]" />
                    {t('header_server_connected')}
                  </span>
                </div>

                <div className="bg-[#F1F3F4] rounded-[16px] p-3.5 mb-4 font-mono text-[13px] text-[#202124] flex items-center justify-between">
                  <span>http://localhost:8000</span>
                  <span className="text-[11px] text-[#5F6368] uppercase font-medium">FastAPI</span>
                </div>

                <div className="space-y-2.5 text-[14px] text-[#5F6368] mb-5">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 size={16} className="text-[var(--success)] shrink-0" />
                    <span>REST API v1 · SSE Streaming</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <CheckCircle2 size={16} className="text-[var(--success)] shrink-0" />
                    <span>
                      {totalRuns} {t('setup_status_n_runs', `${totalRuns} runs`).replace('{count}', String(totalRuns))}
                    </span>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={onOpenNewRun}
                  className="w-full h-11 rounded-full bg-[#1967D2] text-white font-medium text-[14px] btn-fill flex items-center justify-center gap-2 cursor-pointer shadow-sm"
                >
                  <Plus size={16} />
                  <span>{t('header_new_run')}</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* 2. Run Cards Grid (when runs > 0) */}
      {totalRuns > 0 && (
        <section className="bg-[var(--bg)] py-12 px-6 sm:px-10 lg:px-16 border-t border-[var(--border)]">
          <div className="max-w-[1280px] mx-auto">
            {/* Header & Filter Controls */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
              <div>
                <h2 className="text-[26px] font-medium text-[var(--text)] tracking-tight">
                  {t('dash_all_runs_title')}
                </h2>
              </div>

              <div className="flex items-center flex-wrap gap-3">
                {/* Search Input Pill */}
                <div className="relative">
                  <Search size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-2)]" />
                  <input
                    type="text"
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    placeholder={t('dash_search_runs_placeholder')}
                    className="h-10 pl-9 pr-4 rounded-full border border-[var(--border-strong)] bg-[var(--bg)] text-[14px] text-[var(--text)] focus:outline-none focus:border-[var(--accent)] w-56 sm:w-64"
                  />
                </div>

                {/* Filter Pills */}
                <div className="flex items-center gap-1 bg-[var(--surface-tonal)] p-1 rounded-full">
                  <button
                    type="button"
                    onClick={() => setFilterStatus('ALL')}
                    className={`h-8 px-3.5 rounded-full text-[13px] font-medium transition-colors cursor-pointer ${
                      filterStatus === 'ALL'
                        ? 'bg-[var(--bg)] text-[var(--text)] shadow-sm'
                        : 'text-[var(--text-2)] hover:text-[var(--text)]'
                    }`}
                  >
                    {t('dash_filter_all')}
                  </button>
                  <button
                    type="button"
                    onClick={() => setFilterStatus('RUNNING')}
                    className={`h-8 px-3.5 rounded-full text-[13px] font-medium transition-colors cursor-pointer ${
                      filterStatus === 'RUNNING'
                        ? 'bg-[var(--bg)] text-[var(--text)] shadow-sm'
                        : 'text-[var(--text-2)] hover:text-[var(--text)]'
                    }`}
                  >
                    {t('dash_filter_running')}
                  </button>
                  <button
                    type="button"
                    onClick={() => setFilterStatus('FINAL')}
                    className={`h-8 px-3.5 rounded-full text-[13px] font-medium transition-colors cursor-pointer ${
                      filterStatus === 'FINAL'
                        ? 'bg-[var(--bg)] text-[var(--text)] shadow-sm'
                        : 'text-[var(--text-2)] hover:text-[var(--text)]'
                    }`}
                  >
                    {t('dash_filter_final')}
                  </button>
                </div>
              </div>
            </div>

            {/* Grid of 28px rounded Run Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {filteredRuns.map((r) => {
                const phaseIdx = getPhaseIndex(r.phase, r.status);
                const progressPercent = Math.min(100, Math.round((phaseIdx / 11) * 100));

                return (
                  <div
                    key={r.run_id}
                    onClick={() => onSelectRun(r.run_id)}
                    className="bg-white border border-[#E8EAED] hover:border-[#1967D2] rounded-[28px] p-6 lift cursor-pointer flex flex-col justify-between transition-all shadow-[0_1px_2px_rgba(60,64,67,.08)] min-h-[220px]"
                  >
                    <div>
                      {/* Top ID & Status Badge */}
                      <div className="flex items-center justify-between gap-3 mb-3">
                        <span className="font-mono text-[12px] px-2.5 py-0.5 rounded-full border border-[var(--border-strong)] text-[var(--text-2)] font-medium">
                          {r.run_id}
                        </span>

                        {r.status === 'RUNNING' && (
                          <span className="chip chip-accent text-[12px] py-0.5 px-2.5">
                            <span className="w-2 h-2 rounded-full bg-[var(--accent)] pulse" />
                            {t('status_running')}
                          </span>
                        )}
                        {r.status === 'WAITING_FOR_INPUT' && (
                          <span className="chip chip-warn text-[12px] py-0.5 px-2.5">
                            {t('status_waiting')}
                          </span>
                        )}
                        {r.status === 'FINAL' && (
                          <span className="chip chip-success text-[12px] py-0.5 px-2.5">
                            {t('status_final')}
                          </span>
                        )}
                        {r.status === 'PARTIAL' && (
                          <span className="chip chip-warn text-[12px] py-0.5 px-2.5">
                            {t('status_partial')}
                          </span>
                        )}
                        {r.status === 'CANCELLED' && (
                          <span className="chip chip-neutral text-[12px] py-0.5 px-2.5">
                            {t('status_cancelled')}
                          </span>
                        )}
                        {r.status === 'FAILED' && (
                          <span className="chip chip-error text-[12px] py-0.5 px-2.5">
                            {t('status_failed')}
                          </span>
                        )}
                      </div>

                      {/* Goal Title */}
                      <h3 className="text-[18px] font-medium text-[var(--text)] line-clamp-2 mb-3 tracking-tight">
                        {r.goal}
                      </h3>

                      {/* Revision and Phase Progress text */}
                      <div className="text-[13px] font-mono text-[var(--text-2)] mb-2">
                        r{r.revision} · Giai đoạn {String(phaseIdx).padStart(2, '0')} / 11
                      </div>

                      {/* Progress Bar */}
                      <div
                        className="h-[6px] w-full bg-[var(--surface-tonal)] rounded-full overflow-hidden mb-4"
                        role="img"
                        aria-label={`Tiến độ ${progressPercent}%`}
                      >
                        <div
                          className="bg-[var(--accent)] h-full rounded-full transition-all duration-300"
                          style={{ width: `${progressPercent}%` }}
                        />
                      </div>
                    </div>

                    {/* Bottom Metadata & Delete */}
                    <div className="flex items-center justify-between text-[12px] text-[var(--text-2)] pt-3 border-t border-[var(--border)]">
                      <span className="font-mono">{formatDate(r.created_at)}</span>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteRun(r.run_id);
                        }}
                        className="w-8 h-8 rounded-full flex items-center justify-center text-[var(--text-2)] hover:text-[var(--error)] hover:bg-[var(--error-tonal)] transition-colors cursor-pointer"
                        title={t('dash_btn_delete_run')}
                        aria-label={t('dash_btn_delete_run')}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      )}

      {/* 3. Section: "Thiết lập trước khi bắt đầu" (Image 1) */}
      <section className="bg-[var(--bg-alt)] py-16 sm:py-20 px-6 sm:px-10 lg:px-16 border-t border-[var(--border)]">
        <div ref={setupRef} className="max-w-[1280px] mx-auto reveal">
          <h2 className="text-[clamp(26px,3.2vw,36px)] font-medium text-[#202124] tracking-[-0.02em] mb-2">
            {t('dash_setup_title')}
          </h2>
          <p className="text-[16px] text-[#5F6368] mb-10">
            {t('dash_setup_subtitle')}
          </p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Card 1: Backend Server */}
            <div className="bg-white rounded-[28px] p-7 border border-[#E8EAED] lift flex flex-col justify-between shadow-[0_1px_3px_rgba(60,64,67,.06)] min-h-[200px]">
              <div>
                <div className="flex items-center justify-between gap-3 mb-4">
                  <div
                    className={`w-[50px] h-[50px] rounded-full flex items-center justify-center ${
                      isBackendOffline
                        ? 'bg-[var(--error-tonal)] text-[var(--error)]'
                        : 'bg-[var(--success-tonal)] text-[var(--success)]'
                    }`}
                  >
                    {isBackendOffline ? <ServerOff size={22} /> : <Server size={22} />}
                  </div>
                  {isBackendOffline ? (
                    <span className="chip chip-error">{t('setup_status_disconnected')}</span>
                  ) : (
                    <span className="chip chip-success">{t('setup_status_connected')}</span>
                  )}
                </div>
                <h3 className="text-[20px] font-medium text-[#202124] tracking-tight mb-2">
                  {t('setup_card_server_title')}
                </h3>
                <p className="text-[14px] text-[#5F6368] leading-relaxed">
                  {t('setup_card_server_desc')}
                </p>
              </div>
            </div>

            {/* Card 2: LLM Providers */}
            <div className="bg-white rounded-[28px] p-7 border border-[#E8EAED] lift flex flex-col justify-between shadow-[0_1px_3px_rgba(60,64,67,.06)] min-h-[200px]">
              <div>
                <div className="flex items-center justify-between gap-3 mb-4">
                  <div
                    className={`w-[50px] h-[50px] rounded-full flex items-center justify-center ${
                      isBackendOffline
                        ? 'bg-[var(--surface-tonal)] text-[var(--text-2)]'
                        : hasConfiguredProvider
                        ? 'bg-[var(--accent-tonal)] text-[var(--accent-on-tonal)]'
                        : 'bg-[var(--warn-tonal)] text-[var(--warn)]'
                    }`}
                  >
                    {hasConfiguredProvider ? <Sparkles size={22} /> : <Cpu size={22} />}
                  </div>
                  {isBackendOffline ? (
                    <span className="chip chip-neutral">{t('setup_status_need_server')}</span>
                  ) : hasConfiguredProvider ? (
                    <span className="chip chip-success">{t('setup_status_configured')}</span>
                  ) : (
                    <span className="chip chip-warn">{t('setup_status_unconfigured')}</span>
                  )}
                </div>
                <h3 className="text-[20px] font-medium text-[#202124] tracking-tight mb-2">
                  {t('setup_card_llm_title')}
                </h3>
                <p className="text-[14px] text-[#5F6368] leading-relaxed">
                  {t('setup_card_llm_desc')}
                </p>
              </div>
            </div>

            {/* Card 3: First Architecture Run */}
            <div className="bg-white rounded-[28px] p-7 border border-[#E8EAED] lift flex flex-col justify-between shadow-[0_1px_3px_rgba(60,64,67,.06)] min-h-[200px]">
              <div>
                <div className="flex items-center justify-between gap-3 mb-4">
                  <div className="w-[50px] h-[50px] rounded-full bg-[var(--surface-tonal)] text-[#202124] flex items-center justify-center">
                    <Compass size={22} />
                  </div>
                  {isBackendOffline ? (
                    <span className="chip chip-neutral">{t('setup_status_need_server')}</span>
                  ) : totalRuns === 0 ? (
                    <span className="chip chip-neutral">{t('setup_status_no_runs')}</span>
                  ) : (
                    <span className="chip chip-accent">
                      {totalRuns} {lang === 'VN' ? 'phiên' : 'runs'}
                    </span>
                  )}
                </div>
                <h3 className="text-[20px] font-medium text-[#202124] tracking-tight mb-2">
                  {t('setup_card_run_title')}
                </h3>
                <p className="text-[14px] text-[#5F6368] leading-relaxed">
                  {t('setup_card_run_desc')}
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 4. Section: "Một phiên chạy qua 11 giai đoạn" (Image 1) */}
      <section className="bg-[var(--bg)] py-16 sm:py-20 px-6 sm:px-10 lg:px-16 border-t border-[var(--border)]">
        <div ref={phasesRef} className="max-w-[1280px] mx-auto reveal">
          <h2 className="text-[clamp(26px,3.2vw,36px)] font-medium text-[#202124] tracking-[-0.02em] mb-2">
            {t('dash_11_phases_title')}
          </h2>
          <p className="text-[16px] text-[#5F6368] mb-8">
            {t('dash_11_phases_subtitle')}
          </p>

          {/* 11 Horizontal Pills */}
          <div className="flex flex-wrap gap-2 mb-12">
            {PHASES_11.map((p) => (
              <div
                key={p.num}
                className="h-10 px-4 rounded-full bg-[#F1F3F4] text-[#3C4043] font-mono text-[12px] font-medium inline-flex items-center gap-1.5 pill border border-transparent hover:border-[#DADCE0] transition-all select-none"
              >
                <span className="text-[#5F6368] opacity-75">{p.num}</span>
                <span>{p.name}</span>
              </div>
            ))}
          </div>

          {/* 4 Agent Cards: P, R, S, V */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {/* Planner */}
            <div className="bg-[#E8F0FE] text-[#174EA6] rounded-[28px] p-6 lift border border-[#1967D2]/15 flex flex-col justify-between min-h-[180px]">
              <div>
                <div className="w-11 h-11 rounded-full bg-[#1967D2] text-white font-bold text-lg flex items-center justify-center mb-4 shadow-sm">
                  P
                </div>
                <h3 className="text-[20px] font-medium mb-1 tracking-tight text-[#174EA6]">
                  {t('agent_planner_name')}
                </h3>
                <p className="text-[14px] text-[#174EA6]/85 leading-relaxed">
                  {t('agent_planner_desc')}
                </p>
              </div>
            </div>

            {/* Reviewer */}
            <div className="bg-[#FCE8E6] text-[#A50E0E] rounded-[28px] p-6 lift border border-[#C5221F]/15 flex flex-col justify-between min-h-[180px]">
              <div>
                <div className="w-11 h-11 rounded-full bg-[#C5221F] text-white font-bold text-lg flex items-center justify-center mb-4 shadow-sm">
                  R
                </div>
                <h3 className="text-[20px] font-medium mb-1 tracking-tight text-[#A50E0E]">
                  {t('agent_reviewer_name')}
                </h3>
                <p className="text-[14px] text-[#A50E0E]/85 leading-relaxed">
                  {t('agent_reviewer_desc')}
                </p>
              </div>
            </div>

            {/* Synthesizer */}
            <div className="bg-[#FEF7E0] text-[#7A4F01] rounded-[28px] p-6 lift border border-[#F9AB00]/25 flex flex-col justify-between min-h-[180px]">
              <div>
                <div className="w-11 h-11 rounded-full bg-[#F9AB00] text-[#202124] font-bold text-lg flex items-center justify-center mb-4 shadow-sm">
                  S
                </div>
                <h3 className="text-[20px] font-medium mb-1 tracking-tight text-[#7A4F01]">
                  {t('agent_synthesizer_name')}
                </h3>
                <p className="text-[14px] text-[#7A4F01]/85 leading-relaxed">
                  {t('agent_synthesizer_desc')}
                </p>
              </div>
            </div>

            {/* Verifier */}
            <div className="bg-[#E6F4EA] text-[#0D652D] rounded-[28px] p-6 lift border border-[#1E8E3E]/20 flex flex-col justify-between min-h-[180px]">
              <div>
                <div className="w-11 h-11 rounded-full bg-[#1E8E3E] text-white font-bold text-lg flex items-center justify-center mb-4 shadow-sm">
                  V
                </div>
                <h3 className="text-[20px] font-medium mb-1 tracking-tight text-[#0D652D]">
                  {t('agent_verifier_name')}
                </h3>
                <p className="text-[14px] text-[#0D652D]/85 leading-relaxed">
                  {t('agent_verifier_desc')}
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
};
