import React, { useEffect, useState, useRef, useCallback } from 'react';
import { api, classifyApiError } from './api';
import type {
  CloneRunData,
  CreateRunPayload,
  Decision,
  Evidence,
  FinalizeResult,
  Issue,
  PlanRevision,
  RunDetail,
  RunSummary,
  StreamEvent,
  ValidationReport,
} from './types';
import { Header } from './components/Header';
import { PhaseTracker } from './components/PhaseTracker';
import { NewRunModal } from './components/NewRunModal';
import { RunOverview } from './components/RunOverview';
import { DiscussionTimeline } from './components/DiscussionTimeline';
import { IssuesTable } from './components/IssuesTable';
import { DecisionsLog } from './components/DecisionsLog';
import { EvidenceLedger } from './components/EvidenceLedger';
import { PlanViewer } from './components/PlanViewer';
import { QualityGateModal } from './components/QualityGateModal';
import { ExecutionLogs } from './components/ExecutionLogs';
import { AuthModal } from './components/AuthModal';
import { SettingsModal } from './components/SettingsModal';
import { ConfirmModal } from './components/ConfirmModal';
import { DashboardHome } from './components/DashboardHome';
import { ErrorBanner, type GenericErrorInfo } from './components/ErrorBanner';
import { useI18n } from './i18nContext';
import {
  LayoutDashboard,
  MessageSquare,
  AlertOctagon,
  Compass,
  FileSearch,
  GitBranch,
  Terminal,
  CheckCircle2,
  ArrowLeft,
} from 'lucide-react';

