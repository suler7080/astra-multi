import React from 'react';
import type { Decision } from '../types';
import { Compass, CheckCircle2 } from 'lucide-react';

interface DecisionsLogProps {
  decisions: Decision[];
}

export const DecisionsLog: React.FC<DecisionsLogProps> = ({ decisions }) => {
  return (
    <div className="section-card">
      <div className="flex-align-center gap-2 mb-4">
        <Compass size={18} className="text-sky-400" />
        <h3 className="card-title">Architectural Decisions Log ({decisions.length})</h3>
      </div>

      {decisions.length === 0 ? (
        <div className="empty-state">
          <p className="text-slate-400 text-sm">No decisions logged yet.</p>
        </div>
      ) : (
        <div className="decisions-list">
          {decisions.map((dec) => (
            <div key={dec.id} className="decision-card">
              <div className="decision-header">
                <span className="code-id">{dec.id}</span>
                <h4 className="decision-question">{dec.question}</h4>
              </div>

              <div className="chosen-solution-box">
                <div className="flex-align-center gap-2 text-emerald-400 mb-1">
                  <CheckCircle2 size={16} />
                  <span className="text-sm font-semibold">Chosen Alternative</span>
                </div>
                <p className="text-sm text-slate-100 font-medium">{dec.chosen}</p>
              </div>

              <div className="decision-rationale">
                <strong className="text-xs text-slate-400 uppercase tracking-wider">Rationale:</strong>
                <p className="text-sm text-slate-300 mt-1">{dec.rationale}</p>
              </div>

              {dec.alternatives && dec.alternatives.length > 0 && (
                <div className="decision-alternatives">
                  <strong className="text-xs text-slate-400 uppercase tracking-wider">Rejected Alternatives:</strong>
                  <ul className="alternatives-list">
                    {dec.alternatives.map((alt, i) => (
                      <li key={i} className="text-xs text-slate-400">{alt}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
