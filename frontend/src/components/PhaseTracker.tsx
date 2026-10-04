import React from 'react';
import { Check, CircleDot, AlertTriangle, XCircle, CheckCircle2 } from 'lucide-react';

const PHASES = [
  'INTAKE',
  'SNAPSHOT',
  'INVESTIGATE',
  'INDEPENDENT_ANALYSIS',
  'PROPOSE',
  'REVIEW',
  'VERIFY',
  'REVISE',
  'QUALITY_GATE',
  'EXPORT',
] as const;

interface PhaseTrackerProps {
  currentPhase: string;
  status: string;
  stopReason?: string | null;
}

export const PhaseTracker: React.FC<PhaseTrackerProps> = ({
  currentPhase,
  status,
  stopReason,
}) => {
  const currentIndex = PHASES.indexOf(currentPhase as (typeof PHASES)[number]);

  const getStatusBadge = () => {
    switch (status) {
      case 'FINAL':
        return <span className="status-badge badge-final"><CheckCircle2 size={14} /> FINAL</span>;
      case 'RUNNING':
        return <span className="status-badge badge-running"><CircleDot size={14} className="animate-pulse" /> RUNNING</span>;
      case 'WAITING_FOR_INPUT':
        return <span className="status-badge badge-waiting"><AlertTriangle size={14} /> WAITING FOR INPUT</span>;
      case 'PARTIAL':
        return <span className="status-badge badge-partial"><AlertTriangle size={14} /> PARTIAL</span>;
      case 'CANCELLED':
        return <span className="status-badge badge-cancelled"><XCircle size={14} /> CANCELLED</span>;
      case 'FAILED':
        return <span className="status-badge badge-failed"><XCircle size={14} /> FAILED</span>;
      default:
        return <span className="status-badge badge-default">{status}</span>;
    }
  };

  return (
    <div className="phase-tracker-card">
      <div className="phase-header">
        <div className="phase-title-group">
          <span className="section-title">Workflow Lifecycle</span>
          {getStatusBadge()}
        </div>
        {stopReason && (
          <div className="stop-reason-box">
            <strong>Stop reason:</strong> {stopReason}
          </div>
        )}
      </div>

      <div className="phase-stepper">
        {PHASES.map((phase, idx) => {
          const isDone = currentIndex > idx || status === 'FINAL';
          const isCurrent = currentIndex === idx && status !== 'FINAL';
          const isUpcoming = currentIndex < idx && status !== 'FINAL';

          let stepClass = 'phase-step';
          if (isDone) stepClass += ' step-done';
          if (isCurrent) stepClass += ' step-current';
          if (isUpcoming) stepClass += ' step-upcoming';

          return (
            <div key={phase} className={stepClass} title={phase}>
              <div className="step-indicator">
                {isDone ? (
                  <Check size={14} />
                ) : isCurrent ? (
                  <div className="current-dot" />
                ) : (
                  <span className="step-number">{idx + 1}</span>
                )}
              </div>
              <span className="step-label">
                {phase.replace('_', ' ')}
              </span>
              {idx < PHASES.length - 1 && <div className="step-connector" />}
            </div>
          );
        })}
      </div>
    </div>
  );
};
