import agentInstance from '../agentInstance';

// ─── Domain types ────────────────────────────────────────────────────────────

export type RunStatus = 'running' | 'completed' | 'failed';
export type RecommendedAction =
  | 'monitor'
  | 'challenge'
  | 'reject'
  | 'blacklist'
  | 'whitelist_exclusion'
  | 'none';

export interface PatternMetrics {
  precision: number;
  recall: number;
  f1: number;
  hit_count: number;
  total_fraud: number;
  total_flagged: number;
}

export interface PatternAttempt {
  iteration: number;
  description: string;
  sql_predicate: string;
  signal_columns: string[];
  rationale: string;
  metrics: PatternMetrics | null;
  recommended_action: RecommendedAction;
  status: 'candidate' | 'passed' | 'failed' | 'abandoned';
  notes: string;
}

export interface InvestigationLogEntry {
  iteration: number;
  plan_thought: string;
  tool: string;
  args: Record<string, unknown>;
  hypothesis_being_tested: string | null;
  observation: Record<string, unknown>;
  next_thought: string;
}

// ─── Per-node trace events ────────────────────────────────────────────────────

export interface IngestEvent {
  node: 'ingest';
  raw_summary: string;
  severity: string;
  cases_count: number;
}

export interface AnomalyCheckEvent {
  node: 'anomaly_check';
  is_anomalous: boolean;
  confidence: number;
  reasoning: string;
  evidence: Array<{ filters: Record<string, unknown>; observation: string }>;
}

export interface FetchDataEvent {
  node: 'fetch_data';
  slices_count: number;
  slice_keys: string[];
  window_start: string;
  window_end: string;
}

export interface FinalizeEvent {
  node: 'finalize_investigation';
  stop_reason: string;
  iteration_count: number;
  has_final_pattern: boolean;
}

export interface PolicyOutputEvent {
  node: 'policy_output';
  rule_name: string;
  recommended_action: string;
  status: string;
  metrics: Record<string, number> | null;
}

export interface ActionOutputEvent {
  node: 'action_output';
  recommendation: string;
}

export type AgentTraceEvent =
  | IngestEvent
  | AnomalyCheckEvent
  | FetchDataEvent
  | FinalizeEvent
  | PolicyOutputEvent
  | ActionOutputEvent
  | InvestigationLogEntry;

export interface InvestigationReport {
  patterns_attempted: PatternAttempt[];
  final_pattern: PatternAttempt | null;
  stop_reason: 'converged' | 'max_iter' | 'no_pattern' | 'self_declared' | 'error';
  iteration_count: number;
  investigation_log: InvestigationLogEntry[];
  recommendation: string;
}

export interface AnomalyEvidence {
  filters: Record<string, unknown>;
  observation: string;
}

export interface AnomalyDecision {
  is_anomalous: boolean;
  confidence: number;
  reasoning: string;
  evidence: AnomalyEvidence[];
}

export interface NoActionReport {
  decision: AnomalyDecision;
  baseline_window: Record<string, unknown>;
  reported_summary: Record<string, unknown>;
  baseline_summary: Record<string, unknown>;
  recommendation: string;
  emitted_at: string;
}

export interface RuleJSON {
  rule_name: string;
  fraud_type: string;
  sql_predicate: string;
  description: string;
  signal_columns: string[];
  recommended_action: RecommendedAction;
  metrics: { precision: number; recall: number; f1: number };
  iteration_count: number;
  status: 'suggested' | 'no_action';
  emitted_at: string;
  source_run_id: string | null;
}

export interface RunOut {
  run_id: string;
  status: RunStatus;
  anomaly_decision: AnomalyDecision | null;
  investigation_window: Record<string, unknown> | null;
  investigation_report: InvestigationReport | null;
  no_action_report: NoActionReport | null;
  rule_json: RuleJSON | null;
  pretty_report: string | null;
}

// ─── Request payloads ────────────────────────────────────────────────────────

export interface CreateRunPayload {
  source_type: 'email' | 'postmortem';
  raw_input: string;
  min_precision?: number;
  min_recall?: number;
  max_iterations?: number;
}

export interface EmailTriggerPayload {
  subject?: string;
  sender?: string;
  body: string;
  min_precision?: number;
  min_recall?: number;
  max_iterations?: number;
}

export interface PostmortemTriggerPayload {
  incident_id?: string;
  summary?: string;
  record?: Record<string, unknown>;
  min_precision?: number;
  min_recall?: number;
  max_iterations?: number;
}

// ─── API functions ────────────────────────────────────────────────────────────

export const listRuns = async (): Promise<string[]> => {
  const res = await agentInstance.get<string[]>('/runs');
  return res.data;
};

export const getRun = async (runId: string): Promise<RunOut> => {
  const res = await agentInstance.get<RunOut>(`/runs/${runId}`);
  return res.data;
};

export const deleteRun = async (runId: string): Promise<void> => {
  await agentInstance.delete(`/runs/${runId}`);
};

export const createRun = async (payload: CreateRunPayload): Promise<RunOut> => {
  const res = await agentInstance.post<RunOut>('/runs', payload);
  return res.data;
};

export const triggerEmail = async (payload: EmailTriggerPayload): Promise<RunOut> => {
  const res = await agentInstance.post<RunOut>('/triggers/email', payload);
  return res.data;
};

export const triggerPostmortem = async (payload: PostmortemTriggerPayload): Promise<RunOut> => {
  const res = await agentInstance.post<RunOut>('/triggers/postmortem', payload);
  return res.data;
};

export const healthCheck = async (): Promise<boolean> => {
  try {
    await agentInstance.get('/health');
    return true;
  } catch {
    return false;
  }
};

export const streamRun = (
  runId: string,
  onStep: (step: AgentTraceEvent) => void,
  onDone?: () => void,
  onError?: (err: Error) => void,
): (() => void) => {
  const baseUrl = (agentInstance.defaults.baseURL ?? 'http://localhost:8000').replace(/\/$/, '');
  const url = `${baseUrl}/runs/${runId}/stream`;
  const ctrl = new AbortController();

  const headers: Record<string, string> = { Accept: 'text/event-stream' };
  const auth = agentInstance.defaults.headers?.common?.['Authorization'];
  if (auth) headers['Authorization'] = String(auth);

  (async () => {
    try {
      const res = await fetch(url, { headers, signal: ctrl.signal });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        const lines = buf.split('\n');
        buf = lines.pop() ?? '';

        let eventName = 'message';
        for (const line of lines) {
          if (line.startsWith('event:')) {
            eventName = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            const raw = line.slice(5).trim();
            if (eventName === 'done') { onDone?.(); return; }
            try { onStep(JSON.parse(raw) as InvestigationLogEntry); } catch { /* skip */ }
            eventName = 'message';
          } else if (line === '') {
            eventName = 'message';
          }
        }
      }
      onDone?.();
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        onError?.(err as Error);
        onDone?.();
      }
    }
  })();

  return () => ctrl.abort();
};
