import React from 'react';
import type { FinalizeResult, ValidationReport } from '../types';
import { X, ShieldCheck, AlertTriangle, CheckCircle, Award } from 'lucide-react';
import { useI18n } from '../i18n';

interface QualityGateModalProps {
  isOpen: boolean;
  onClose: () => void;
  report?: ValidationReport | null;
  finalizeResult?: FinalizeResult | null;
  mode: 'validation' | 'finalize';
}

export const QualityGateModal: React.FC<QualityGateModalProps> = ({
  isOpen,
  onClose,
  report,
  finalizeResult,
  mode,
}) => {
  const { t } = useI18n();
  if (!isOpen) return null;

  return (
    <div className="modal-backdrop">
      <div className="modal-container max-w-2xl" role="dialog" aria-modal="true">
        <div className="modal-header">
          <div className="modal-title-group">
            {mode === 'validation' ? (
              <>
                <ShieldCheck className="text-sky-400" size={20} />
                <h2 className="modal-title">{t('qg_validation_title')}</h2>
              </>
            ) : (
              <>
                <Award className="text-emerald-400" size={20} />
                <h2 className="modal-title">{t('qg_finalize_title')}</h2>
              </>
            )}
          </div>
          <button onClick={onClose} className="btn-icon" aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        <div className="modal-body p-6">
          {mode === 'validation' && report && (
            <div className="quality-report-content">
              <div className={`report-status-banner ${report.passed ? 'banner-pass' : 'banner-fail'}`}>
                {report.passed ? (
                  <>
                    <CheckCircle size={20} className="text-emerald-400" />
                    <div>
                      <h4 className="font-semibold text-emerald-300">All Quality Gates Passed</h4>
                      <p className="text-xs text-emerald-200">
                        Plan revision {report.plan_revision} fully satisfies structural integrity, requirement coverage, and DAG checks.
                      </p>
                    </div>
                  </>
                ) : (
                  <>
                    <AlertTriangle size={20} className="text-rose-400" />
                    <div>
                      <h4 className="font-semibold text-rose-300">Violations Detected ({report.violations.length})</h4>
                      <p className="text-xs text-rose-200">
                        The candidate plan requires remediation before it can be finalized.
                      </p>
                    </div>
                  </>
                )}
              </div>

              {report.violations.length > 0 && (
                <div className="violations-list mt-4">
                  <h4 className="text-sm font-semibold text-slate-200 mb-2">{t('qg_violations')}:</h4>
                  {report.violations.map((v, i) => (
                    <div key={i} className="violation-card">
                      <div className="flex-align-center gap-2 mb-1">
                        <span className="badge-rose text-xs font-mono">{v.rule_id}</span>
                        <span className="badge-subtle text-xs">{v.severity}</span>
                        <span className="code-id text-xs">{v.entity}</span>
                      </div>
                      <p className="text-xs font-medium text-slate-100">{v.message}</p>
                      <p className="text-xs text-slate-400 mt-1 italic">Remediation: {v.remediation}</p>
                    </div>
                  ))}
                </div>
              )}

              {report.uncovered_requirements.length > 0 && (
                <div className="uncovered-box mt-3">
                  <span className="text-xs font-semibold text-amber-300">{t('qg_uncovered_reqs')}:</span>
                  <div className="flex-wrap gap-1 mt-1">
                    {report.uncovered_requirements.map((r) => (
                      <span key={r} className="badge-amber text-xs">{r}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {mode === 'finalize' && finalizeResult && (
            <div className="finalize-report-content">
              <div className={`report-status-banner ${finalizeResult.can_finalize ? 'banner-pass' : 'banner-fail'}`}>
                {finalizeResult.can_finalize ? (
                  <>
                    <CheckCircle size={20} className="text-emerald-400" />
                    <div>
                      <h4 className="font-semibold text-emerald-300">Run Successfully Finalized</h4>
                      <p className="text-xs text-emerald-200">
                        Promoted to FINAL status. Plan is ready for export and execution handover.
                      </p>
                    </div>
                  </>
                ) : (
                  <>
                    <AlertTriangle size={20} className="text-amber-400" />
                    <div>
                      <h4 className="font-semibold text-amber-300">Finalization Blocked</h4>
                      <p className="text-xs text-amber-200">
                        Run status: {finalizeResult.status}. Remaining blockers must be resolved first.
                      </p>
                    </div>
                  </>
                )}
              </div>

              {finalizeResult.blockers.length > 0 && (
                <div className="blockers-list mt-4">
                  <h4 className="text-sm font-semibold text-slate-200 mb-2">{t('qg_unresolved_issues')}:</h4>
                  <ul className="list-disc pl-5 space-y-1">
                    {finalizeResult.blockers.map((b, i) => (
                      <li key={i} className="text-xs text-slate-300">{b}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="modal-actions">
          <button onClick={onClose} className="btn-secondary">
            {t('qg_close')}
          </button>
        </div>
      </div>
    </div>
  );
};
