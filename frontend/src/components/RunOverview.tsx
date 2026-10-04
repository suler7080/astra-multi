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
}) => {
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

      {/* Pending Questions Banner */}
      {run.pending_questions && run.pending_questions.length > 0 && (
        <div className="pending-questions-card">
          <div className="pending-header">
            <div className="flex-align-center gap-2">
              <HelpCircle className="text-amber-400" size={20} />
              <h3 className="card-title text-amber-300">Clarification Needed from Operator</h3>
            </div>
            <span className="badge-amber">{run.pending_questions.length} Question(s)</span>
          </div>
          <p className="card-desc">
            The agents have paused deliberation to request specific human input or decision constraint:
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
                    placeholder="Provide answer / architectural preference..."
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
                    <span>Submit</span>
                  </button>
                </div>
              </div>
            ))}
          </div>

          {isWaiting && (
            <div className="resume-prompt-row">
              <span className="text-sm text-slate-300">
                All questions answered? Resume deliberation to continue planning:
              </span>
              <button
                onClick={onResumeRun}
                className="btn-success"
                disabled={isProcessing}
              >
                <Play size={15} />
                <span>Resume Run</span>
              </button>
            </div>
          )}
        </div>
      )}

      {/* Main Stats Grid */}
      <div className="stats-grid">
        <div className="stat-card">
          <span className="stat-label">Goal & Objective</span>
          <span className="stat-value text-base font-medium">{run.goal}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Status & Revision</span>
          <div className="flex-align-center gap-2 mt-1">
            <span className="font-semibold text-lg">{run.status}</span>
            <span className="badge-subtle">Rev {run.revision}</span>
          </div>
        </div>
        <div className="stat-card">
          <span className="stat-label">Artifacts Committed</span>
          <div className="flex-align-center gap-3 mt-1 text-sm text-slate-300">
            <span>Plans: <strong>{run.plans_count}</strong></span>
            <span>Issues: <strong>{run.issues_count}</strong> ({run.blocking_issues_count} blocking)</span>
            <span>Decisions: <strong>{run.decisions_count}</strong></span>
            <span>Evidence: <strong>{run.evidence_count}</strong></span>
          </div>
        </div>
      </div>

      {/* Requirements List */}
      <div className="section-card">
        <div className="flex-between mb-3">
          <div className="flex-align-center gap-2">
            <ListTodo size={18} className="text-sky-400" />
            <h3 className="card-title">Target Requirements ({run.requirements.length})</h3>
          </div>
        </div>
        <div className="requirements-table">
          {run.requirements.map((req) => (
            <div key={req.id} className="req-row">
              <span className="req-id-badge">{req.id}</span>
              <div className="flex-1">
                <p className="text-sm font-medium text-slate-100">{req.text}</p>
                <p className="text-xs text-slate-400 mt-1">Acceptance: {req.acceptance}</p>
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
              <span>Resume Run</span>
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
                    placeholder="Reason for cancellation..."
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
                    Confirm Stop
                  </button>
                  <button
                    onClick={() => setShowCancelPrompt(false)}
                    className="btn-text-sm"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setShowCancelPrompt(true)}
                  className="btn-danger"
                  disabled={isProcessing}
                >
                  <StopCircle size={15} />
                  <span>Cancel Run</span>
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
            <span>Validate Quality Gates</span>
          </button>

          <button
            onClick={onFinalize}
            className="btn-secondary"
            disabled={isProcessing || run.status === 'FINAL'}
            title="Evaluate finalization conditions to promote to FINAL status"
          >
            <Award size={15} className="text-emerald-400" />
            <span>Finalize Plan</span>
          </button>
        </div>

        <div className="toolbar-right">
          <button
            onClick={onExportMarkdown}
            className="btn-secondary"
            disabled={isProcessing}
          >
            <FileText size={15} />
            <span>Export Markdown</span>
          </button>
          <button
            onClick={onExportJson}
            className="btn-secondary"
            disabled={isProcessing}
          >
            <Download size={15} />
            <span>Export JSON</span>
          </button>
        </div>
      </div>
    </div>
  );
};
