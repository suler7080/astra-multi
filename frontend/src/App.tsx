import React, { useEffect, useState, useRef } from 'react';
import { api, ApiError } from './api';
import type {
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
import { DashboardHome } from './components/DashboardHome';
import { useI18n } from './i18n';
import {
  LayoutDashboard,
  MessageSquare,
  AlertOctagon,
  Compass,
  FileSearch,
  GitBranch,
  Terminal,
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
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const [authMode, setAuthMode] = useState<'setup' | 'login'>('login');
  const [isQualityModalOpen, setIsQualityModalOpen] = useState(false);
  const [qualityModalMode, setQualityModalMode] = useState<'validation' | 'finalize'>('validation');
  const [validationReport, setValidationReport] = useState<ValidationReport | null>(null);
  const [finalizeResult, setFinalizeResult] = useState<FinalizeResult | null>(null);

  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSseConnected, setIsSseConnected] = useState(false);

  const eventSourceRef = useRef<EventSource | null>(null);

  // Check auth status on mount and load runs if authenticated
  useEffect(() => {
    checkAuthAndInit();
  }, []);

  const checkAuthAndInit = async () => {
    try {
      const status = await api.getAuthStatus();
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
      loadRuns(runParam);
    } catch {
      const params = new URLSearchParams(window.location.search);
      const runParam = params.get('run');
      loadRuns(runParam);
    }
  };

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

  const loadRuns = async (initialRunId?: string | null) => {
    try {
      setIsLoading(true);
      const list = await api.listRuns();
      setRuns(list);

      if (initialRunId && list.some((r) => r.run_id === initialRunId)) {
        setSelectedRunId(initialRunId);
        updateUrlParam(initialRunId);
        await loadRunDetails(initialRunId);
      } else {
        setSelectedRunId(null);
        setCurrentRun(null);
        updateUrlParam('');
      }
    } catch (err: unknown) {
      handleError(err, 'Failed to load runs');
    } finally {
      setIsLoading(false);
    }
  };

  const loadRunDetails = async (runId: string) => {
    try {
      setIsLoading(true);
      const detail = await api.getRun(runId);
      setCurrentRun(detail);

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
      handleError(err, `Failed to load run ${runId}`);
    } finally {
      setIsLoading(false);
    }
  };

  // Setup SSE stream for selected run
  useEffect(() => {
    if (!selectedRunId) return;

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    setEvents([]);
    setIsSseConnected(false);

    const sseUrl = api.getEventSourceUrl(selectedRunId);
    const es = new EventSource(sseUrl);
    eventSourceRef.current = es;

    es.onopen = () => {
      setIsSseConnected(true);
    };

    es.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        const streamEv: StreamEvent = {
          id: e.lastEventId ? Number(e.lastEventId) : Date.now(),
          event: parsed.type || 'message',
          data: parsed,
        };
        setEvents((prev) => [...prev, streamEv]);
      } catch {
        // raw data
      }
    };

    // Listen to custom events
    const customTypes = [
      'commit_plan',
      'record_issue',
      'record_decision',
      'ask_question',
      'transition_phase',
      'run_completed',
    ];

    customTypes.forEach((type) => {
      es.addEventListener(type, (e: MessageEvent) => {
        try {
          const parsed = JSON.parse(e.data);
          const streamEv: StreamEvent = {
            id: e.lastEventId ? Number(e.lastEventId) : Date.now(),
            event: type,
            data: parsed,
          };
          setEvents((prev) => [...prev, streamEv]);

          // Refresh details on state changes
          loadRunDetails(selectedRunId);
        } catch {
          // parse error
        }
      });
    });

    es.onerror = () => {
      setIsSseConnected(false);
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [selectedRunId]);

  const handleSelectRun = (runId: string) => {
    if (!runId) {
      setSelectedRunId(null);
      setCurrentRun(null);
      updateUrlParam('');
      return;
    }
    setSelectedRunId(runId);
    updateUrlParam(runId);
    loadRunDetails(runId);
  };

  const handleCreateRun = async (payload: CreateRunPayload, idempotencyKey: string) => {
    try {
      setIsSubmitting(true);
      setErrorMessage(null);
      const res = await api.createRun(payload, idempotencyKey);
      setIsNewRunOpen(false);
      showFeedback(`Run ${res.run_id} started successfully!`);
      await loadRuns(res.run_id);
    } catch (err: unknown) {
      handleError(err, 'Failed to launch new run');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAnswerQuestion = async (questionId: string, answer: string, expectedRevision: number) => {
    if (!selectedRunId) return;
    try {
      setIsLoading(true);
      await api.answerQuestion(selectedRunId, questionId, answer, expectedRevision);
      showFeedback(t('feedback_question_answered'));
      await loadRunDetails(selectedRunId);
    } catch (err: unknown) {
      handleError(err, 'Failed to submit answer');
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
      handleError(err, 'Failed to resume run');
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
      handleError(err, 'Failed to cancel run');
    } finally {
      setIsLoading(false);
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
      handleError(err, 'Validation failed');
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
    } catch (err: unknown) {
      handleError(err, 'Finalization failed');
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
      handleError(err, `Failed to fetch plan revision ${rev}`);
    }
  };

  const handleExportMarkdown = async (rev?: number) => {
    if (!selectedRunId) return;
    try {
      const md = await api.exportPlanMarkdown(selectedRunId, rev);
      downloadFile(md, `plan-${selectedRunId}-rev${rev || currentRun?.revision || 1}.md`, 'text/markdown');
    } catch (err: unknown) {
      handleError(err, 'Failed to export Markdown');
    }
  };

  const handleExportJson = async (rev?: number) => {
    if (!selectedRunId) return;
    try {
      const data = await api.exportPlanJson(selectedRunId, rev);
      downloadFile(JSON.stringify(data, null, 2), `plan-${selectedRunId}-rev${rev || currentRun?.revision || 1}.json`, 'application/json');
    } catch (err: unknown) {
      handleError(err, 'Failed to export JSON');
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

  const showFeedback = (msg: string) => {
    setActionMessage(msg);
    setTimeout(() => setActionMessage(null), 4000);
  };

  const handleError = (err: unknown, defaultMsg: string) => {
    let msg = defaultMsg;
    if (err instanceof ApiError) {
      msg = `${err.code}: ${err.message}`;
      if (err.status === 401) {
        setIsAuthModalOpen(true);
        setAuthMode('login');
      }
    } else if (err instanceof Error) {
      msg = err.message;
    }
    setErrorMessage(msg);
    setTimeout(() => setErrorMessage(null), 6000);
  };

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
      />

      {errorMessage && (
        <div className="global-error-toast" role="alert">
          <span>{errorMessage}</span>
          <button onClick={() => setErrorMessage(null)} className="btn-text-sm">Dismiss</button>
        </div>
      )}

      {currentRun ? (
        <main className="main-content">
          <PhaseTracker
            currentPhase={currentRun.phase}
            status={currentRun.status}
            stopReason={currentRun.stop_reason}
          />

          {/* Navigation Tabs */}
          <nav className="tab-navigation" aria-label="Run Views">
            <button
              onClick={() => setActiveTab('overview')}
              className={`nav-tab ${activeTab === 'overview' ? 'tab-active' : ''}`}
            >
              <LayoutDashboard size={15} />
              <span>{t('tab_overview')}</span>
              {currentRun.pending_questions.length > 0 && (
                <span className="tab-badge-amber">{currentRun.pending_questions.length}</span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('discussion')}
              className={`nav-tab ${activeTab === 'discussion' ? 'tab-active' : ''}`}
            >
              <MessageSquare size={15} />
              <span>{t('tab_discussion')} ({events.length})</span>
            </button>

            <button
              onClick={() => setActiveTab('issues')}
              className={`nav-tab ${activeTab === 'issues' ? 'tab-active' : ''}`}
            >
              <AlertOctagon size={15} />
              <span>{t('tab_issues')} ({issues.length})</span>
            </button>

            <button
              onClick={() => setActiveTab('decisions')}
              className={`nav-tab ${activeTab === 'decisions' ? 'tab-active' : ''}`}
            >
              <Compass size={15} />
              <span>{t('tab_decisions')} ({decisions.length})</span>
            </button>

            <button
              onClick={() => setActiveTab('evidence')}
              className={`nav-tab ${activeTab === 'evidence' ? 'tab-active' : ''}`}
            >
              <FileSearch size={15} />
              <span>{t('tab_evidence')} ({evidence.length})</span>
            </button>

            <button
              onClick={() => setActiveTab('plan')}
              className={`nav-tab ${activeTab === 'plan' ? 'tab-active' : ''}`}
            >
              <GitBranch size={15} />
              <span>{t('tab_plan')}</span>
            </button>

            <button
              onClick={() => setActiveTab('logs')}
              className={`nav-tab ${activeTab === 'logs' ? 'tab-active' : ''}`}
            >
              <Terminal size={15} />
              <span>{t('tab_logs')}</span>
              {currentRun.status === 'FAILED' && (
                <span className="tab-badge-rose">{t('tab_error_badge')}</span>
              )}
            </button>
          </nav>

          {/* Tab Views */}
          <div className="tab-content-area">
            {activeTab === 'overview' && (
              <RunOverview
                run={currentRun}
                onAnswerQuestion={handleAnswerQuestion}
                onResumeRun={handleResumeRun}
                onCancelRun={handleCancelRun}
                onValidate={handleValidate}
                onFinalize={handleFinalize}
                onExportMarkdown={() => handleExportMarkdown()}
                onExportJson={() => handleExportJson()}
                isProcessing={isLoading}
                actionMessage={actionMessage}
                onViewLogs={() => setActiveTab('logs')}
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
          onOpenNewRun={() => setIsNewRunOpen(true)}
          onRefresh={() => loadRuns()}
          isLoading={isLoading}
        />
      )}

      <NewRunModal
        isOpen={isNewRunOpen}
        onClose={() => setIsNewRunOpen(false)}
        onSubmit={handleCreateRun}
        isSubmitting={isSubmitting}
        error={errorMessage}
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
        onProviderChanged={() => {
          showFeedback('Active provider updated successfully.');
          if (selectedRunId) loadRunDetails(selectedRunId);
        }}
      />

      {isAuthModalOpen && (
        <AuthModal
          mode={authMode}
          onAuthenticated={() => {
            setIsAuthModalOpen(false);
            const params = new URLSearchParams(window.location.search);
            const runParam = params.get('run');
            loadRuns(runParam);
          }}
        />
      )}
    </div>
  );
};

export default App;
