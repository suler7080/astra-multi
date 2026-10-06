import React, { useEffect, useState } from 'react';
import type { RunDetail, RunLogEntry } from '../types';
import { api } from '../api';
import {
  Terminal,
  AlertTriangle,
  AlertOctagon,
  Info,
  RefreshCw,
  Copy,
  Check,
  ChevronDown,
  ChevronRight,
  Search,
  CheckCircle2,
} from 'lucide-react';
import { useI18n } from '../i18n';

interface ExecutionLogsProps {
  run: RunDetail;
}

export const ExecutionLogs: React.FC<ExecutionLogsProps> = ({ run }) => {
  const { t } = useI18n();
  const [logs, setLogs] = useState<RunLogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [errorLevelFilter, setErrorLevelFilter] = useState<'ALL' | 'ERROR' | 'WARN' | 'INFO'>('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);
  const [copiedText, setCopiedText] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(!['FINAL', 'PARTIAL', 'FAILED', 'CANCELLED'].includes(run.status));

  const fetchLogs = async () => {
    try {
      setIsLoading(true);
      const data = await api.getRunLogs(run.run_id);
      setLogs(data);
    } catch (err) {
      console.error('Failed to fetch execution logs', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, [run.run_id]);

  useEffect(() => {
    if (!autoRefresh || ['FINAL', 'PARTIAL', 'FAILED', 'CANCELLED'].includes(run.status)) {
      return;
    }
    const interval = setInterval(() => {
      fetchLogs();
    }, 3000);
    return () => clearInterval(interval);
  }, [run.run_id, autoRefresh, run.status]);

  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopiedText(label);
    setTimeout(() => setCopiedText(null), 2000);
  };

  const filteredLogs = logs.filter((log) => {
    if (errorLevelFilter !== 'ALL' && log.level !== errorLevelFilter) {
      return false;
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchMsg = log.message.toLowerCase().includes(q);
      const matchNode = log.node.toLowerCase().includes(q);
      const matchDetails = log.details ? JSON.stringify(log.details).toLowerCase().includes(q) : false;
      return matchMsg || matchNode || matchDetails;
    }
    return true;
  });

  const errorCount = logs.filter((l) => l.level === 'ERROR').length;
  const warnCount = logs.filter((l) => l.level === 'WARN').length;
  const infoCount = logs.filter((l) => l.level === 'INFO').length;

  const getLevelBadgeClass = (level: string) => {
    switch (level) {
      case 'ERROR':
        return 'log-badge-error';
      case 'WARN':
        return 'log-badge-warn';
      case 'INFO':
        return 'log-badge-info';
      default:
        return 'log-badge-default';
    }
  };

  const getLevelIcon = (level: string) => {
    switch (level) {
      case 'ERROR':
        return <AlertOctagon size={13} className="text-rose-400" />;
      case 'WARN':
        return <AlertTriangle size={13} className="text-amber-400" />;
      case 'INFO':
        return <Info size={13} className="text-sky-400" />;
      default:
        return <CheckCircle2 size={13} className="text-slate-400" />;
    }
  };

  return (
    <div className="execution-logs-container">
      {/* Prominent Error Banner if run failed or error present */}
      {(run.status === 'FAILED' || run.stop_reason) && (
        <div className="error-diagnostic-banner">
          <div className="flex items-start gap-3">
            <AlertOctagon size={24} className="text-rose-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-rose-200">
                  {run.status === 'FAILED' ? t('logs_stopped_fatal') : `${run.status}: Execution Stopped`}
                </h3>
                <button
                  onClick={() => copyToClipboard(run.stop_reason || '', 'stop_reason')}
                  className="btn-copy-error text-xs flex items-center gap-1.5"
                >
                  {copiedText === 'stop_reason' ? (
                    <>
                      <Check size={13} className="text-emerald-400" />
                      <span>{t('logs_copied')}</span>
                    </>
                  ) : (
                    <>
                      <Copy size={13} />
                      <span>{t('logs_copy_error')}</span>
                    </>
                  )}
                </button>
              </div>
              <pre className="error-stop-reason-box">{run.stop_reason || 'Unknown execution error'}</pre>
            </div>
          </div>
        </div>
      )}

      {/* Toolbar / Filters */}
      <div className="logs-toolbar">
        <div className="flex items-center gap-2">
          <Terminal size={18} className="text-sky-400" />
          <span className="font-semibold text-sm text-slate-200">{t('logs_title')} ({logs.length})</span>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Level Filter Tabs */}
          <div className="level-filter-group">
            <button
              onClick={() => setErrorLevelFilter('ALL')}
              className={`filter-btn ${errorLevelFilter === 'ALL' ? 'filter-btn-active' : ''}`}
            >
              {t('logs_filter_all')} ({logs.length})
            </button>
            <button
              onClick={() => setErrorLevelFilter('ERROR')}
              className={`filter-btn ${errorLevelFilter === 'ERROR' ? 'filter-btn-active text-rose-300' : ''}`}
            >
              {t('logs_filter_error')} ({errorCount})
            </button>
            <button
              onClick={() => setErrorLevelFilter('WARN')}
              className={`filter-btn ${errorLevelFilter === 'WARN' ? 'filter-btn-active text-amber-300' : ''}`}
            >
              {t('logs_filter_warn')} ({warnCount})
            </button>
            <button
              onClick={() => setErrorLevelFilter('INFO')}
              className={`filter-btn ${errorLevelFilter === 'INFO' ? 'filter-btn-active text-sky-300' : ''}`}
            >
              {t('logs_filter_info')} ({infoCount})
            </button>
          </div>

          {/* Search box */}
          <div className="relative search-input-wrapper">
            <Search size={14} className="absolute left-2.5 top-2.5 text-slate-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('logs_search_placeholder')}
              className="form-input text-xs pl-8 pr-3 py-1.5 w-44"
            />
          </div>

          {/* Auto Refresh Toggle */}
          <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded bg-slate-800 border-slate-700"
            />
            <span>{t('logs_live_stream')}</span>
          </label>

          {/* Refresh button */}
          <button
            onClick={fetchLogs}
            disabled={isLoading}
            className="btn-secondary text-xs px-2.5 py-1.5 flex items-center gap-1.5"
            title={t('logs_refresh')}
          >
            <RefreshCw size={13} className={isLoading ? 'animate-spin text-sky-400' : ''} />
            <span>{t('logs_refresh')}</span>
          </button>

          {/* Copy all button */}
          <button
            onClick={() => {
              const text = logs
                .map((l) => `[${l.timestamp}] [${l.level}] [${l.node}] ${l.message}`)
                .join('\n');
              copyToClipboard(text, 'all_logs');
            }}
            className="btn-secondary text-xs px-2.5 py-1.5 flex items-center gap-1.5"
            title={t('logs_copy_logs')}
          >
            {copiedText === 'all_logs' ? (
              <>
                <Check size={13} className="text-emerald-400" />
                <span>{t('logs_copied')}</span>
              </>
            ) : (
              <>
                <Copy size={13} />
                <span>{t('logs_copy_logs')}</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Terminal Display */}
      <div className="logs-terminal-window">
        {filteredLogs.length === 0 ? (
          <div className="p-8 text-center text-slate-500 text-sm">
            {searchQuery || errorLevelFilter !== 'ALL'
              ? t('logs_no_match')
              : t('logs_no_logs')}
          </div>
        ) : (
          <div className="divide-y divide-slate-800/60 font-mono text-xs">
            {filteredLogs.map((log) => {
              const isExpanded = expandedLogId === log.id;
              const hasDetails = log.details && Object.keys(log.details).length > 0;
              const timeStr = log.timestamp.includes('T')
                ? log.timestamp.split('T')[1].replace('Z', '').slice(0, 8)
                : log.timestamp;

              return (
                <div
                  key={log.id}
                  className={`log-row-item ${log.level === 'ERROR' ? 'bg-rose-950/20' : log.level === 'WARN' ? 'bg-amber-950/10' : ''}`}
                >
                  <div
                    className="flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-slate-800/40 select-text"
                    onClick={() => hasDetails && setExpandedLogId(isExpanded ? null : log.id)}
                  >
                    {/* Expand icon */}
                    <button
                      className={`text-slate-500 hover:text-slate-300 ${!hasDetails ? 'opacity-0 cursor-default' : ''}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        if (hasDetails) setExpandedLogId(isExpanded ? null : log.id);
                      }}
                    >
                      {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </button>

                    {/* Timestamp */}
                    <span className="text-slate-500 whitespace-nowrap">{timeStr}</span>

                    {/* Level Badge */}
                    <div className="flex items-center gap-1.5 min-w-[70px]">
                      {getLevelIcon(log.level)}
                      <span className={getLevelBadgeClass(log.level)}>{log.level}</span>
                    </div>

                    {/* Node */}
                    <span className="text-slate-400 bg-slate-800/70 px-1.5 py-0.5 rounded text-[11px] whitespace-nowrap">
                      [{log.node}]
                    </span>

                    {/* Message */}
                    <span
                      className={`flex-1 break-words font-sans text-xs ${
                        log.level === 'ERROR'
                          ? 'text-rose-200 font-medium'
                          : log.level === 'WARN'
                          ? 'text-amber-200'
                          : 'text-slate-300'
                      }`}
                    >
                      {log.message}
                    </span>
                  </div>

                  {/* Expandable Details / Traceback */}
                  {isExpanded && hasDetails && (
                    <div className="px-10 py-3 bg-slate-950/80 border-t border-slate-800/80">
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-[11px] font-semibold text-slate-400">{t('logs_diagnostics_title')}</span>
                        <button
                          onClick={() => copyToClipboard(JSON.stringify(log.details, null, 2), `detail-${log.id}`)}
                          className="text-slate-400 hover:text-slate-200 text-[11px] flex items-center gap-1"
                        >
                          {copiedText === `detail-${log.id}` ? (
                            <>
                              <Check size={12} className="text-emerald-400" />
                              <span>{t('logs_copied')}</span>
                            </>
                          ) : (
                            <>
                              <Copy size={12} />
                              <span>{t('logs_copy_json')}</span>
                            </>
                          )}
                        </button>
                      </div>

                      {/* Traceback block if available */}
                      {Boolean(log.details?.traceback) && (
                        <div className="mb-3">
                          <span className="text-[11px] text-rose-400 font-semibold block mb-1">{t('logs_stack_trace')}</span>
                          <pre className="p-3 rounded bg-rose-950/30 border border-rose-900/50 text-rose-200 text-xs overflow-x-auto whitespace-pre font-mono">
                            {String(log.details?.traceback)}
                          </pre>
                        </div>
                      )}

                      {/* Full JSON payload */}
                      <pre className="p-3 rounded bg-slate-900 border border-slate-800 text-slate-300 text-xs overflow-x-auto whitespace-pre-wrap font-mono">
                        {JSON.stringify(log.details, null, 2)}
                      </pre>
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
