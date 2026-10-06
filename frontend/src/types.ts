export interface Requirement {
  id: string;
  text: string;
  acceptance: string;
}

export interface RunSummary {
  run_id: string;
  goal: string;
  phase: string;
  status: string;
  revision: number;
  created_at: string;
  stop_reason?: string | null;
}

export interface Question {
  id: string;
  run_id: string;
  text: string;
  blocking: boolean;
  requirement_ids: string[];
  answer?: string | null;
  answered_by?: string | null;
  answered_at?: string | null;
}

export interface RunDetail {
  run_id: string;
  task_id: string;
  task_revision: number;
  goal: string;
  requirements: Requirement[];
  phase: string;
  status: string;
  revision: number;
  created_at: string;
  stop_reason?: string | null;
  plan_revision?: number | null;
  plans_count: number;
  issues_count: number;
  blocking_issues_count: number;
  decisions_count: number;
  evidence_count: number;
  pending_questions: Question[];
}

export interface Issue {
  id: string;
  run_id: string;
  severity: 'blocking' | 'warning' | 'info';
  status: 'OPEN' | 'RESOLVED' | 'REJECTED' | 'DUPLICATE';
  based_on_revision: number;
  claim: string;
  impact: string;
  verification_request?: string | null;
  suggested_resolution: string;
  requirement_ids: string[];
  evidence_ids: string[];
}

export interface Decision {
  id: string;
  run_id: string;
  question: string;
  chosen: string;
  rationale: string;
  alternatives: string[];
  evidence_ids: string[];
  related_issues: string[];
}

export interface Evidence {
  id: string;
  run_id: string;
  source_type: 'repo' | 'tool' | 'document' | 'user';
  locator: string;
  content_hash: string;
  captured_at: string;
  snapshot_id?: string | null;
  tool_call_id?: string | null;
  status: 'NOT_RUN' | 'PASS' | 'FAIL';
}

export interface PlanStep {
  id: string;
  objective: string;
  requirement_ids: string[];
  dependencies: string[];
  targets: string[];
  validation: string;
  deliverables: string[];
  completion_criteria: string[];
  evidence_ids: string[];
}

export interface PlanRevision {
  id: string;
  run_id: string;
  revision: number;
  based_on_revision: number;
  requirements_revision: number;
  snapshot_id?: string | null;
  steps: PlanStep[];
  decisions: Decision[];
  risks: string[];
}

export interface Violation {
  rule_id: string;
  severity: string;
  entity: string;
  message: string;
  remediation: string;
}

export interface ValidationReport {
  passed: boolean;
  plan_revision: number;
  task_revision: number;
  violations: Violation[];
  uncovered_requirements: string[];
  unresolved_blocking_issues: string[];
}

export interface FinalizeResult {
  run_id: string;
  status: string;
  can_finalize: boolean;
  blockers: string[];
}

export interface CreateRunPayload {
  goal: string;
  requirements: string[];
  mode?: 'greenfield' | 'repo';
  token_limit?: number;
  cost_limit?: number;
  call_limit?: number;
  max_rounds?: number;
  idempotency_key?: string;
}

export interface StreamEvent {
  id: number;
  event: string;
  data: {
    id?: string;
    sequence?: number;
    type?: string;
    actor?: string;
    timestamp?: string;
    payload?: Record<string, unknown>;
    status?: string;
    phase?: string;
    stop_reason?: string;
  };
}

export interface RunLogEntry {
  id: string;
  timestamp: string;
  level: 'INFO' | 'WARN' | 'ERROR' | 'DEBUG';
  node: string;
  message: string;
  details?: Record<string, unknown> | null;
}

export interface AuthStatus {
  setup_required: boolean;
  authenticated: boolean;
}

export interface ProviderItem {
  name: string;
  kind: 'openai' | 'google' | 'openai-compatible';
  base_url?: string | null;
  model: string;
  has_api_key: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SaveProviderPayload {
  name: string;
  kind: 'openai' | 'google' | 'openai-compatible';
  base_url?: string | null;
  model: string;
  api_key?: string;
  is_active?: boolean;
}

export interface TestProviderPayload {
  name?: string;
  kind: 'openai' | 'google' | 'openai-compatible';
  base_url?: string | null;
  model: string;
  api_key?: string;
}

export interface TestProviderResult {
  success: boolean;
  latency_ms?: number;
  error?: string;
}


