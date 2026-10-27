import React, { useState } from 'react';
import type { PlanRevision, Issue, Decision, Evidence } from '../types';
import { GitBranch, Download, FileText, ChevronDown, ChevronUp, CheckSquare } from 'lucide-react';
import { useI18n } from '../i18nContext';

interface PlanViewerProps {
  currentPlan?: PlanRevision | null;
  totalPlansCount: number;
  onSelectRevision: (rev: number) => void;
  onExportMarkdown: (rev: number) => void;
  onExportJson: (rev: number) => void;
  issues?: Issue[];
  decisions?: Decision[];
  evidence?: Evidence[];
}

export const PlanViewer: React.FC<PlanViewerProps> = ({
  currentPlan,
  totalPlansCount,
  onSelectRevision,
  onExportMarkdown,
  onExportJson,
  issues = [],
  decisions = [],
  evidence = [],
}) => {
  const { t } = useI18n();
  const [selectedRev, setSelectedRev] = useState<number>(currentPlan?.revision || 1);
  const [expandedStepId, setExpandedStepId] = useState<string | null>(null);

  if (!currentPlan) {
    return (
      <div className="bg-[var(--bg)] border border-[var(--border)] rounded-[28px] p-12 text-center shadow-sm">
        <GitBranch size={36} className="text-[var(--text-2)] mx-auto mb-3 opacity-60" />
        <p className="text-[15px] text-[var(--text-2)] font-medium">{t('plan_no_plan')}</p>
      </div>
    );
  }

  const revisions = Array.from({ length: totalPlansCount }, (_, i) => i + 1);

  // Helper to find related issues for a step
  const getStepIssues = (stepId: string, reqIds: string[]) => {
    return issues.filter((iss) => {
      if (iss.claim.includes(stepId) || iss.impact.includes(stepId)) return true;
      if (iss.requirement_ids.some((r) => reqIds.includes(r))) return true;
      return false;
    });
  };

  // Helper to find related decisions for a step
  const getStepDecisions = (stepId: string) => {
    return decisions.filter((d) => d.related_issues.some((r) => r.includes(stepId)) || d.chosen.includes(stepId));
  };

  // Helper to find related evidence
  const getStepEvidence = (evidenceIds: string[]) => {
    return evidence.filter((e) => evidenceIds.includes(e.id));
  };

  return (
    <div className="space-y-6">
      {/* Plan Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2">
        <div>
          <h2 className="text-[24px] font-medium text-[var(--text)] tracking-tight">
            {t('plan_steps_summary').replace('{rev}', String(currentPlan.revision))}
          </h2>
          <p className="text-[14px] text-[var(--text-2)] mt-0.5">
            {t('plan_reviewer_critique_hint')}
          </p>
        </div>

        {/* Revision Selector and Export Actions */}
        <div className="flex items-center flex-wrap gap-2.5">
          {revisions.length > 1 && (
            <div className="flex items-center gap-1 bg-[var(--surface-tonal)] p-1 rounded-full">
              {revisions.map((rev) => (
                <button
                  key={rev}
                  type="button"
                  onClick={() => {
                    setSelectedRev(rev);
                    onSelectRevision(rev);
                  }}
                  className={`h-7 px-3 rounded-full text-[12px] font-mono font-medium transition-colors cursor-pointer ${
                    rev === selectedRev
                      ? 'bg-[var(--bg)] text-[var(--accent)] shadow-sm'
                      : 'text-[var(--text-2)] hover:text-[var(--text)]'
                  }`}
                >
                  r{rev}
                </button>
              ))}
            </div>
          )}

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onExportMarkdown(currentPlan.revision)}
              className="h-8 px-3.5 rounded-full border border-[var(--border-strong)] bg-[var(--bg)] hover:bg-[var(--surface-tonal)] text-[var(--text)] text-[12px] font-medium flex items-center gap-1.5 transition-colors cursor-pointer"
            >
              <FileText size={13} className="text-[var(--text-2)]" />
              <span>Markdown</span>
            </button>
            <button
              type="button"
              onClick={() => onExportJson(currentPlan.revision)}
              className="h-8 px-3.5 rounded-full border border-[var(--border-strong)] bg-[var(--bg)] hover:bg-[var(--surface-tonal)] text-[var(--text)] text-[12px] font-medium flex items-center gap-1.5 transition-colors cursor-pointer"
            >
              <Download size={13} className="text-[var(--text-2)]" />
              <span>JSON</span>
            </button>
          </div>
        </div>
      </div>

      {/* Steps List */}
      <div className="space-y-5">
        {currentPlan.steps.map((step) => {
          const stepIssues = getStepIssues(step.id, step.requirement_ids);
          const openIssues = stepIssues.filter((i) => i.status === 'OPEN');
          const resolvedIssues = stepIssues.filter((i) => i.status === 'RESOLVED');
          const blockingIssue = openIssues.find((i) => i.severity === 'blocking') || openIssues[0];

          const stepDecisions = getStepDecisions(step.id);
          const stepEvidences = getStepEvidence(step.evidence_ids || []);
          const isExpanded = expandedStepId === step.id;

          // Critique highlighting: if open issue exists with a specific quote
          const renderObjectiveWithCritique = () => {
            if (!blockingIssue) return step.objective;

            // Simple intelligent highlighting heuristic
            const phraseMatch = blockingIssue.claim || '';
            const matchIndex = step.objective.toLowerCase().indexOf(phraseMatch.toLowerCase());

            if (matchIndex >= 0 && phraseMatch.length > 3) {
              const before = step.objective.substring(0, matchIndex);
              const matched = step.objective.substring(matchIndex, matchIndex + phraseMatch.length);
              const after = step.objective.substring(matchIndex + phraseMatch.length);

              return (
                <>
                  {before}
                  <mark className="bg-[var(--error-tonal)] text-[var(--error-on-tonal)] px-1.5 py-0.5 rounded-[6px] font-medium">
                    {matched}
                  </mark>
                  {after}
                </>
              );
            }

            return step.objective;
          };

          return (
            <div
              key={step.id}
              className="bg-[var(--bg)] border border-[var(--border)] rounded-[28px] p-6 sm:p-7 lift shadow-sm transition-all"
            >
              {/* Step Header Row */}
              <div className="flex items-center justify-between gap-3 mb-3">
                <span className="font-mono text-[13px] px-3 py-1 rounded-full border border-[var(--border-strong)] text-[var(--text)] font-medium">
                  {step.id}
                </span>

                {openIssues.length > 0 ? (
                  <span className="chip chip-error text-[12px] py-0.5 px-3">
                    {t('plan_n_issues_open').replace('{count}', String(openIssues.length))}
                  </span>
                ) : resolvedIssues.length > 0 ? (
                  <span className="chip chip-success text-[12px] py-0.5 px-3">
                    {t('plan_resolved')}
                  </span>
                ) : (
                  <span className="chip chip-neutral text-[12px] py-0.5 px-3">
                    {t('plan_not_reviewed')}
                  </span>
                )}
              </div>

              {/* Step Objective */}
              <h3 className="text-[18px] sm:text-[19px] font-medium text-[var(--text)] leading-relaxed tracking-tight my-3">
                {renderObjectiveWithCritique()}
              </h3>

              {/* Reviewer Comment Box (Light Red / error-tonal) */}
              {blockingIssue && (
                <div className="bg-[var(--error-tonal)] text-[var(--error-on-tonal)] border border-[var(--error)]/20 rounded-[20px] p-4 sm:p-5 my-4">
                  <div className="font-mono text-[11px] font-medium uppercase tracking-wider mb-1.5 opacity-90">
                    REVIEWER · {blockingIssue.id} · {blockingIssue.severity.toUpperCase()}
                  </div>
                  <p className="text-[14px] leading-relaxed">
                    {blockingIssue.impact || blockingIssue.claim}
                  </p>
                </div>
              )}

              {/* Badges / Chips Row: Decisions, Evidence, Issues */}
              <div className="flex flex-wrap items-center gap-2 mt-4 pt-3 border-t border-[var(--border)]">
                {/* Related Issues chips */}
                {stepIssues.map((iss) => (
                  <span
                    key={iss.id}
                    className={`font-mono text-[11px] py-0.5 px-2.5 rounded-full ${
                      iss.status === 'OPEN'
                        ? 'chip-error'
                        : iss.status === 'RESOLVED'
                        ? 'chip-success'
                        : 'chip-neutral'
                    }`}
                  >
                    {iss.id}
                  </span>
                ))}

                {/* Related Decisions chips */}
                {stepDecisions.map((dec) => (
                  <span
                    key={dec.id}
                    className="font-mono text-[11px] py-0.5 px-2.5 rounded-full chip-neutral"
                  >
                    {dec.id} · Synthesizer
                  </span>
                ))}

                {/* Related Evidence chips */}
                {stepEvidences.map((ev) => (
                  <span
                    key={ev.id}
                    className="font-mono text-[11px] py-0.5 px-2.5 rounded-full chip-success"
                  >
                    {ev.id} · {ev.locator.split('/').pop() || 'test'} · {ev.status}
                  </span>
                ))}

                {/* Dependencies string */}
                {step.dependencies && step.dependencies.length > 0 && (
                  <span className="font-mono text-[12px] text-[var(--text-2)] ml-auto">
                    {t('plan_depends_on')} {step.dependencies.join(', ')}
                  </span>
                )}
              </div>

              {/* Expandable Technical Details Button */}
              {(step.deliverables.length > 0 || step.validation || step.completion_criteria.length > 0) && (
                <div className="mt-3 pt-2">
                  <button
                    type="button"
                    onClick={() => setExpandedStepId(isExpanded ? null : step.id)}
                    className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[var(--text-2)] hover:text-[var(--text)] transition-colors cursor-pointer"
                  >
                    <span>{isExpanded ? t('error_hide_details') : t('error_view_details')}</span>
                    {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                  </button>

                  {isExpanded && (
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 p-4 mt-3 rounded-[20px] bg-[var(--surface-tonal)] text-[var(--text-3)] text-[13px]">
                      {step.deliverables.length > 0 && (
                        <div>
                          <strong className="block text-[11px] uppercase tracking-wider font-mono text-[var(--text-2)] mb-1.5">
                            {t('plan_deliverables')}
                          </strong>
                          <ul className="space-y-1">
                            {step.deliverables.map((d, idx) => (
                              <li key={idx} className="flex items-start gap-1.5">
                                <span className="text-[var(--accent)]">•</span>
                                <span>{d}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {step.validation && (
                        <div>
                          <strong className="block text-[11px] uppercase tracking-wider font-mono text-[var(--text-2)] mb-1.5">
                            {t('plan_validation_command')}
                          </strong>
                          <div className="p-2.5 rounded-[12px] bg-[var(--bg)] border border-[var(--border)] font-mono text-[12px] text-[var(--text)] break-all select-all">
                            <code>{step.validation}</code>
                          </div>
                        </div>
                      )}

                      {step.completion_criteria.length > 0 && (
                        <div>
                          <strong className="block text-[11px] uppercase tracking-wider font-mono text-[var(--text-2)] mb-1.5">
                            {t('plan_completion_criteria')}
                          </strong>
                          <ul className="space-y-1">
                            {step.completion_criteria.map((c, idx) => (
                              <li key={idx} className="flex items-start gap-1.5">
                                <CheckSquare size={13} className="text-[var(--success)] shrink-0 mt-0.5" />
                                <span>{c}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
