import React, { useState } from 'react';
import type { RunDetail } from '../types';
import {
  HelpCircle,
  Send,
  Play,
  StopCircle,
  ShieldCheck,
  Award,
  Download,
  FileText,
  CheckCircle2,
  ListTodo,
} from 'lucide-react';
import { useI18n } from '../i18n';

interface RunOverviewProps {
  run: RunDetail;
  onAnswerQuestion: (questionId: string, answer: string, expectedRevision: number) => Promise<void>;
  onResumeRun: () => Promise<void>;
  onCancelRun: (reason: string) => Promise<void>;
  onValidate: () => Promise<void>;
  onFinalize: () => Promise<void>;
  onExportMarkdown: () => void;
  onExportJson: () => void;
  isProcessing: boolean;
  actionMessage?: string | null;
  onViewLogs?: () => void;
}

export const RunOverview: React.FC<RunOverviewProps> = ({
  run,
  onAnswerQuestion,
  onResumeRun,
  onCancelRun,
  onValidate,
  onFinalize,
  onExportMarkdown,
  onExportJson,
  isProcessing,
  actionMessage,
  onViewLogs,
}) => {
  const { t } = useI18n();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [cancelReason, setCancelReason] = useState('Stopped by operator');
  const [showCancelPrompt, setShowCancelPrompt] = useState(false);

  const handleAnswerSubmit = async (questionId: string) => {
    const text = (answers[questionId] || '').trim();
    if (!text) return;
    await onAnswerQuestion(questionId, text, run.revision);
    setAnswers({ ...answers, [questionId]: '' });
  };

  const isTerminal = ['FINAL', 'PARTIAL', 'FAILED', 'CANCELLED'].includes(run.status);
  const isWaiting = run.status === 'WAITING_FOR_INPUT';

  return (
    <div className="overview-container">
      {actionMessage && (
        <div className="action-feedback-banner">
          <CheckCircle2 size={16} className="text-emerald-400" />
          <span>{actionMessage}</span>
        </div>
      )}

      {/* Prominent Failure Banner if run failed */}
      {(run.status === 'FAILED' || (isTerminal && run.stop_reason && run.status !== 'FINAL')) && (
        <div className="run-failure-banner">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-start gap-3 flex-1">
              <span className="p-2 rounded-lg bg-rose-950/60 border border-rose-800/60 text-rose-400">
                ⚠️
              </span>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold text-rose-200">
                    {t('overview_execution_stopped')}: {run.status === 'FAILED' ? t('overview_fatal_failure') : run.status}
                  </h3>
                  <span className="badge-danger text-[11px]">Phase: {run.phase}</span>
                </div>
                <p className="text-xs text-rose-300/90 mt-1 font-mono break-words bg-rose-950/40 p-2.5 rounded border border-rose-900/40">
                  {run.stop_reason || 'Unknown error occurred during workflow execution.'}
                </p>
              </div>
            </div>

            {onViewLogs && (
              <button
                onClick={onViewLogs}
                className="btn-danger-sm flex items-center gap-1.5 whitespace-nowrap self-center"
              >
                <span>{t('overview_view_logs')}</span>
                <span>➔</span>
              </button>
            )}
          </div>
        </div>
      )}

      {/* Pending Questions Banner */}
      {run.pending_questions && run.pending_questions.length > 0 && (
        <div className="pending-questions-card">
          <div className="pending-header">
            <div className="flex-align-center gap-2">
              <HelpCircle className="text-amber-400" size={20} />
              <h3 className="card-title text-amber-300">{t('overview_clarification_title')}</h3>
            </div>
            <span className="badge-amber">{run.pending_questions.length} {t('overview_question_count')}</span>
          </div>
          <p className="card-desc">
            {t('overview_clarification_desc')}
          </p>

          <div className="questions-list">
            {run.pending_questions.map((q) => (
              <div key={q.id} className="question-item">
                <div className="question-text">
                  <span className="q-badge">{q.id}</span>
                  <strong>{q.text}</strong>
                </div>

                <div className="answer-input-row">
                  <input
                    type="text"
                    value={answers[q.id] || ''}
                    onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })}
                    placeholder={t('overview_answer_placeholder')}
                    className="form-input flex-1"
                    disabled={isProcessing}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleAnswerSubmit(q.id);
                    }}
                  />
                  <button
                    onClick={() => handleAnswerSubmit(q.id)}
                    className="btn-primary"
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
            <div className="resume-prompt-row">
              <span className="text-sm text-slate-300">
                {t('overview_all_answered')}
              </span>
              <button
                onClick={onResumeRun}
                className="btn-success"
                disabled={isProcessing}
              >
                <Play size={15} />
                <span>{t('overview_resume_run')}</span>
              </button>
            </div>
          )}
        </div>
      )}

      {/* Main Stats Grid */}
      <div className="stats-grid">
        <div className="stat-card">
          <span className="stat-label">{t('overview_goal')}</span>
          <span className="stat-value text-base font-medium">{run.goal}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">{t('overview_status_rev')}</span>
          <div className="flex-align-center gap-2 mt-1">
            <span className="font-semibold text-lg">{run.status}</span>
            <span className="badge-subtle">Rev {run.revision}</span>
          </div>
        </div>
        <div className="stat-card">
          <span className="stat-label">{t('overview_artifacts')}</span>
          <div className="stat-artifacts-grid">
            <div className="stat-artifact-item">
              <span>{t('overview_plans_count')}</span>
              <strong>{run.plans_count}</strong>
            </div>
            <div className="stat-artifact-item">
              <span>{t('overview_issues_count')}</span>
              <strong>{run.issues_count} {run.blocking_issues_count > 0 && `(${run.blocking_issues_count})`}</strong>
            </div>
            <div className="stat-artifact-item">
              <span>{t('overview_decisions_count')}</span>
              <strong>{run.decisions_count}</strong>
            </div>
            <div className="stat-artifact-item">
              <span>{t('overview_evidence_count')}</span>
              <strong>{run.evidence_count}</strong>
            </div>
          </div>
        </div>
      </div>

      {/* Requirements List */}
      <div className="section-card">
        <div className="flex-between mb-3">
          <div className="flex-align-center gap-2">
            <ListTodo size={18} className="text-sky-400" />
            <h3 className="card-title">{t('overview_target_requirements')} ({run.requirements.length})</h3>
          </div>
        </div>
        <div className="requirements-table">
          {run.requirements.map((req) => (
            <div key={req.id} className="req-row">
              <span className="req-id-badge">{req.id}</span>
              <div className="flex-1">
                <p className="text-sm font-medium text-slate-100">{req.text}</p>
                <p className="text-xs text-slate-400 mt-1">{t('overview_acceptance')} {req.acceptance}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Action Toolbar */}
      <div className="action-toolbar">
        <div className="toolbar-left">
          {isWaiting && (
            <button
              onClick={onResumeRun}
              className="btn-success"
              disabled={isProcessing}
            >
              <Play size={15} />
              <span>{t('overview_resume_run')}</span>
            </button>
          )}

          {!isTerminal && (
            <>
              {showCancelPrompt ? (
                <div className="cancel-prompt-inline">
                  <input
                    type="text"
                    value={cancelReason}
                    onChange={(e) => setCancelReason(e.target.value)}
                    placeholder={t('overview_cancel_placeholder')}
                    className="form-input text-xs"
                  />
                  <button
                    onClick={() => {
                      onCancelRun(cancelReason);
                      setShowCancelPrompt(false);
                    }}
                    className="btn-danger-sm"
                    disabled={isProcessing}
                  >
                    {t('overview_confirm_stop')}
                  </button>
                  <button
                    onClick={() => setShowCancelPrompt(false)}
                    className="btn-text-sm"
                  >
                    {t('overview_cancel')}
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setShowCancelPrompt(true)}
                  className="btn-danger"
                  disabled={isProcessing}
                >
                  <StopCircle size={15} />
                  <span>{t('overview_cancel_run')}</span>
                </button>
              )}
            </>
          )}

          <button
            onClick={onValidate}
            className="btn-secondary"
            disabled={isProcessing}
            title="Execute P4 Quality Gate structural verification"
          >
            <ShieldCheck size={15} className="text-sky-400" />
            <span>{t('overview_validate_gates')}</span>
          </button>

          <button
            onClick={onFinalize}
            className="btn-secondary"
            disabled={isProcessing || run.status === 'FINAL'}
            title="Evaluate finalization conditions to promote to FINAL status"
          >
            <Award size={15} className="text-emerald-400" />
            <span>{t('overview_finalize_plan')}</span>
          </button>
        </div>

        <div className="toolbar-right">
          <button
            onClick={onExportMarkdown}
            className="btn-secondary"
            disabled={isProcessing}
          >
            <FileText size={15} />
            <span>{t('overview_export_md')}</span>
          </button>
          <button
            onClick={onExportJson}
            className="btn-secondary"
            disabled={isProcessing}
          >
            <Download size={15} />
            <span>{t('overview_export_json')}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
