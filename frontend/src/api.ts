import type {
  AuthStatus,
  CreateRunPayload,
  Decision,
  Evidence,
  FinalizeResult,
  Issue,
  PlanRevision,
  ProviderItem,
  RunDetail,
  RunLogEntry,
  RunSummary,
  SaveProviderPayload,
  TestProviderPayload,
  TestProviderResult,
  ValidationReport,
} from './types';

const BASE_URL = import.meta.env.VITE_API_BASE || '/api';

export class ApiError extends Error {
  code: string;
  status: number;
  correlationId?: string;

  constructor(status: number, message: string, code: string = 'api_error', correlationId?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.correlationId = correlationId;
  }
}

function getAuthHeaders(extraHeaders: Record<string, string> = {}): Record<string, string> {
  const token = localStorage.getItem('astra_auth_token');
  const headers: Record<string, string> = { ...extraHeaders };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errCode = 'unknown_error';
    let errMsg = res.statusText;
    let correlationId: string | undefined;

    try {
      const errJson = await res.json();
      if (errJson.error) {
        errCode = errJson.error.code || errCode;
        errMsg = errJson.error.message || errMsg;
        correlationId = errJson.error.correlation_id;
      } else if (errJson.detail) {
        errMsg = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
      }
    } catch {
      // response is not JSON
    }
    throw new ApiError(res.status, errMsg, errCode, correlationId);
  }
  return res.json();
}

export const api = {
  // Auth APIs
  async getAuthStatus(): Promise<AuthStatus> {
    const res = await fetch(`${BASE_URL}/auth/status`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<AuthStatus>(res);
  },

  async setupAdmin(password: string): Promise<{ token: string }> {
    const res = await fetch(`${BASE_URL}/auth/setup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    const data = await handleResponse<{ token: string }>(res);
    localStorage.setItem('astra_auth_token', data.token);
    return data;
  },

  async login(password: string): Promise<{ token: string }> {
    const res = await fetch(`${BASE_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    const data = await handleResponse<{ token: string }>(res);
    localStorage.setItem('astra_auth_token', data.token);
    return data;
  },

  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    const res = await fetch(`${BASE_URL}/auth/change-password`, {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
    await handleResponse(res);
  },

  logout(): void {
    localStorage.removeItem('astra_auth_token');
  },

  // Settings & Provider APIs
  async listProviders(): Promise<ProviderItem[]> {
    const res = await fetch(`${BASE_URL}/settings/providers`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<ProviderItem[]>(res);
  },

  async saveProvider(payload: SaveProviderPayload): Promise<ProviderItem> {
    const res = await fetch(`${BASE_URL}/settings/providers`, {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    return handleResponse<ProviderItem>(res);
  },

  async deleteProvider(name: string): Promise<void> {
    const res = await fetch(`${BASE_URL}/settings/providers/${encodeURIComponent(name)}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });
    await handleResponse(res);
  },

  async activateProvider(name: string): Promise<{ success: boolean; active_provider: string }> {
    const res = await fetch(`${BASE_URL}/settings/providers/${encodeURIComponent(name)}/activate`, {
      method: 'POST',
      headers: getAuthHeaders(),
    });
    return handleResponse<{ success: boolean; active_provider: string }>(res);
  },

  async testProvider(payload: TestProviderPayload): Promise<TestProviderResult> {
    const res = await fetch(`${BASE_URL}/settings/providers/test`, {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    return handleResponse<TestProviderResult>(res);
  },

  // Runs APIs
  async listRuns(): Promise<RunSummary[]> {
    const res = await fetch(`${BASE_URL}/runs`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<RunSummary[]>(res);
  },

  async getRun(runId: string): Promise<RunDetail> {
    const res = await fetch(`${BASE_URL}/runs/${runId}`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<RunDetail>(res);
  },

  async createRun(payload: CreateRunPayload, idempotencyKey?: string): Promise<{ run_id: string; status: string; phase: string; message: string }> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (idempotencyKey) {
      headers['Idempotency-Key'] = idempotencyKey;
    }
    const res = await fetch(`${BASE_URL}/runs`, {
      method: 'POST',
      headers: getAuthHeaders(headers),
      body: JSON.stringify(payload),
    });
    return handleResponse(res);
  },

  async getIssues(runId: string): Promise<Issue[]> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/issues`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<Issue[]>(res);
  },

  async getEvidence(runId: string): Promise<Evidence[]> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/evidence`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<Evidence[]>(res);
  },

  async getDecisions(runId: string): Promise<Decision[]> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/decisions`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<Decision[]>(res);
  },

  async getPlan(runId: string, revision: number): Promise<PlanRevision> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/plans/${revision}`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<PlanRevision>(res);
  },

  async getRunLogs(runId: string): Promise<RunLogEntry[]> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/logs`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<RunLogEntry[]>(res);
  },

  async answerQuestion(runId: string, questionId: string, answer: string, expectedRevision: number): Promise<{ message: string; question_id: string; status: string }> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/answers`, {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        question_id: questionId,
        answer,
        expected_revision: expectedRevision,
      }),
    });
    return handleResponse(res);
  },

  async resumeRun(runId: string): Promise<{ run_id: string; status: string; message: string }> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/resume`, {
      method: 'POST',
      headers: getAuthHeaders(),
    });
    return handleResponse(res);
  },

  async cancelRun(runId: string, reason?: string): Promise<{ run_id: string; status: string; message: string }> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/cancel`, {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ reason: reason || 'Cancelled by user' }),
    });
    return handleResponse(res);
  },

  async validateRun(runId: string): Promise<ValidationReport> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/validate`, {
      method: 'POST',
      headers: getAuthHeaders(),
    });
    return handleResponse<ValidationReport>(res);
  },

  async finalizeRun(runId: string): Promise<FinalizeResult> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/finalize`, {
      method: 'POST',
      headers: getAuthHeaders(),
    });
    return handleResponse<FinalizeResult>(res);
  },

  async exportPlanMarkdown(runId: string, revision?: number): Promise<string> {
    const query = new URLSearchParams({ format: 'markdown' });
    if (revision) query.set('revision', String(revision));
    const res = await fetch(`${BASE_URL}/runs/${runId}/export?${query.toString()}`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      throw new Error(`Export failed: ${res.statusText}`);
    }
    return res.text();
  },

  async exportPlanJson(runId: string, revision?: number): Promise<Record<string, unknown>> {
    const query = new URLSearchParams({ format: 'json' });
    if (revision) query.set('revision', String(revision));
    const res = await fetch(`${BASE_URL}/runs/${runId}/export?${query.toString()}`, {
      headers: getAuthHeaders(),
    });
    return handleResponse<Record<string, unknown>>(res);
  },

  getEventSourceUrl(runId: string, lastEventId?: number): string {
    const url = new URL(`${BASE_URL}/runs/${runId}/events`, window.location.origin);
    if (lastEventId) {
      url.searchParams.set('last_event_id', String(lastEventId));
    }
    return url.pathname + url.search;
  },
};
