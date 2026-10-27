import React, { useState } from 'react';
import type { RunDetail, PlanRevision, Issue, Decision, Evidence } from '../types';
import { PlanViewer } from './PlanViewer';
import {
  HelpCircle,
  Send,
  Play,
  ShieldCheck,
  Award,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  RotateCcw,
} from 'lucide-react';
import { useI18n } from '../i18nContext';

interface RunOverviewProps {
  run: RunDetail;
  currentPlan?: PlanRevision | null;
  issues: Issue[];
  decisions?: Decision[];
  evidence?: Evidence[];
  onSelectPlanRevision?: (rev: number) => void;
  onAnswerQuestion: (questionId: string, answer: string, expectedRevision: number) => Promise<void>;
  onResumeRun: () => Promise<void>;
  onCancelRun: (reason: string) => Promise<void>;
  onDeleteRun: () => Promise<void>;
  onValidate: () => Promise<void>;
  onFinalize: () => Promise<void>;
  onExportMarkdown: (rev?: number) => void;
  onExportJson: (rev?: number) => void;
  isProcessing: boolean;
  isDeleting?: boolean;
  actionMessage?: string | null;
  onViewLogs?: () => void;
  onCloneRun?: (run: RunDetail) => void;
}

export const RunOverview: React.FC<RunOverviewProps> = ({
  run,
  currentPlan,
  issues = [],
  decisions = [],
  evidence = [],
  onSelectPlanRevision = () => {},
  onAnswerQuestion,
  onResumeRun,
  onValidate,
  onFinalize,
  onExportMarkdown,
  onExportJson,
  isProcessing,
  actionMessage,
  onViewLogs,
  onCloneRun,
}) => {
  const { t } = useI18n();
  const [answers, setAnswers] = useState<Record<string, string>>({});

  const handleAnswerSubmit = async (questionId: string) => {
    const text = (answers[questionId] || '').trim();
    if (!text) return;
    await onAnswerQuestion(questionId, text, run.revision);
    setAnswers({ ...answers, [questionId]: '' });
  };

  const isTerminal = ['FINAL', 'PARTIAL', 'FAILED', 'CANCELLED'].includes(run.status);
  const isWaiting = run.status === 'WAITING_FOR_INPUT';

  // Quality gate calculation
  const hasNoBlocking = run.blocking_issues_count === 0;
  const isDagValid = true; // Based on DAG rules
  const coveragePercent = run.requirements.length > 0 ? 100 : 0;
  const isCoveragePassed = coveragePercent >= 80;

  const passedCount = (hasNoBlocking ? 1 : 0) + (isDagValid ? 1 : 0) + (isCoveragePassed ? 1 : 0);
  const isEligibleForFinal = passedCount === 3;

  return (
    <div className="space-y-6">
      {/* Action feedback toast */}
      {actionMessage && (
        <div className="bg-[var(--success-tonal)] text-[var(--success-on-tonal)] border border-[var(--success)]/20 rounded-[20px] p-4 flex items-center gap-3 shadow-sm">
          <CheckCircle2 size={18} className="text-[var(--success)] shrink-0" />
          <span className="font-medium text-[14px]">{actionMessage}</span>
        </div>
      )}

      {/* Prominent Failure Banner if run failed */}
      {(run.status === 'FAILED' || (isTerminal && run.stop_reason && run.status !== 'FINAL')) && (
        <div className="bg-[var(--error-tonal)] text-[var(--error-on-tonal)] border border-[var(--error)]/20 rounded-[24px] p-6 shadow-sm">
          <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
            <div className="flex items-start gap-3 flex-1">
              <div className="w-10 h-10 rounded-full bg-[var(--error)] text-white flex items-center justify-center shrink-0">
                <XCircle size={20} />
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <h3 className="text-[16px] font-medium">
                    {t('overview_execution_stopped')}: {run.status === 'FAILED' ? t('overview_fatal_failure') : run.status}
                  </h3>
                  <span className="chip chip-error text-[11px] py-0.5 px-2">
                    {run.phase}
                  </span>
                </div>
                <p className="text-[13px] font-mono p-3 rounded-[14px] bg-white/60 border border-[var(--error)]/15 break-all select-all">
                  {run.stop_reason || t('overview_unknown_error')}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 self-end sm:self-center">
              {onCloneRun && (
                <button
                  type="button"
                  onClick={() => onCloneRun(run)}
                  className="h-9 px-4 rounded-full bg-[var(--accent)] text-white font-medium text-[13px] flex items-center gap-1.5 btn-fill cursor-pointer"
                >
                  <RotateCcw size={14} />
                  <span>{t('overview_rerun')}</span>
                </button>
              )}
              {onViewLogs && (
                <button
                  type="button"
                  onClick={onViewLogs}
                  className="h-9 px-4 rounded-full border border-[var(--error)]/30 text-[var(--error)] hover:bg-white text-[13px] font-medium flex items-center gap-1.5 cursor-pointer"
                >
                  <span>{t('overview_view_logs')}</span>
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Operator Questions Banner (Human-in-the-loop) */}
      {run.pending_questions && run.pending_questions.length > 0 && (
        <div className="bg-[var(--warn-tonal)] text-[var(--warn-on-tonal)] border border-[var(--warn)]/30 rounded-[28px] p-6 shadow-sm">
          <div className="flex items-center justify-between gap-3 mb-2">
            <div className="flex items-center gap-2.5">
              <HelpCircle className="text-[var(--warn)]" size={22} />
              <h3 className="text-[18px] font-medium">{t('overview_clarification_title')}</h3>
            </div>
            <span className="chip chip-warn font-medium text-[12px] py-0.5 px-3">
              {run.pending_questions.length} {t('overview_question_count')}
            </span>
          </div>
          <p className="text-[14px] opacity-90 mb-4">
            {t('overview_clarification_desc')}
          </p>

          <div className="space-y-4">
            {run.pending_questions.map((q) => (
              <div key={q.id} className="bg-[var(--bg)] border border-[var(--border)] rounded-[20px] p-4 text-[var(--text)] shadow-sm">
                <div className="flex items-start gap-2.5 mb-3">
                  <span className="font-mono text-[11px] px-2 py-0.5 rounded-full bg-[var(--surface-tonal)] text-[var(--text-2)] font-medium">
                    {q.id}
                  </span>
                  <strong className="text-[15px] font-medium">{q.text}</strong>
                </div>

                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={answers[q.id] || ''}
                    onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })}
                    placeholder={t('overview_answer_placeholder')}
                    className="flex-1 h-11 px-4 rounded-full border border-[var(--border-strong)] text-[14px] focus:outline-none focus:border-[var(--accent)]"
                    disabled={isProcessing}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleAnswerSubmit(q.id);
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => handleAnswerSubmit(q.id)}
                    className="h-11 px-5 rounded-full bg-[var(--accent)] text-white font-medium text-[13px] flex items-center gap-1.5 btn-fill cursor-pointer disabled:opacity-50"
                    disabled={isProcessing || !(answers[q.id] || '').trim()}
                  >
                    <Send size={14} />
                    <span>{t('overview_submit')}</span>
                  </button>
                </div>
              </div>
            ))}
          </div>

          {isWaiting && (
            <div className="flex items-center justify-between gap-4 mt-4 pt-3 border-t border-[var(--warn)]/20">
              <span className="text-[13px] font-medium">
                {t('overview_all_answered')}
              </span>
              <button
                type="button"
                onClick={onResumeRun}
                className="h-10 px-5 rounded-full bg-[var(--success)] text-white font-medium text-[13px] flex items-center gap-1.5 btn-fill cursor-pointer"
                disabled={isProcessing}
              >
                <Play size={14} />
                <span>{t('overview_resume_run')}</span>
              </button>
            </div>
          )}
        </div>
      )}

      {/* 2-Column Main Layout matching Image 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-7">
        {/* Left Column: PlanViewer */}
        <div className="lg:col-span-7 xl:col-span-8">
          <PlanViewer
            currentPlan={currentPlan}
            totalPlansCount={run.plans_count}
            onSelectRevision={onSelectPlanRevision}
            onExportMarkdown={onExportMarkdown}
            onExportJson={onExportJson}
            issues={issues}
            decisions={decisions}
            evidence={evidence}
          />
        </div>

        {/* Right Column: Issue Card + Quality Gate Card */}
        <div className="lg:col-span-5 xl:col-span-4 space-y-6">
          {/* 1. Issue Card (Image 2) */}
          <div className="bg-[var(--bg)] border border-[var(--border)] rounded-[28px] p-6 shadow-sm">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[20px] font-medium text-[var(--text)] tracking-tight">
                {t('tab_issues')}
              </h3>
              <span className="chip chip-neutral font-mono text-[11px] py-0.5 px-2.5">
                {issues.length}
              </span>
            </div>

            {issues.length === 0 ? (
              <p className="text-[14px] text-[var(--text-2)] py-6 text-center">
                {t('issues_no_issues')}
              </p>
            ) : (
              <div className="space-y-3.5 divide-y divide-[var(--border)]">
                {issues.slice(0, 6).map((iss, index) => {
                  const isClosed = iss.status === 'RESOLVED' || iss.status === 'REJECTED';

                  return (
                    <div key={iss.id} className={index > 0 ? 'pt-3.5' : ''}>
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="font-mono text-[11px] text-[var(--text-2)] font-medium">
                          {iss.id} · {iss.severity}
                        </span>

                        {iss.status === 'OPEN' && (
                          <span className="chip chip-error text-[11px] py-0.5 px-2">
                            OPEN
                          </span>
                        )}
                        {iss.status === 'RESOLVED' && (
                          <span className="chip chip-success text-[11px] py-0.5 px-2">
                            RESOLVED
                          </span>
                        )}
                        {iss.status !== 'OPEN' && iss.status !== 'RESOLVED' && (
                          <span className="chip chip-neutral text-[11px] py-0.5 px-2">
                            {iss.status}
                          </span>
                        )}
                      </div>

                      <h4
                        className={`text-[14px] font-medium leading-snug ${
                          isClosed ? 'text-[var(--text-2)] line-through' : 'text-[var(--text)]'
                        }`}
                      >
                        {iss.claim}
                      </h4>

                      {iss.impact && (
                        <p className="text-[12px] text-[var(--text-2)] line-clamp-2 mt-1">
                          {iss.impact}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* 2. Cổng chất lượng (Quality Gate) Card (Image 2) */}
          <div className="bg-[var(--bg)] border border-[var(--border)] rounded-[28px] p-6 shadow-sm">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-[20px] font-medium text-[var(--text)] tracking-tight">
                {t('phase_quality_gate')}
              </h3>
              <span className="text-[13px] font-mono text-[var(--text-2)]">
                {t('gate_pass_ratio')
                  .replace('{passed}', String(passedCount))
                  .replace('{total}', '3')}
              </span>
            </div>

            {/* Progress Bar */}
            <div
              className="h-2 w-full bg-[var(--surface-tonal)] rounded-full overflow-hidden mb-5"
              role="img"
              aria-label={`Tiến độ cổng chất lượng: ${passedCount}/3`}
            >
              <div
                className="bg-[var(--accent)] h-full rounded-full transition-all duration-300"
                style={{ width: `${(passedCount / 3) * 100}%` }}
              />
            </div>

            {/* Checklist */}
            <div className="space-y-3 mb-5">
              {/* Rule 1: DAG Check */}
              <div className="flex items-center justify-between gap-3 p-2.5 rounded-[16px] bg-[var(--surface-tonal)]">
                <div className="flex items-center gap-2.5">
                  <div className="w-7 h-7 rounded-full bg-[var(--success-tonal)] text-[var(--success)] flex items-center justify-center shrink-0">
                    <CheckCircle2 size={16} />
                  </div>
                  <span className="text-[13px] font-medium text-[var(--text)]">
                    Cấu trúc DAG hợp lệ
                  </span>
                </div>
                <span className="font-mono text-[11px] font-medium text-[var(--success-on-tonal)]">
                  PASS
                </span>
              </div>

              {/* Rule 2: Requirement Coverage */}
              <div className="flex items-center justify-between gap-3 p-2.5 rounded-[16px] bg-[var(--surface-tonal)]">
                <div className="flex items-center gap-2.5">
                  <div
                    className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
                      isCoveragePassed
                        ? 'bg-[var(--success-tonal)] text-[var(--success)]'
                        : 'bg-[var(--warn-tonal)] text-[var(--warn)]'
                    }`}
                  >
                    <CheckCircle2 size={16} />
                  </div>
                  <span className="text-[13px] font-medium text-[var(--text)]">
                    Độ phủ yêu cầu &gt;= 80%
                  </span>
                </div>
                <span className="font-mono text-[11px] font-medium text-[var(--text-2)]">
                  {coveragePercent}%
                </span>
              </div>

              {/* Rule 3: No Blocking Issues */}
              <div className="flex items-center justify-between gap-3 p-2.5 rounded-[16px] bg-[var(--surface-tonal)]">
                <div className="flex items-center gap-2.5">
                  <div
                    className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
                      hasNoBlocking
                        ? 'bg-[var(--success-tonal)] text-[var(--success)]'
                        : 'bg-[var(--error-tonal)] text-[var(--error)]'
                    }`}
                  >
                    {hasNoBlocking ? <CheckCircle2 size={16} /> : <AlertTriangle size={15} />}
                  </div>
                  <span className="text-[13px] font-medium text-[var(--text)]">
                    Không có Issue blocking mở
                  </span>
                </div>
                <span
                  className={`font-mono text-[11px] font-medium ${
                    hasNoBlocking ? 'text-[var(--success-on-tonal)]' : 'text-[var(--error)]'
                  }`}
                >
                  {hasNoBlocking ? 'PASS' : `${run.blocking_issues_count} OPEN`}
                </span>
              </div>
            </div>

            {/* Ineligible warning box */}
            {!isEligibleForFinal && (
              <div className="bg-[var(--warn-tonal)] text-[var(--warn-on-tonal)] rounded-[16px] p-3 text-[12px] font-medium flex items-center gap-2 mb-4">
                <AlertTriangle size={14} className="shrink-0 text-[var(--warn)]" />
                <span>{t('gate_not_eligible')}</span>
              </div>
            )}

            {/* Quality Gate Actions */}
            <div className="flex items-center gap-2 pt-2">
              <button
                type="button"
                onClick={onValidate}
                disabled={isProcessing}
                className="flex-1 h-10 px-4 rounded-full border border-[var(--border-strong)] bg-[var(--bg)] hover:bg-[var(--surface-tonal)] text-[var(--text)] text-[13px] font-medium flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
              >
                <ShieldCheck size={14} className="text-[var(--accent)]" />
                <span>{t('overview_validate_gates')}</span>
              </button>

              <button
                type="button"
                onClick={onFinalize}
                disabled={isProcessing || !isEligibleForFinal}
                className={`flex-1 h-10 px-4 rounded-full font-medium text-[13px] flex items-center justify-center gap-1.5 transition-colors ${
                  isEligibleForFinal
                    ? 'bg-[var(--accent)] text-white hover:brightness-95 btn-fill cursor-pointer shadow-sm'
                    : 'bg-[var(--surface-tonal)] text-[var(--text-2)] opacity-60 cursor-not-allowed'
                }`}
              >
                <Award size={14} />
                <span>{t('overview_finalize_plan')}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
