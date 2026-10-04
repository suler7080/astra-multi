import type {
  CreateRunPayload,
  Decision,
  Evidence,
  FinalizeResult,
  Issue,
  PlanRevision,
  RunDetail,
  RunSummary,
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
  async listRuns(): Promise<RunSummary[]> {
    const res = await fetch(`${BASE_URL}/runs`);
    return handleResponse<RunSummary[]>(res);
  },

  async getRun(runId: string): Promise<RunDetail> {
    const res = await fetch(`${BASE_URL}/runs/${runId}`);
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
      headers,
      body: JSON.stringify(payload),
    });
    return handleResponse(res);
  },

  async getIssues(runId: string): Promise<Issue[]> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/issues`);
    return handleResponse<Issue[]>(res);
  },

  async getEvidence(runId: string): Promise<Evidence[]> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/evidence`);
    return handleResponse<Evidence[]>(res);
  },

  async getDecisions(runId: string): Promise<Decision[]> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/decisions`);
    return handleResponse<Decision[]>(res);
  },

  async getPlan(runId: string, revision: number): Promise<PlanRevision> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/plans/${revision}`);
    return handleResponse<PlanRevision>(res);
  },

  async answerQuestion(runId: string, questionId: string, answer: string, expectedRevision: number): Promise<{ message: string; question_id: string; status: string }> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/answers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
    });
    return handleResponse(res);
  },

  async cancelRun(runId: string, reason?: string): Promise<{ run_id: string; status: string; message: string }> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason || 'Cancelled by user' }),
    });
    return handleResponse(res);
  },

  async validateRun(runId: string): Promise<ValidationReport> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/validate`, {
      method: 'POST',
    });
    return handleResponse<ValidationReport>(res);
  },

  async finalizeRun(runId: string): Promise<FinalizeResult> {
    const res = await fetch(`${BASE_URL}/runs/${runId}/finalize`, {
      method: 'POST',
    });
    return handleResponse<FinalizeResult>(res);
  },

  async exportPlanMarkdown(runId: string, revision?: number): Promise<string> {
    const query = new URLSearchParams({ format: 'markdown' });
    if (revision) query.set('revision', String(revision));
    const res = await fetch(`${BASE_URL}/runs/${runId}/export?${query.toString()}`);
    if (!res.ok) {
      throw new Error(`Export failed: ${res.statusText}`);
    }
    return res.text();
  },

  async exportPlanJson(runId: string, revision?: number): Promise<Record<string, unknown>> {
    const query = new URLSearchParams({ format: 'json' });
    if (revision) query.set('revision', String(revision));
    const res = await fetch(`${BASE_URL}/runs/${runId}/export?${query.toString()}`);
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