export const App: React.FC = () => {
  const { t } = useI18n();
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [currentRun, setCurrentRun] = useState<RunDetail | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [currentPlan, setCurrentPlan] = useState<PlanRevision | null>(null);
  const [events, setEvents] = useState<StreamEvent[]>([]);

  const [activeTab, setActiveTab] = useState<'overview' | 'discussion' | 'issues' | 'decisions' | 'evidence' | 'plan' | 'logs'>('overview');
  const [isNewRunOpen, setIsNewRunOpen] = useState(false);
  const [cloneData, setCloneData] = useState<CloneRunData | null>(null);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const [authMode, setAuthMode] = useState<'setup' | 'login'>('login');
  const [isQualityModalOpen, setIsQualityModalOpen] = useState(false);
  const [qualityModalMode, setQualityModalMode] = useState<'validation' | 'finalize'>('validation');
  const [validationReport, setValidationReport] = useState<ValidationReport | null>(null);
  const [finalizeResult, setFinalizeResult] = useState<FinalizeResult | null>(null);

  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isDeletingId, setIsDeletingId] = useState<string | null>(null);
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [isSseConnected, setIsSseConnected] = useState(false);

  // Centralized Connection & Error state (Giai đoạn 1)
  const [connectionStatus, setConnectionStatus] = useState<'connected' | 'connecting' | 'offline'>('connected');
  const [retryCountdown, setRetryCountdown] = useState(10);
  const [isRetrying, setIsRetrying] = useState(false);
  const [genericError, setGenericError] = useState<GenericErrorInfo | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [hasConfiguredProvider, setHasConfiguredProvider] = useState<boolean>(false);

  const checkProviders = useCallback(async () => {
    try {
      const list = await api.listProviders();
      setHasConfiguredProvider((prev) => {
        const next = list.length > 0;
        return prev === next ? prev : next;
      });
    } catch {
      setHasConfiguredProvider((prev) => (prev ? false : prev));
    }
  }, []);

  const backoffDelayRef = useRef(10);
  const connectingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const handleOffline = useCallback(() => {
    setConnectionStatus((prev) => {
      if (prev === 'offline' || prev === 'connecting') return prev;
      if (!connectingTimeoutRef.current) {
        connectingTimeoutRef.current = setTimeout(() => {
          setConnectionStatus('offline');
          setRetryCountdown(backoffDelayRef.current);
          connectingTimeoutRef.current = null;
        }, 3000);
      }
      return 'connecting';
    });
  }, []);

  const handleError = useCallback((err: unknown, defaultMsg: string) => {
    const classified = classifyApiError(err, defaultMsg);
    if (classified.category === 'backend_offline') {
      handleOffline();
      return;
    }

    if (classified.category === 'unauthorized') {
      setIsAuthModalOpen(true);
      setAuthMode('login');
      return;
    }

    setGenericError({
      message: classified.userMessage,
      details: classified.details,
      code: classified.code,
      status: classified.status,
      correlationId: classified.correlationId,
    });
  }, [handleOffline]);

  // Sync runParam into window URL without reload
  const updateUrlParam = (runId: string) => {
    const url = new URL(window.location.href);
    if (runId) {
      url.searchParams.set('run', runId);
    } else {
      url.searchParams.delete('run');
    }
    window.history.replaceState({}, '', url.toString());
  };

  const loadRunDetails = useCallback(
    async (runId: string, silent = false) => {
      try {
        if (!silent) setIsLoading(true);
        const detail = await api.getRun(runId);
        setCurrentRun(detail);

        // Keep runs list in sync with current run phase and status
        setRuns((prev) =>
          prev.map((r) =>
            r.run_id === detail.run_id
              ? {
                  ...r,
                  phase: detail.phase,
                  status: detail.status,
                  revision: detail.revision,
                  stop_reason: detail.stop_reason,
                }
              : r
          )
        );

        // Concurrently fetch entities
        const [iss, dec, ev] = await Promise.all([
          api.getIssues(runId).catch(() => []),
          api.getDecisions(runId).catch(() => []),
          api.getEvidence(runId).catch(() => []),
        ]);
        setIssues(iss);
        setDecisions(dec);
        setEvidence(ev);

        if (detail.plan_revision) {
          try {
            const plan = await api.getPlan(runId, detail.plan_revision);
            setCurrentPlan(plan);
          } catch {
            setCurrentPlan(null);
          }
        } else {
          setCurrentPlan(null);
        }
      } catch (err: unknown) {
        if (!silent) handleError(err, t('err_load_run_detail'));
      } finally {
        if (!silent) setIsLoading(false);
      }
    },
    [handleError, t]
  );

  const loadRuns = useCallback(
    async (initialRunId?: string | null, silent = false) => {
      try {
        if (!silent) setIsLoading(true);
        void checkProviders();
        const list = await api.listRuns();
        setRuns((prev) => {
          if (
            prev.length === list.length &&
            prev.every(
              (r, idx) =>
                r.run_id === list[idx].run_id &&
                r.status === list[idx].status &&
                r.phase === list[idx].phase &&
                r.revision === list[idx].revision &&
                r.stop_reason === list[idx].stop_reason
            )
          ) {
            return prev;
          }
          return list;
        });

        if (initialRunId && list.some((r) => r.run_id === initialRunId)) {
          setSelectedRunId(initialRunId);
          updateUrlParam(initialRunId);
          await loadRunDetails(initialRunId, silent);
        } else if (initialRunId === undefined && selectedRunId) {
          // Sync selected run if present in updated list
          const inList = list.find((r) => r.run_id === selectedRunId);
          if (inList) {
            setCurrentRun((prev) => {
              if (!prev) return null;
              if (inList.phase !== prev.phase || inList.status !== prev.status) {
                return {
                  ...prev,
                  phase: inList.phase,
                  status: inList.status,
                  stop_reason: inList.stop_reason,
                };
              }
              return prev;
            });
          }
        } else if (initialRunId === null) {
          setSelectedRunId(null);
          setCurrentRun(null);
          updateUrlParam('');
        }
      } catch (err: unknown) {
        if (!silent) handleError(err, t('err_load_runs'));
      } finally {
        if (!silent) setIsLoading(false);
      }
    },
    [selectedRunId, loadRunDetails, handleError, t, checkProviders]
  );

  const performRetry = useCallback(async () => {
    if (isRetrying) return;
    setIsRetrying(true);
    try {
      const auth = await api.getAuthStatus();
      if (connectingTimeoutRef.current) {
        clearTimeout(connectingTimeoutRef.current);
        connectingTimeoutRef.current = null;
      }
      const wasDisconnected = connectionStatus === 'offline' || connectionStatus === 'connecting';
      setConnectionStatus('connected');
      backoffDelayRef.current = 10;
      setRetryCountdown(10);

      if (wasDisconnected) {
        setToastMessage(t('conn_reconnected'));
        setTimeout(() => setToastMessage(null), 4000);
      }

      if (auth.setup_required) {
        setAuthMode('setup');
        setIsAuthModalOpen(true);
      } else if (!auth.authenticated) {
        setAuthMode('login');
        setIsAuthModalOpen(true);
      } else {
        setIsAuthModalOpen(false);
        const params = new URLSearchParams(window.location.search);
        const runParam = params.get('run');
        void loadRuns(runParam);
        void checkProviders();
      }
    } catch (err: unknown) {
      const classified = classifyApiError(err);
      if (classified.category === 'backend_offline') {
        backoffDelayRef.current = Math.min(backoffDelayRef.current + 5, 30);
        setRetryCountdown(backoffDelayRef.current);
        setConnectionStatus('offline');
      } else {
        setConnectionStatus('connected');
        backoffDelayRef.current = 10;
        setRetryCountdown(10);
        handleError(err, t('err_connect'));
      }
    } finally {
      setIsRetrying(false);
    }
  }, [connectionStatus, isRetrying, loadRuns, handleError, t, checkProviders]);

  // Auto-retry timer when connection is offline
  useEffect(() => {
    if (connectionStatus !== 'offline') return;

    const timer = setInterval(() => {
      setRetryCountdown((prev) => {
        if (prev <= 1) {
          void performRetry();
          return backoffDelayRef.current;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [connectionStatus, performRetry]);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (connectingTimeoutRef.current) {
        clearTimeout(connectingTimeoutRef.current);
      }
    };
  }, []);

  // Check auth status on mount and load runs if authenticated
  useEffect(() => {
    let ignore = false;
    api
      .getAuthStatus()
      .then((status) => {
        if (ignore) return;
        setConnectionStatus('connected');
        if (status.setup_required) {
          setAuthMode('setup');
          setIsAuthModalOpen(true);
          return;
        }
        if (!status.authenticated) {
          setAuthMode('login');
          setIsAuthModalOpen(true);
          return;
        }
        const params = new URLSearchParams(window.location.search);
        const runParam = params.get('run');
        void loadRuns(runParam);
      })
      .catch((err: unknown) => {
        if (ignore) return;
        const classified = classifyApiError(err);
        if (classified.category === 'backend_offline') {
          handleOffline();
        } else {
          const params = new URLSearchParams(window.location.search);
          const runParam = params.get('run');
          void loadRuns(runParam);
        }
      });

    return () => {
      ignore = true;
    };
  }, [loadRuns, handleOffline]);

  // Setup SSE stream for selected run
  useEffect(() => {
    if (!selectedRunId) return;

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    const sseUrl = api.getEventSourceUrl(selectedRunId);
    const es = new EventSource(sseUrl);
    eventSourceRef.current = es;

    es.onopen = () => {
      setIsSseConnected(true);
    };

    const handleStreamEvent = (type: string, data: any, lastId?: string) => {
      const streamEv: StreamEvent = {
        id: lastId ? Number(lastId) : Date.now(),
        event: type,
        data,
      };
      setEvents((prev) => {
        if (prev.some((p) => p.id === streamEv.id && p.event === streamEv.event)) {
          return prev;
        }
        return [...prev, streamEv];
      });

      // Instantly update phase & status without waiting for network call
      if (type === 'transition_run' || type === 'transition_phase') {
        const res = data?.payload?.result || data?.result;
        const newPhase = res?.phase;
        const newStatus = res?.status;
        if (newPhase) {
          setCurrentRun((prev) => {
            if (!prev) return prev;
            return {
              ...prev,
              phase: newPhase,
              status: newStatus || prev.status,
            };
          });
          setRuns((prev) =>
            prev.map((r) =>
              r.run_id === selectedRunId
                ? { ...r, phase: newPhase, status: newStatus || r.status }
                : r
            )
          );
        }
      } else if (type === 'run_completed') {
        const newStatus = data?.status;
        const newPhase = data?.phase;
        const stopReason = data?.stop_reason;
        if (newStatus || newPhase) {
          setCurrentRun((prev) => {
            if (!prev) return prev;
            return {
              ...prev,
              phase: newPhase || prev.phase,
              status: newStatus || prev.status,
              stop_reason: stopReason ?? prev.stop_reason,
            };
          });
          setRuns((prev) =>
            prev.map((r) =>
              r.run_id === selectedRunId
                ? {
                    ...r,
                    phase: newPhase || r.phase,
                    status: newStatus || r.status,
                    stop_reason: stopReason ?? r.stop_reason,
                  }
                : r
            )
          );
        }
      }

      // Silent background refresh of run details
      loadRunDetails(selectedRunId, true);
    };

    es.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        handleStreamEvent(parsed.type || 'message', parsed, e.lastEventId);
      } catch {
        // raw data
      }
    };

    // Listen to all custom events emitted by domain & worker
    const customTypes = [
      'transition_run',
      'transition_phase',
      'add_record',
      'commit_plan',
      'change_issue',
      'answer_question',
      'revise_task',
      'run_completed',
      'record_issue',
      'record_decision',
      'ask_question',
    ];

    customTypes.forEach((type) => {
      es.addEventListener(type, (e: MessageEvent) => {
        try {
          const parsed = JSON.parse(e.data);
          handleStreamEvent(type, parsed, e.lastEventId);
        } catch {
          // parse error
        }
      });
    });

    // Backend ends the SSE stream with a "stream_error" event (api/worker.py) when
    // the run's event feed fails, then closes it server-side. EventSource would
    // auto-reconnect into a loop while the error persists, so close it here and
    // rely on the periodic polling below, which runs independently of the stream.
    es.addEventListener('stream_error', (e: MessageEvent) => {
      let backendMessage: string | undefined;
      try {
        const parsed = JSON.parse(e.data) as { message?: unknown };
        if (typeof parsed?.message === 'string') backendMessage = parsed.message;
      } catch {
        // Malformed payload — the generic message below still informs the user.
      }
      // Close first to stop the reconnect loop, then flag the connection as down.
      es.close();
      if (eventSourceRef.current === es) {
        eventSourceRef.current = null;
      }
      setIsSseConnected(false);
      setGenericError({
        message: t('conn_stream_error'),
        details: backendMessage,
      });
    });

    es.onerror = () => {
      setIsSseConnected(false);
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [selectedRunId, loadRunDetails, t]);

  // Periodic background safety-net polling for the selected run
  useEffect(() => {
    if (!selectedRunId) return;

    const isActive =
      currentRun?.status === 'RUNNING' ||
      currentRun?.status === 'WAITING_FOR_INPUT';

    // Poll active runs every 2.5s, or disconnected SSE every 2s, or idle runs every 12s
    const pollInterval = !isSseConnected ? 2000 : isActive ? 2500 : 12000;

    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') {
        void loadRunDetails(selectedRunId, true);
      }
    }, pollInterval);

    return () => clearInterval(timer);
  }, [selectedRunId, currentRun?.status, isSseConnected, loadRunDetails]);

  // Periodic background auto-refresh for runs list (dashboard / header)
  useEffect(() => {
    // Suspend polling when any modal is open to prevent DOM disruptions and closing select menus
    if (isSettingsOpen || isNewRunOpen || isQualityModalOpen || isAuthModalOpen || Boolean(deletingRunId)) {
      return;
    }

    const hasActiveRuns = runs.some(
      (r) => r.status === 'RUNNING' || r.status === 'WAITING_FOR_INPUT'
    );
    // Poll active runs every 2.5s; inside a selected run every 15s; idle dashboard every 30s
    const intervalTime = hasActiveRuns ? 2500 : selectedRunId ? 15000 : 30000;

    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') {
        void loadRuns(undefined, true);
      }
    }, intervalTime);

    return () => clearInterval(timer);
  }, [selectedRunId, runs, loadRuns, isSettingsOpen, isNewRunOpen, isQualityModalOpen, isAuthModalOpen, deletingRunId]);

  // Immediately refresh on tab visibility / focus change
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        if (isSettingsOpen || isNewRunOpen || isQualityModalOpen || isAuthModalOpen || Boolean(deletingRunId)) {
          return;
        }
        if (selectedRunId) {
          void loadRunDetails(selectedRunId, true);
        } else {
          void loadRuns(undefined, true);
        }
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [selectedRunId, loadRuns, loadRunDetails, isSettingsOpen, isNewRunOpen, isQualityModalOpen, isAuthModalOpen, deletingRunId]);

  const handleSelectRun = (runId: string) => {
    setEvents([]);
    setIsSseConnected(false);
    if (!runId) {
      setSelectedRunId(null);
      setCurrentRun(null);
      updateUrlParam('');
      return;
    }
    setSelectedRunId(runId);
    updateUrlParam(runId);
    void loadRunDetails(runId);
  };

  const handleCloneRun = (run: RunDetail) => {
    setCloneData({
      goal: run.goal,
      requirements: (run.requirements || []).map((r) => (typeof r === 'string' ? r : r.text || '')),
      mode: run.mode === 'repo' ? 'repo' : 'greenfield',
      token_limit: run.token_limit ?? 250000,
      cost_limit: run.cost_limit ?? 5.0,
      max_rounds: run.max_rounds ?? 2,
      parent_run_id: run.run_id,
    });
    setIsNewRunOpen(true);
  };

  const showFeedback = useCallback((msg: string) => {
    setActionMessage(msg);
    setTimeout(() => setActionMessage(null), 4000);
  }, []);

  const handleCloseNewRun = useCallback(() => {
    setIsNewRunOpen(false);
    setCloneData(null);
  }, []);

  const handleCreateRun = useCallback(async (payload: CreateRunPayload, idempotencyKey: string) => {
    try {
      setIsSubmitting(true);
      setGenericError(null);
      const res = await api.createRun(payload, idempotencyKey);
      setIsNewRunOpen(false);
      setCloneData(null);
      showFeedback(t('feedback_run_started').replace('{id}', res.run_id));
      await loadRuns(res.run_id);
    } catch (err: unknown) {
      handleError(err, t('err_launch_run'));
    } finally {
      setIsSubmitting(false);
    }
  }, [t, loadRuns, handleError, showFeedback]);

  const handleAnswerQuestion = async (questionId: string, answer: string, expectedRevision: number) => {
    if (!selectedRunId) return;
    try {
      setIsLoading(true);
      await api.answerQuestion(selectedRunId, questionId, answer, expectedRevision);
      showFeedback(t('feedback_question_answered'));
      await loadRunDetails(selectedRunId);
    } catch (err: unknown) {
      handleError(err, t('err_answer_question'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleResumeRun = async () => {
    if (!selectedRunId) return;
    try {
      setIsLoading(true);
      await api.resumeRun(selectedRunId);
      showFeedback(t('feedback_run_resumed'));
      await loadRunDetails(selectedRunId);
    } catch (err: unknown) {
      handleError(err, t('err_resume_run'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleCancelRun = async (reason: string) => {
    if (!selectedRunId) return;
    try {
      setIsLoading(true);
      await api.cancelRun(selectedRunId, reason);
      showFeedback(t('feedback_run_cancelled'));
      await loadRunDetails(selectedRunId);
    } catch (err: unknown) {
      handleError(err, t('err_cancel_run'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleDeleteRun = (runId: string): Promise<void> => {
    if (!runId) return Promise.resolve();
    setDeletingRunId(runId);
    return Promise.resolve();
  };

  const handleConfirmDeleteRun = async () => {
    if (!deletingRunId) return;
    const runId = deletingRunId;
    try {
      setIsDeletingId(runId);
      if (eventSourceRef.current && selectedRunId === runId) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      await api.deleteRun(runId, true);
      showFeedback(t('feedback_run_deleted'));
      if (selectedRunId === runId) {
        setSelectedRunId(null);
        setCurrentRun(null);
        updateUrlParam('');
      }
      await loadRuns();
      setDeletingRunId(null);
    } catch (err: unknown) {
      handleError(err, t('err_delete_run'));
    } finally {
      setIsDeletingId(null);
    }
  };

  const handleValidate = async () => {
    if (!selectedRunId) return;
    try {
      setIsLoading(true);
      const rep = await api.validateRun(selectedRunId);
      setValidationReport(rep);
      setQualityModalMode('validation');
      setIsQualityModalOpen(true);
    } catch (err: unknown) {
      handleError(err, t('err_validate_gates'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleFinalize = async () => {
    if (!selectedRunId) return;
    try {
      setIsLoading(true);
      const res = await api.finalizeRun(selectedRunId);
      setFinalizeResult(res);
      setQualityModalMode('finalize');
      setIsQualityModalOpen(true);
      await loadRunDetails(selectedRunId);
      await loadRuns(selectedRunId);
    } catch (err: unknown) {
      handleError(err, t('err_finalize_plan'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectPlanRevision = async (rev: number) => {
    if (!selectedRunId) return;
    try {
      const plan = await api.getPlan(selectedRunId, rev);
      setCurrentPlan(plan);
    } catch (err: unknown) {
      handleError(err, t('err_load_run_detail'));
    }
  };

  const handleExportMarkdown = async (rev?: number) => {
    if (!selectedRunId) return;
    try {
      const md = await api.exportPlanMarkdown(selectedRunId, rev);
      downloadFile(md, `plan-${selectedRunId}-rev${rev || currentRun?.revision || 1}.md`, 'text/markdown');
    } catch (err: unknown) {
      handleError(err, t('err_export_md'));
    }
  };

  const handleExportJson = async (rev?: number) => {
    if (!selectedRunId) return;
    try {
      const data = await api.exportPlanJson(selectedRunId, rev);
      downloadFile(JSON.stringify(data, null, 2), `plan-${selectedRunId}-rev${rev || currentRun?.revision || 1}.json`, 'application/json');
    } catch (err: unknown) {
      handleError(err, t('err_export_json'));
    }
  };

  const downloadFile = (content: string, filename: string, mime: string) => {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleProviderChanged = useCallback(() => {
    showFeedback(t('feedback_provider_updated'));
    if (selectedRunId) loadRunDetails(selectedRunId);
    void checkProviders();
  }, [t, selectedRunId, loadRunDetails, checkProviders, showFeedback]);


  return (
    <div className="app-container">
      <Header
        runs={runs}
        selectedRunId={selectedRunId}
        onSelectRun={handleSelectRun}
        onOpenNewRun={() => setIsNewRunOpen(true)}
        onRefresh={() => selectedRunId && loadRunDetails(selectedRunId)}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onLogout={() => {
          api.logout();
          setIsAuthModalOpen(true);
          setAuthMode('login');
        }}
        isLoading={isLoading}
        isOffline={connectionStatus === 'offline'}
      />

      <ErrorBanner
        connectionStatus={connectionStatus}
        countdown={retryCountdown}
        isRetrying={isRetrying}
        onRetry={() => void performRetry()}
        genericError={genericError}
        onDismissGenericError={() => setGenericError(null)}
      />

      {toastMessage && (
        <div className="global-toast-success" role="status" aria-live="polite">
          <CheckCircle2 size={16} />
          <span>{toastMessage}</span>
        </div>
      )}

      {currentRun ? (
        <main className="max-w-[1280px] mx-auto px-6 sm:px-10 lg:px-16 py-8 w-full bg-[var(--bg-alt)] min-h-screen overflow-x-hidden">
          {/* Top Bar matching Image 2 */}
          <div className="flex items-center justify-between gap-4 mb-6 rise">
            <button
              type="button"
              onClick={() => handleSelectRun('')}
              className="h-10 px-4 rounded-full border border-[var(--border-strong)] bg-[var(--bg)] hover:bg-[var(--surface-tonal)] text-[var(--text)] text-[14px] font-medium inline-flex items-center gap-2 transition-colors cursor-pointer"
            >
              <ArrowLeft size={16} />
              <span>{t('run_back_all_runs')}</span>
            </button>

            <div className="flex items-center gap-3">
              {(currentRun.status === 'RUNNING' || currentRun.status === 'WAITING_FOR_INPUT') && (
                <button
                  type="button"
                  onClick={() => {
                    const reason = window.prompt(t('overview_cancel_placeholder'), t('overview_default_stop_reason'));
                    if (reason !== null) {
                      void handleCancelRun(reason || t('overview_default_stop_reason'));
                    }
                  }}
                  className="h-10 px-5 rounded-full border border-[var(--error)]/30 text-[var(--error)] hover:bg-[var(--error-tonal)] text-[14px] font-medium transition-colors cursor-pointer"
                >
                  {t('run_cancel_btn')}
                </button>
              )}
            </div>
          </div>

          {/* Goal H1 & Badges row matching Image 2 */}
          <div className="mb-6 rise">
            <h1 className="text-[clamp(30px,4vw,48px)] font-medium text-[var(--text)] tracking-tight leading-tight mb-3">
              {currentRun.goal}
            </h1>
            <div className="flex items-center flex-wrap gap-2.5">
              {currentRun.status === 'RUNNING' && (
                <span className="chip chip-accent text-[12px] py-1 px-3">
                  <span className="w-2 h-2 rounded-full bg-[var(--accent)] pulse" />
                  {t('status_running')}
                </span>
              )}
              {currentRun.status === 'WAITING_FOR_INPUT' && (
                <span className="chip chip-warn text-[12px] py-1 px-3">
                  {t('status_waiting')}
                </span>
              )}
              {currentRun.status === 'FINAL' && (
                <span className="chip chip-success text-[12px] py-1 px-3">
                  {t('status_final')}
                </span>
              )}
              {currentRun.status === 'FAILED' && (
                <span className="chip chip-error text-[12px] py-1 px-3">
                  {t('status_failed')}
                </span>
              )}
              {currentRun.status === 'CANCELLED' && (
                <span className="chip chip-neutral text-[12px] py-1 px-3">
                  {t('status_cancelled')}
                </span>
              )}

              <span className="chip chip-neutral font-medium text-[12px] py-1 px-3">
                Vòng {currentRun.revision} / {currentRun.max_rounds || 2}
              </span>

              <span className="font-mono text-[12px] px-3 py-1 rounded-full border border-[var(--border-strong)] text-[var(--text-2)] font-medium">
                {currentRun.run_id}
              </span>
            </div>
          </div>

          <PhaseTracker
            currentPhase={currentRun.phase}
            status={currentRun.status}
            stopReason={currentRun.stop_reason}
          />

          {/* Navigation Tabs (Google pill style) */}
          <nav className="flex items-center gap-1.5 overflow-x-auto pb-2 mb-6" aria-label={t('nav_run_views_label')}>
            <button
              onClick={() => setActiveTab('overview')}
              className={`h-9 px-4 rounded-full text-[13px] font-medium transition-colors cursor-pointer flex items-center gap-1.5 shrink-0 ${
                activeTab === 'overview'
                  ? 'bg-[var(--accent-tonal)] text-[var(--accent-on-tonal)]'
                  : 'text-[var(--text-2)] hover:bg-[var(--surface-tonal)]'
              }`}
            >
              <LayoutDashboard size={15} />
              <span>{t('tab_overview')}</span>
              {currentRun.pending_questions.length > 0 && (
                <span className="chip chip-warn text-[10px] py-0 px-1.5">{currentRun.pending_questions.length}</span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('discussion')}
              className={`h-9 px-4 rounded-full text-[13px] font-medium transition-colors cursor-pointer flex items-center gap-1.5 shrink-0 ${
                activeTab === 'discussion'
                  ? 'bg-[var(--accent-tonal)] text-[var(--accent-on-tonal)]'
                  : 'text-[var(--text-2)] hover:bg-[var(--surface-tonal)]'
              }`}
            >
              <MessageSquare size={15} />
              <span>{t('tab_discussion')} ({events.length})</span>
            </button>

            <button
              onClick={() => setActiveTab('issues')}
              className={`h-9 px-4 rounded-full text-[13px] font-medium transition-colors cursor-pointer flex items-center gap-1.5 shrink-0 ${
                activeTab === 'issues'
                  ? 'bg-[var(--accent-tonal)] text-[var(--accent-on-tonal)]'
                  : 'text-[var(--text-2)] hover:bg-[var(--surface-tonal)]'
              }`}
            >
              <AlertOctagon size={15} />
              <span>{t('tab_issues')} ({issues.length})</span>
            </button>

            <button
              onClick={() => setActiveTab('decisions')}
              className={`h-9 px-4 rounded-full text-[13px] font-medium transition-colors cursor-pointer flex items-center gap-1.5 shrink-0 ${
                activeTab === 'decisions'
                  ? 'bg-[var(--accent-tonal)] text-[var(--accent-on-tonal)]'
                  : 'text-[var(--text-2)] hover:bg-[var(--surface-tonal)]'
              }`}
            >
              <Compass size={15} />
              <span>{t('tab_decisions')} ({decisions.length})</span>
            </button>

            <button
              onClick={() => setActiveTab('evidence')}
              className={`h-9 px-4 rounded-full text-[13px] font-medium transition-colors cursor-pointer flex items-center gap-1.5 shrink-0 ${
                activeTab === 'evidence'
                  ? 'bg-[var(--accent-tonal)] text-[var(--accent-on-tonal)]'
                  : 'text-[var(--text-2)] hover:bg-[var(--surface-tonal)]'
              }`}
            >
              <FileSearch size={15} />
              <span>{t('tab_evidence')} ({evidence.length})</span>
            </button>

            <button
              onClick={() => setActiveTab('plan')}
              className={`h-9 px-4 rounded-full text-[13px] font-medium transition-colors cursor-pointer flex items-center gap-1.5 shrink-0 ${
                activeTab === 'plan'
                  ? 'bg-[var(--accent-tonal)] text-[var(--accent-on-tonal)]'
                  : 'text-[var(--text-2)] hover:bg-[var(--surface-tonal)]'
              }`}
            >
              <GitBranch size={15} />
              <span>{t('tab_plan')}</span>
            </button>

            <button
              onClick={() => setActiveTab('logs')}
              className={`h-9 px-4 rounded-full text-[13px] font-medium transition-colors cursor-pointer flex items-center gap-1.5 shrink-0 ${
                activeTab === 'logs'
                  ? 'bg-[var(--accent-tonal)] text-[var(--accent-on-tonal)]'
                  : 'text-[var(--text-2)] hover:bg-[var(--surface-tonal)]'
              }`}
            >
              <Terminal size={15} />
              <span>{t('tab_logs')}</span>
              {currentRun.status === 'FAILED' && (
                <span className="chip chip-error text-[10px] py-0 px-1.5">{t('tab_error_badge')}</span>
              )}
            </button>
          </nav>

          {/* Tab Views */}
          <div className="tab-content-area">
            {activeTab === 'overview' && (
              <RunOverview
                run={currentRun}
                currentPlan={currentPlan}
                issues={issues}
                decisions={decisions}
                evidence={evidence}
                onSelectPlanRevision={handleSelectPlanRevision}
                onAnswerQuestion={handleAnswerQuestion}
                onResumeRun={handleResumeRun}
                onCancelRun={handleCancelRun}
                onDeleteRun={() => handleDeleteRun(selectedRunId ?? '')}
                onValidate={handleValidate}
                onFinalize={handleFinalize}
                onExportMarkdown={() => handleExportMarkdown()}
                onExportJson={() => handleExportJson()}
                isProcessing={isLoading}
                isDeleting={isDeletingId === selectedRunId}
                actionMessage={actionMessage}
                onViewLogs={() => setActiveTab('logs')}
                onCloneRun={handleCloneRun}
              />
            )}

            {activeTab === 'discussion' && (
              <DiscussionTimeline
                events={events}
                isConnected={isSseConnected}
              />
            )}

            {activeTab === 'issues' && (
              <IssuesTable issues={issues} />
            )}

            {activeTab === 'decisions' && (
              <DecisionsLog decisions={decisions} />
            )}

            {activeTab === 'evidence' && (
              <EvidenceLedger evidence={evidence} />
            )}

            {activeTab === 'plan' && (
              <PlanViewer
                currentPlan={currentPlan}
                totalPlansCount={currentRun.plans_count}
                onSelectRevision={handleSelectPlanRevision}
                onExportMarkdown={handleExportMarkdown}
                onExportJson={handleExportJson}
                issues={issues}
                decisions={decisions}
                evidence={evidence}
              />
            )}

            {activeTab === 'logs' && (
              <ExecutionLogs run={currentRun} />
            )}
          </div>
        </main>
      ) : (
        <DashboardHome
          runs={runs}
          onSelectRun={handleSelectRun}
          onDeleteRun={handleDeleteRun}
          onOpenNewRun={() => {
            setCloneData(null);
            setIsNewRunOpen(true);
          }}
          onOpenSettings={() => setIsSettingsOpen(true)}
          onRefresh={() => {
            void loadRuns();
            void checkProviders();
          }}
          isLoading={isLoading}
          isDeletingId={isDeletingId}
          isBackendOffline={connectionStatus === 'offline'}
          hasConfiguredProvider={hasConfiguredProvider}
          retryCountdown={retryCountdown}
          onRetry={() => void performRetry()}
          isRetrying={isRetrying}
        />
      )}

      <NewRunModal
        isOpen={isNewRunOpen}
        onClose={handleCloseNewRun}
        onSubmit={handleCreateRun}
        isSubmitting={isSubmitting}
        error={genericError?.message || null}
        initialData={cloneData}
      />

      <QualityGateModal
        isOpen={isQualityModalOpen}
        onClose={() => setIsQualityModalOpen(false)}
        report={validationReport}
        finalizeResult={finalizeResult}
        mode={qualityModalMode}
      />

      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        onProviderChanged={handleProviderChanged}
      />

      <ConfirmModal
        isOpen={Boolean(deletingRunId)}
        title={t('dash_confirm_delete_title')}
        message={
          <div>
            <p>
              {(() => {
                const target = runs.find((r) => r.run_id === deletingRunId);
                const isActive = target
                  ? target.status === 'RUNNING' || target.status === 'WAITING_FOR_INPUT'
                  : currentRun
                    ? currentRun.status === 'RUNNING' || currentRun.status === 'WAITING_FOR_INPUT'
                    : false;
                return isActive ? t('dash_confirm_delete_active') : t('dash_confirm_delete');
              })()}
            </p>
            <p className="mt-2.5 font-mono text-[12px] px-2.5 py-1 rounded-full bg-[var(--surface-tonal)] text-[var(--text-2)] border border-[var(--border)] inline-block">
              {deletingRunId}
            </p>
          </div>
        }
        confirmText={t('dash_btn_delete_run')}
        cancelText={t('modal_btn_cancel')}
        variant="danger"
        isLoading={Boolean(isDeletingId)}
        onClose={() => setDeletingRunId(null)}
        onConfirm={handleConfirmDeleteRun}
      />

      {isAuthModalOpen && (
        <AuthModal
          mode={authMode}
          onAuthenticated={() => {
            setIsAuthModalOpen(false);
            const params = new URLSearchParams(window.location.search);
            const runParam = params.get('run');
            loadRuns(runParam);
            void checkProviders();
          }}
        />
      )}
    </div>
  );
};

export default App;
