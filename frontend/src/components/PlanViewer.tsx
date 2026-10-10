import React, { useState } from 'react';
import type { PlanRevision } from '../types';
import { GitBranch, CheckSquare, Download, FileText, ArrowRight } from 'lucide-react';
import { useI18n } from '../i18nContext';

interface PlanViewerProps {
  currentPlan?: PlanRevision | null;
  totalPlansCount: number;
  onSelectRevision: (rev: number) => void;
  onExportMarkdown: (rev: number) => void;
  onExportJson: (rev: number) => void;
}

export const PlanViewer: React.FC<PlanViewerProps> = ({
  currentPlan,
  totalPlansCount,
  onSelectRevision,
  onExportMarkdown,
  onExportJson,
}) => {
  const { t } = useI18n();
  const [selectedRev, setSelectedRev] = useState<number>(currentPlan?.revision || 1);

  if (!currentPlan) {
    return (
      <div className="section-card empty-state">
        <GitBranch size={32} className="text-slate-600 mb-2" />
        <p className="text-slate-400 text-sm">{t('plan_no_plan')}</p>
      </div>
    );
  }

  const revisions = Array.from({ length: totalPlansCount }, (_, i) => i + 1);

  return (
    <div className="section-card">
      <div className="flex-between mb-4">
        <div className="flex-align-center gap-2">
          <GitBranch size={18} className="text-sky-400" />
          <h3 className="card-title">{t('plan_title')}</h3>
          <span className="badge-subtle ml-2">Revision {currentPlan.revision}</span>
        </div>

        <div className="flex-align-center gap-2">
          {revisions.length > 1 && (
            <div className="rev-selector-group">
              <span className="text-xs text-slate-400">View Revision:</span>
              <div className="rev-buttons-row">
                {revisions.map((rev) => (
                  <button
                    key={rev}
                    onClick={() => {
                      setSelectedRev(rev);
                      onSelectRevision(rev);
                    }}
                    className={`btn-rev ${rev === selectedRev ? 'btn-rev-active' : ''}`}
                  >
                    r{rev}
                  </button>
                ))}
              </div>
            </div>
          )}

          <button
            onClick={() => onExportMarkdown(currentPlan.revision)}
            className="btn-secondary-sm"
          >
            <FileText size={14} />
            <span>Markdown</span>
          </button>
          <button
            onClick={() => onExportJson(currentPlan.revision)}
            className="btn-secondary-sm"
          >
            <Download size={14} />
            <span>JSON</span>
          </button>
        </div>
      </div>

      {/* Plan Steps */}
      <div className="steps-container">
        {currentPlan.steps.map((step, idx) => (
          <div key={step.id} className="step-card">
            <div className="step-card-header">
              <div className="flex-align-center gap-2">
                <span className="step-idx-badge">{idx + 1}</span>
                <span className="code-id">{step.id}</span>
                <h4 className="step-objective">{step.objective}</h4>
              </div>
            </div>

            <div className="step-details-grid">
              <div className="step-col">
                <strong className="detail-label">Deliverables:</strong>
                <ul className="step-list">
                  {step.deliverables.map((d, i) => (
                    <li key={i} className="text-xs text-slate-200">{d}</li>
                  ))}
                </ul>
              </div>

              <div className="step-col">
                <strong className="detail-label">Validation Command:</strong>
                <code className="validation-cmd-box">{step.validation}</code>
              </div>

              <div className="step-col">
                <strong className="detail-label">Completion Criteria:</strong>
                <ul className="step-list">
                  {step.completion_criteria.map((c, i) => (
                    <li key={i} className="text-xs text-slate-300">
                      <CheckSquare size={12} className="inline mr-1 text-emerald-400" />
                      {c}
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="step-footer">
              <div className="flex-align-center gap-1">
                <span className="text-xs text-slate-400">Requirements:</span>
                {step.requirement_ids.map((r) => (
                  <span key={r} className="badge-subtle text-xs">{r}</span>
                ))}
              </div>

              {step.dependencies && step.dependencies.length > 0 && (
                <div className="flex-align-center gap-1">
                  <span className="text-xs text-slate-400">Depends on:</span>
                  {step.dependencies.map((dep) => (
                    <span key={dep} className="badge-amber text-xs">
                      <ArrowRight size={10} className="inline mr-1" />
                      {dep}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
