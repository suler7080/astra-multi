import React, { useEffect, useRef, useState } from 'react';
import type { StreamEvent } from '../types';
import {
  MessageSquare,
  Radio,
  User,
  Bot,
  Shield,
  CheckCircle,
  Code,
  AlertOctagon,
  HelpCircle,
  Compass,
  GitBranch,
  ChevronDown,
  ChevronRight,
  Sparkles,
} from 'lucide-react';
import { useI18n } from '../i18nContext';

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
  const [expandedPayloads, setExpandedPayloads] = useState<Record<string, boolean>>({});
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events, autoScroll]);

  const togglePayload = (id: string) => {
    setExpandedPayloads((prev) => ({ ...prev, [id]: !prev[id] }));
  };

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
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/20">
          <Bot size={12} /> Planner
        </span>
      );
    }
    if (lower.includes('reviewer')) {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-purple-500/10 text-purple-300 border border-purple-500/20">
          <Shield size={12} /> Reviewer
        </span>
      );
    }
    if (lower.includes('synthesizer')) {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
          <Sparkles size={12} /> Synthesizer
        </span>
      );
    }
    if (lower.includes('verifier') || lower.includes('quality')) {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
          <Shield size={12} /> Verifier
        </span>
      );
    }
    if (lower.includes('user') || lower.includes('human')) {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/20">
          <User size={12} /> {t('actor_operator')}
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-800 text-slate-300 border border-white/5">
        <Code size={12} /> {actor}
      </span>
    );
  };

  const renderStructuredContent = (item: StreamEvent) => {
    const p = (item.data?.payload || {}) as Record<string, any>;
    const eventName = item.event;

    // 1. Issue event
    if (eventName === 'record_issue' || p.concern) {
      return (
        <div className="mt-2 p-3.5 rounded-xl bg-amber-950/20 border border-amber-500/20 space-y-2">
          <div className="flex items-center gap-2">
            <span className="p-1 rounded bg-amber-500/10 text-amber-400">
              <AlertOctagon size={14} />
            </span>
            <span className="text-xs font-semibold uppercase tracking-wider text-amber-400 font-mono">
              {p.severity || 'Issue'}
            </span>
            {p.id && <span className="code-id text-[11px]">{p.id}</span>}
          </div>
          <p className="text-sm font-medium text-slate-100">{p.concern}</p>
          {p.impact && (
            <p className="text-xs text-slate-300 bg-black/20 p-2 rounded-lg border border-white/5">
              <strong className="text-slate-400 font-semibold">{t('issue_col_impact')}:</strong> {p.impact}
            </p>
          )}
          {p.resolution && (
            <p className="text-xs text-emerald-300">
              <strong className="text-emerald-400">{t('issue_col_resolution')}:</strong> {p.resolution}
            </p>
          )}
        </div>
      );
    }

    // 2. Decision event
    if (eventName === 'record_decision' || p.chosen) {
      return (
        <div className="mt-2 p-3.5 rounded-xl bg-sky-950/20 border border-sky-500/20 space-y-2">
          <div className="flex items-center gap-2">
            <span className="p-1 rounded bg-sky-500/10 text-sky-400">
              <Compass size={14} />
            </span>
            <span className="text-xs font-semibold uppercase tracking-wider text-sky-400 font-mono">
              Decision Recorded
            </span>
            {p.id && <span className="code-id text-[11px]">{p.id}</span>}
          </div>
          {p.question && <p className="text-xs text-slate-400 font-medium">{p.question}</p>}
          <div className="p-2.5 rounded-lg bg-emerald-950/30 border border-emerald-500/20">
            <span className="text-[11px] uppercase tracking-wider font-semibold text-emerald-400 block mb-0.5">
              {t('decisions_chosen_alternative')}
            </span>
            <span className="text-sm font-semibold text-slate-100">{p.chosen}</span>
          </div>
          {p.rationale && (
            <p className="text-xs text-slate-300 leading-relaxed">
              <strong className="text-slate-400">{t('decisions_rationale')}:</strong> {p.rationale}
            </p>
          )}
        </div>
      );
    }

    // 3. Question event
    if (eventName === 'ask_question' || p.question) {
      return (
        <div className="mt-2 p-3.5 rounded-xl bg-amber-950/25 border border-amber-500/30 space-y-2">
          <div className="flex items-center gap-2">
            <span className="p-1 rounded bg-amber-500/10 text-amber-400">
              <HelpCircle size={14} />
            </span>
            <span className="text-xs font-semibold uppercase tracking-wider text-amber-400 font-mono">
              Clarification Question
            </span>
          </div>
          <p className="text-sm font-semibold text-slate-100">{p.question}</p>
          {Array.isArray(p.options) && p.options.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-1">
              {p.options.map((opt: string, i: number) => (
                <span key={i} className="text-xs px-2.5 py-1 rounded-lg bg-slate-900/80 border border-white/10 text-slate-300">
                  {opt}
                </span>
              ))}
            </div>
          )}
        </div>
      );
    }

    // 4. Plan Revision event
    if (eventName === 'commit_plan' || p.plan_revision) {
      return (
        <div className="mt-2 p-3.5 rounded-xl bg-indigo-950/20 border border-indigo-500/20 space-y-2">
          <div className="flex items-center gap-2">
            <span className="p-1 rounded bg-indigo-500/10 text-indigo-400">
              <GitBranch size={14} />
            </span>
            <span className="text-xs font-semibold uppercase tracking-wider text-indigo-300 font-mono">
              Plan Committed (r{p.plan_revision || p.revision || 1})
            </span>
          </div>
          {p.summary && <p className="text-xs text-slate-300">{p.summary}</p>}
          {Array.isArray(p.steps) && (
            <p className="text-xs text-indigo-300 font-mono">
              {p.steps.length} architectural milestones created
            </p>
          )}
        </div>
      );
    }

    // 5. General message / comment / thought
    if (p.message || p.thought || p.content) {
      const text = p.message || p.thought || p.content;
      return (
        <div className="mt-2 p-3 rounded-xl bg-slate-900/60 border border-white/5 text-sm text-slate-200 leading-relaxed font-sans">
          {text}
        </div>
      );
    }

    return null;
  };

  return (
    <div className="bg-[var(--bg)] border border-[var(--border)] rounded-[28px] shadow-sm overflow-hidden">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-6 py-5 border-b border-[var(--border)] bg-[var(--bg)]">
        <div className="flex items-center gap-2.5">
          <MessageSquare size={18} className="text-[var(--accent)]" />
          <h3 className="text-[20px] font-medium text-[var(--text)] tracking-tight">{t('timeline_title')}</h3>
          <div className="flex items-center gap-1.5 ml-2 px-3 py-1 rounded-full bg-[var(--surface-tonal)]">
            <Radio size={12} className={isConnected ? 'text-[var(--success)] animate-pulse' : 'text-[var(--text-2)]'} />
            <span className="text-[12px] font-medium text-[var(--text-2)]">
              {isConnected ? t('timeline_connected') : t('timeline_disconnected')}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="h-9 text-[13px] rounded-full py-1 px-4 bg-[var(--surface-tonal)] border border-[var(--border-strong)] text-[var(--text)] outline-none cursor-pointer"
          >
            <option value="all">{t('timeline_filter_all').replace('{count}', String(events.length))}</option>
            <option value="commit_plan">{t('timeline_filter_plan')}</option>
            <option value="record_issue">{t('timeline_filter_issues')}</option>
            <option value="record_decision">{t('timeline_filter_decisions')}</option>
            <option value="ask_question">{t('timeline_filter_questions')}</option>
            <option value="transition_phase">{t('timeline_filter_phases')}</option>
          </select>

          <label className="inline-flex items-center gap-1.5 text-[13px] text-[var(--text-2)] cursor-pointer select-none">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="rounded border-[var(--border-strong)] text-[var(--accent)]"
            />
            {t('timeline_auto_scroll')}
          </label>
        </div>
      </div>

      {/* Body */}
      <div className="p-6 max-h-[640px] overflow-y-auto space-y-4 scrollbar-thin" ref={scrollRef}>
        {filteredEvents.length === 0 ? (
          <div className="text-center py-16 text-[var(--text-2)]">
            <MessageSquare size={36} className="mx-auto mb-3 opacity-40 text-[var(--text-2)]" />
            <p className="text-[14px] font-medium">{t('timeline_empty')}</p>
          </div>
        ) : (
          <div className="space-y-4">
            {filteredEvents.map((item, index) => {
              const d = item.data || {};
              const eventId = String(item.id || index);
              const formattedTime = d.timestamp
                ? new Date(d.timestamp).toLocaleTimeString()
                : '';
              const isPayloadOpen = !!expandedPayloads[eventId];

              return (
                <div
                  key={eventId}
                  className="p-5 rounded-[20px] bg-[var(--bg-alt)] border border-[var(--border)] hover:border-[var(--accent)]/30 transition-colors shadow-sm relative group"
                >
                  {/* Top Meta Row */}
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[11px] font-medium text-[var(--text-2)]">#{item.id || index + 1}</span>
                      <span className="font-mono text-[11px] font-medium text-[var(--accent-on-tonal)] bg-[var(--accent-tonal)] px-2.5 py-0.5 rounded-full">
                        {item.event}
                      </span>
                      {getActorBadge(d.actor)}
                    </div>
                    {formattedTime && (
                      <span className="text-[11px] font-mono text-[var(--text-2)] tabular-nums">
                        {formattedTime}
                      </span>
                    )}
                  </div>

                  {/* High Level Event Banner for Phase Transitions */}
                  {(() => {
                    if (item.event !== 'transition_run' && item.event !== 'transition_phase') return null;
                    const payload = d.payload as Record<string, any> | undefined;
                    const res = payload?.result || payload;
                    const phaseName = res?.phase;
                    const statusName = res?.status || 'RUNNING';
                    if (!phaseName) return null;
                    return (
                      <div className="my-2 p-3 rounded-[16px] bg-[var(--accent-tonal)] text-[var(--accent-on-tonal)] border border-[var(--accent)]/20 text-[13px] flex items-center gap-2 font-mono">
                        <span className="font-bold">➔ {t('phase_workflow_lifecycle')}:</span>
                        <span>{t('timeline_phase_advanced').replace('{phase}', phaseName).replace('{status}', statusName)}</span>
                      </div>
                    );
                  })()}

                  {item.event === 'run_completed' && (
                    <div className="my-2 p-3 rounded-[16px] bg-[var(--success-tonal)] text-[var(--success-on-tonal)] border border-[var(--success)]/20 text-[13px] flex items-center gap-2 font-mono">
                      <CheckCircle size={15} className="text-[var(--success)]" />
                      <span>{t('timeline_run_completed_status').replace('{status}', d.status || '').replace('{phase}', d.phase || '')}</span>
                    </div>
                  )}

                  {/* Structured Content Card */}
                  {renderStructuredContent(item)}

                  {/* Collapsible Technical Payload */}
                  {d.payload && Object.keys(d.payload).length > 0 && (
                    <div className="mt-3 pt-2 border-t border-[var(--border)]">
                      <button
                        type="button"
                        onClick={() => togglePayload(eventId)}
                        className="inline-flex items-center gap-1 text-[11px] font-mono text-[var(--text-2)] hover:text-[var(--text)] transition-colors cursor-pointer"
                      >
                        {isPayloadOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                        <span>{isPayloadOpen ? 'Hide Raw Payload' : 'View Raw Payload'}</span>
                      </button>
                      {isPayloadOpen && (
                        <div className="mt-2 p-3 rounded-[16px] bg-[var(--surface-tonal)] border border-[var(--border)] overflow-x-auto text-[12px] font-mono text-[var(--text)] leading-relaxed select-all">
                          <pre>{JSON.stringify(d.payload, null, 2)}</pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
