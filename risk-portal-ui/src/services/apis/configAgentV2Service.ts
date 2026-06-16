// Client for fraud-config-agent-v2 (FastAPI, default :8081).
// Distinct from configAgentService (the older :8001 agent) — v2 adds a
// human-review write gate: chat → awaiting_review → approve/reject → MySQL.

export const CONFIG_AGENT_V2_URL =
  (import.meta.env.VITE_CONFIG_AGENT_V2_URL as string | undefined) ?? 'http://localhost:8081';

export type V2Status =
  | 'clarify'
  | 'awaiting_review'
  | 'completed'
  | 'rejected'
  | 'running'
  | 'error';

export interface DedupInfo {
  found: boolean;
  event_name: string;
  rule_name: string;
}

export interface WriteResult {
  written: boolean;
  row_id?: number;
  target?: string;
  reason?: string;
}

export interface ChatV2Response {
  status: V2Status;
  run_id?: string;
  session_id?: string;
  question?: string;
  final_output?: object;
  operation?: 'create' | 'update';
  dedup?: DedupInfo;
  source_run_id?: string;
  message?: string;
}

export interface RunDetail {
  run_id: string;
  status: V2Status;
  source_type?: string;
  source_run_id?: string | null;
  operation?: 'create' | 'update';
  dedup?: DedupInfo;
  requirement?: object;
  final_output?: object;
  output_file?: string;
  write_result?: WriteResult;
}

export interface RunSummary {
  run_id: string;
  status: V2Status;
  source_type?: string;
  source_run_id?: string;
  session_id?: string;
  created_at?: string;
}

export interface ReviewResponse {
  run_id: string;
  status: V2Status;
  write_result?: WriteResult;
  output_file?: string;
}

async function postJson<T>(path: string, body: object): Promise<T> {
  const res = await fetch(`${CONFIG_AGENT_V2_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      detail = j.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json();
}

export const chatV2 = (
  message: string,
  sessionId?: string,
  clarificationAnswer = '',
): Promise<ChatV2Response> =>
  postJson('/chat', { message, session_id: sessionId, clarification_answer: clarificationAnswer });

export const runFromReport = (
  runId: string,
  sessionId?: string,
  fraudAgentUrl?: string,
): Promise<ChatV2Response> =>
  postJson('/runs/from-report', {
    run_id: runId,
    session_id: sessionId,
    fraud_agent_url: fraudAgentUrl,
  });

export const reviewRun = (
  runId: string,
  decision: 'approve' | 'reject',
  approvedBy = 'strategist',
): Promise<ReviewResponse> =>
  postJson(`/runs/${runId}/review`, { decision, approved_by: approvedBy });

export const getRunV2 = async (runId: string): Promise<RunDetail | null> => {
  try {
    const res = await fetch(`${CONFIG_AGENT_V2_URL}/runs/${runId}`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
};

export const listRunsV2 = async (): Promise<RunSummary[]> => {
  try {
    const res = await fetch(`${CONFIG_AGENT_V2_URL}/runs`);
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
};

// Deployed rules read from the DB (MySQL rule_config table).
// Each record = config of one event (event_name).
export interface DbRule {
  id: number;
  event_name: string;
  description: string;
  config: {
    name?: string;
    filter?: string;
    actionCode?: string;
    decisionCode?: string;
    variables?: unknown[];
    rules?: unknown[];
  };
  status?: number;
  source_run_id?: string | null;
  created_by?: string | null;
  created_at?: string | null;
}

export const listDbConfigs = async (): Promise<DbRule[]> => {
  try {
    const res = await fetch(`${CONFIG_AGENT_V2_URL}/rules`);
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
};
