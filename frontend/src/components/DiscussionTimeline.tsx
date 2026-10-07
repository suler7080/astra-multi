import React, { useEffect, useRef, useState } from 'react';
import type { StreamEvent } from '../types';
import { MessageSquare, Radio, User, Bot, Shield, CheckCircle, Code } from 'lucide-react';
import { useI18n } from '../i18n';

interface DiscussionTimelineProps {
  events: StreamEvent[];
  isConnected: boolean;
}

export const DiscussionTimeline: React.FC<DiscussionTimelineProps> = ({
  events,
  isConnected,
}) => {
  const { t } = useI18n();
  const [filterType, setFilterType] = useState<string>('all');
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events, autoScroll]);

  const filteredEvents = events.filter((e) => {
    if (filterType === 'all') return true;
    if (filterType === 'transition_phase' || filterType === 'transition_run') {
      return (
        e.event === 'transition_phase' ||
        e.event === 'transition_run' ||
        e.data?.type === 'transition_run'
      );
    }
    if (filterType === 'record_issue') {
      return (
        e.event === 'record_issue' ||
        (e.event === 'add_record' &&
          String(e.data?.payload?.logical_operation_id || '').startsWith('issue'))
      );
    }
    if (filterType === 'record_decision') {
      return (
        e.event === 'record_decision' ||
        (e.event === 'add_record' &&
          String(e.data?.payload?.logical_operation_id || '').startsWith('decision'))
      );
    }
    if (filterType === 'ask_question') {
      return (
        e.event === 'ask_question' ||
        (e.event === 'add_record' &&
          String(e.data?.payload?.logical_operation_id || '').startsWith('question'))
      );
    }
    return e.event === filterType || e.data?.type === filterType;
  });

  const getActorBadge = (actor?: string) => {
    if (!actor) return null;
    const lower = actor.toLowerCase();
    if (lower.includes('planner')) {
      return <span className="actor-badge badge-planner"><Bot size={12} /> Planner</span>;
    }
    if (lower.includes('reviewer')) {
      return <span className="actor-badge badge-reviewer"><Shield size={12} /> Reviewer</span>;
    }
    if (lower.includes('synthesizer')) {
      return <span className="actor-badge badge-synthesizer"><Bot size={12} /> Synthesizer</span>;
    }
    if (lower.includes('verifier') || lower.includes('quality')) {
      return <span className="actor-badge badge-verifier"><Shield size={12} /> Verifier</span>;
    }
    if (lower.includes('user') || lower.includes('human')) {
      return <span className="actor-badge badge-user"><User size={12} /> Operator</span>;
    }
    return <span className="actor-badge badge-system"><Code size={12} /> {actor}</span>;
  };

  return (
    <div className="section-card timeline-card">
      <div className="timeline-header">
        <div className="flex-align-center gap-2">
          <MessageSquare size={18} className="text-sky-400" />
          <h3 className="card-title">{t('timeline_title')}</h3>
          <div className="flex-align-center gap-1 ml-2">
            <Radio size={14} className={isConnected ? 'text-emerald-400 animate-pulse' : 'text-slate-500'} />
            <span className="text-xs text-slate-400">
              {isConnected ? t('timeline_connected') : t('timeline_disconnected')}
            </span>
          </div>
        </div>

        <div className="timeline-controls">
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="form-select-sm"
          >
            <option value="all">All Events ({events.length})</option>
            <option value="commit_plan">Plan Commits</option>
            <option value="record_issue">Issues</option>
            <option value="record_decision">Decisions</option>
            <option value="ask_question">Questions</option>
            <option value="transition_phase">Phase Transitions</option>
          </select>

          <label className="checkbox-label text-xs">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
            />
            Auto-scroll
          </label>
        </div>
      </div>

      <div className="timeline-body" ref={scrollRef}>
        {filteredEvents.length === 0 ? (
          <div className="empty-state">
            <MessageSquare size={32} className="text-slate-600 mb-2" />
            <p className="text-slate-400 text-sm">{t('timeline_empty')}</p>
          </div>
        ) : (
          <div className="timeline-items-list">
            {filteredEvents.map((item, index) => {
              const d = item.data;
              const formattedTime = d.timestamp
                ? new Date(d.timestamp).toLocaleTimeString()
                : '';

              return (
                <div key={item.id || index} className="timeline-event-row">
                  <div className="event-seq-column">
                    <span className="seq-badge">#{item.id || index + 1}</span>
                    <span className="event-time">{formattedTime}</span>
                  </div>

                  <div className="event-content-column">
                    <div className="event-meta-row">
                      <span className="event-type-badge">{item.event}</span>
                      {getActorBadge(d.actor)}
                    </div>

                    {d.payload && (
                      <div className="event-payload-box">
                        <pre className="payload-json">
                          {JSON.stringify(d.payload, null, 2)}
                        </pre>
                      </div>
                    )}

                    {(() => {
                      if (item.event !== 'transition_run' && item.event !== 'transition_phase') return null;
                      const payload = d.payload as Record<string, any> | undefined;
                      const res = payload?.result || payload;
                      const phaseName = res?.phase;
                      const statusName = res?.status || 'RUNNING';
                      if (!phaseName) return null;
                      return (
                        <div className="run-completed-banner" style={{ borderColor: 'rgba(56, 189, 248, 0.4)', background: 'rgba(12, 74, 110, 0.2)' }}>
                          <span className="text-sky-400 font-semibold">➔ {t('phase_workflow_lifecycle')}:</span>
                          <span>Phase advanced to <strong>{phaseName}</strong> ({statusName})</span>
                        </div>
                      );
                    })()}

                    {item.event === 'run_completed' && (
                      <div className="run-completed-banner">
                        <CheckCircle size={16} className="text-emerald-400" />
                        <span>Run Completed with Status: <strong>{d.status}</strong> ({d.phase})</span>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
