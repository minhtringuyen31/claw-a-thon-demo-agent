import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { KeenIcon } from '@/components';
import { Container } from '@/components/container';
import {
  getRun, streamRun, deleteRun,
  AgentTraceEvent, InvestigationLogEntry,
  IngestEvent, AnomalyCheckEvent, FetchDataEvent,
  FinalizeEvent, PolicyOutputEvent, ActionOutputEvent,
  PatternAttempt, RunOut, RunStatus,
} from '@/services/apis/Agent';

const STATUS_CONFIG: Record<RunStatus, { label: string; color: string }> = {
  running: { label: 'Running', color: 'primary' },
  completed: { label: 'Completed', color: 'success' },
  failed: { label: 'Failed', color: 'danger' },
};

const PATTERN_STATUS_COLOR: Record<string, string> = {
  passed: 'success',
  candidate: 'warning',
  failed: 'danger',
  abandoned: 'secondary',
};

const ACTION_COLOR: Record<string, string> = {
  reject: 'danger',
  blacklist: 'danger',
  challenge: 'warning',
  monitor: 'info',
  whitelist_exclusion: 'primary',
  none: 'secondary',
};

const MetricBar = ({ label, value }: { label: string; value: number }) => (
  <div>
    <div className="flex justify-between text-xs text-gray-600 mb-1">
      <span>{label}</span>
      <span className="font-medium">{(value * 100).toFixed(1)}%</span>
    </div>
    <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
      <div
        className="h-full bg-primary rounded-full transition-all"
        style={{ width: `${Math.min(value * 100, 100)}%` }}
      />
    </div>
  </div>
);

const PatternCard = ({ p, index }: { p: PatternAttempt; index: number }) => (
  <div className="border border-gray-200 rounded-lg p-4">
    <div className="flex items-start justify-between gap-3 mb-3">
      <div className="flex items-center gap-2">
        <span className="size-6 rounded-full bg-gray-100 text-gray-600 text-xs font-semibold flex items-center justify-center shrink-0">
          {index + 1}
        </span>
        <p className="text-sm font-medium text-gray-800">{p.description}</p>
      </div>
      <span
        className={`badge badge-${PATTERN_STATUS_COLOR[p.status] ?? 'secondary'} badge-outline rounded-[30px] shrink-0`}
      >
        {p.status}
      </span>
    </div>

    {p.metrics && (
      <div className="grid grid-cols-2 gap-4 mb-3">
        <MetricBar label="Precision" value={p.metrics.precision} />
        <MetricBar label="Recall" value={p.metrics.recall} />
      </div>
    )}

    {p.metrics && (
      <div className="flex gap-4 text-xs text-gray-500">
        <span>Hit: <strong className="text-gray-700">{p.metrics.hit_count}</strong></span>
        <span>Flagged: <strong className="text-gray-700">{p.metrics.total_flagged}</strong></span>
        <span>Total fraud: <strong className="text-gray-700">{p.metrics.total_fraud}</strong></span>
      </div>
    )}
  </div>
);

// ─── Tool color helpers ───────────────────────────────────────────────────────

const TOOL_COLOR: Record<string, string> = {
  query_with_filters: 'primary',
  raw_sql:            'info',
  compute_metrics:    'success',
  get_schema:         'secondary',
  aggregate:          'primary',
};

// ─── Per-node trace step renderers ───────────────────────────────────────────

const TimelineRow = ({
  circle, color, isLast, children,
}: {
  circle: React.ReactNode;
  color: string;
  isLast: boolean;
  children: React.ReactNode;
}) => (
  <div className="flex gap-3">
    <div className="flex flex-col items-center shrink-0">
      <div className={`size-7 rounded-full flex items-center justify-center shrink-0 bg-${color}`}>
        {circle}
      </div>
      {!isLast && <div className="w-px flex-1 bg-gray-200 dark:bg-gray-700 my-1 min-h-[12px]" />}
    </div>
    <div className="flex-1 min-w-0 pb-4">{children}</div>
  </div>
);

const NodeLabel = ({ label, sublabel }: { label: string; sublabel?: string }) => (
  <div className="flex items-center gap-2 mb-1.5">
    <span className="text-[11px] font-bold text-gray-700 dark:text-gray-300 uppercase tracking-wide">{label}</span>
    {sublabel && <span className="text-[11px] text-gray-400">{sublabel}</span>}
  </div>
);

const IngestRow = ({ step, isLast }: { step: IngestEvent; isLast: boolean }) => (
  <TimelineRow circle={<span className="text-[9px] font-bold text-white">IN</span>} color="slate-400" isLast={isLast}>
    <NodeLabel label="Ingest" sublabel={step.severity ? `severity: ${step.severity}` : undefined} />
    <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed">{step.raw_summary || '—'}</p>
    {step.cases_count > 0 && (
      <span className="mt-1 inline-block text-[11px] text-gray-400">{step.cases_count} reported cases</span>
    )}
  </TimelineRow>
);

const AnomalyRow = ({ step, isLast }: { step: AnomalyCheckEvent; isLast: boolean }) => {
  const color = step.is_anomalous ? 'danger' : 'success';
  return (
    <TimelineRow
      circle={<KeenIcon icon={step.is_anomalous ? 'shield-cross' : 'shield-tick'} className="text-white text-[13px]" />}
      color={color}
      isLast={isLast}
    >
      <NodeLabel
        label="Anomaly Check"
        sublabel={`${step.is_anomalous ? 'ANOMALOUS' : 'NORMAL'} · ${(step.confidence * 100).toFixed(0)}% confidence`}
      />
      <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed mb-2">{step.reasoning}</p>
      {step.evidence.length > 0 && (
        <div className="flex flex-col gap-1">
          {step.evidence.map((ev, i) => (
            <div key={i} className="flex items-start gap-1.5 text-[11px] text-gray-500">
              <span className="text-gray-300 mt-0.5">▸</span>
              <span>{ev.observation}</span>
            </div>
          ))}
        </div>
      )}
    </TimelineRow>
  );
};

const FetchDataRow = ({ step, isLast }: { step: FetchDataEvent; isLast: boolean }) => (
  <TimelineRow circle={<span className="text-[9px] font-bold text-white">FD</span>} color="info" isLast={isLast}>
    <NodeLabel
      label="Fetch Data"
      sublabel={`${step.slices_count} slice${step.slices_count !== 1 ? 's' : ''}`}
    />
    {(step.window_start || step.window_end) && (
      <p className="text-[11px] text-gray-400 mb-1">
        {String(step.window_start).slice(0, 10)} → {String(step.window_end).slice(0, 10)}
      </p>
    )}
    {step.slice_keys.length > 0 && (
      <div className="flex flex-wrap gap-1 mt-1">
        {step.slice_keys.map((k) => (
          <span key={k} className="badge badge-light badge-outline text-[10px] font-mono rounded">{k}</span>
        ))}
      </div>
    )}
  </TimelineRow>
);

const InvestigationRow = ({ step, isLast }: { step: InvestigationLogEntry; isLast: boolean }) => {
  const toolColor = TOOL_COLOR[step.tool] ?? 'secondary';
  const fmtJson = (v: Record<string, unknown>, maxKeys = 4) => {
    const keys = Object.keys(v);
    const short: Record<string, unknown> = {};
    keys.slice(0, maxKeys).forEach((k) => { short[k] = v[k]; });
    try { return JSON.stringify(short, null, 2) + (keys.length > maxKeys ? '\n…' : ''); } catch { return String(v); }
  };
  return (
    <TimelineRow
      circle={<span className="text-[10px] font-bold text-white">{step.iteration}</span>}
      color={toolColor}
      isLast={isLast}
    >
      <div className="flex items-center gap-2 mb-2">
        <span className={`badge badge-${toolColor} badge-outline rounded-[30px] text-[11px] font-mono`}>{step.tool}</span>
        {step.hypothesis_being_tested && (
          <span className="text-[11px] text-gray-400 truncate max-w-[280px]" title={step.hypothesis_being_tested}>
            H: {step.hypothesis_being_tested}
          </span>
        )}
      </div>
      {step.plan_thought && (
        <div className="flex gap-2 mb-1.5">
          <span className="text-[11px] font-semibold text-blue-500 w-14 shrink-0 mt-0.5">Plan</span>
          <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed">{step.plan_thought}</p>
        </div>
      )}
      <details className="mb-1.5">
        <summary className="text-[11px] font-semibold text-violet-500 cursor-pointer select-none hover:opacity-80 flex items-center gap-1">
          <span className="w-14 shrink-0">Action</span>
          <span className="text-gray-400 font-normal font-mono truncate max-w-[200px]">
            {Object.keys(step.args)[0] ? `${Object.keys(step.args)[0]}: ${String(Object.values(step.args)[0]).slice(0, 40)}…` : '{}'}
          </span>
        </summary>
        <pre className="mt-1 ml-16 p-2 bg-gray-50 dark:bg-gray-800 rounded-lg text-[11px] font-mono text-gray-600 dark:text-gray-400 overflow-x-auto whitespace-pre-wrap max-h-28">
          {fmtJson(step.args)}
        </pre>
      </details>
      <details>
        <summary className="text-[11px] font-semibold text-emerald-500 cursor-pointer select-none hover:opacity-80 flex items-center gap-1">
          <span className="w-14 shrink-0">Observe</span>
          <span className="text-gray-400 font-normal truncate max-w-[200px]">
            {Object.keys(step.observation).slice(0, 2).join(', ')}
          </span>
        </summary>
        <pre className="mt-1 ml-16 p-2 bg-gray-50 dark:bg-gray-800 rounded-lg text-[11px] font-mono text-gray-600 dark:text-gray-400 overflow-x-auto whitespace-pre-wrap max-h-28">
          {fmtJson(step.observation)}
        </pre>
      </details>
      {step.next_thought && (
        <div className="flex gap-2 mt-1.5">
          <span className="text-[11px] font-semibold text-amber-500 w-14 shrink-0 mt-0.5">Next</span>
          <p className="text-xs text-gray-500 italic leading-relaxed">{step.next_thought}</p>
        </div>
      )}
    </TimelineRow>
  );
};

const FinalizeRow = ({ step, isLast }: { step: FinalizeEvent; isLast: boolean }) => {
  const color = step.stop_reason === 'converged' ? 'success' : step.stop_reason === 'max_iter' ? 'warning' : 'secondary';
  return (
    <TimelineRow
      circle={<KeenIcon icon="check" className="text-white text-[13px]" />}
      color={color}
      isLast={isLast}
    >
      <NodeLabel label="Finalize" sublabel={`${step.stop_reason} · ${step.iteration_count} iterations`} />
      <span className={`text-[11px] ${step.has_final_pattern ? 'text-success' : 'text-gray-400'}`}>
        {step.has_final_pattern ? 'Pattern found ✓' : 'No pattern found'}
      </span>
    </TimelineRow>
  );
};

const PolicyOutputRow = ({ step, isLast }: { step: PolicyOutputEvent; isLast: boolean }) => (
  <TimelineRow circle={<KeenIcon icon="document" className="text-white text-[13px]" />} color="primary" isLast={isLast}>
    <NodeLabel label="Policy Output" sublabel={step.status} />
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-[11px] font-mono text-gray-700 dark:text-gray-300">{step.rule_name}</span>
      <span className={`badge badge-${ACTION_COLOR[step.recommended_action] ?? 'secondary'} badge-outline rounded-[30px] text-[10px]`}>
        {step.recommended_action}
      </span>
    </div>
    {step.metrics && (
      <div className="flex gap-3 mt-1 text-[11px] text-gray-500">
        <span>P: <strong className="text-gray-700">{(step.metrics.precision * 100).toFixed(0)}%</strong></span>
        <span>R: <strong className="text-gray-700">{(step.metrics.recall * 100).toFixed(0)}%</strong></span>
      </div>
    )}
  </TimelineRow>
);

const ActionOutputRow = ({ step, isLast }: { step: ActionOutputEvent; isLast: boolean }) => (
  <TimelineRow circle={<KeenIcon icon="check-circle" className="text-white text-[13px]" />} color="success" isLast={isLast}>
    <NodeLabel label="No Action Required" />
    <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed">{step.recommendation}</p>
  </TimelineRow>
);

const TraceStep = ({ step, isLast }: { step: AgentTraceEvent; isLast: boolean }) => {
  if ('node' in step) {
    if (step.node === 'ingest')               return <IngestRow step={step} isLast={isLast} />;
    if (step.node === 'anomaly_check')        return <AnomalyRow step={step} isLast={isLast} />;
    if (step.node === 'fetch_data')           return <FetchDataRow step={step} isLast={isLast} />;
    if (step.node === 'finalize_investigation') return <FinalizeRow step={step} isLast={isLast} />;
    if (step.node === 'policy_output')        return <PolicyOutputRow step={step} isLast={isLast} />;
    if (step.node === 'action_output')        return <ActionOutputRow step={step} isLast={isLast} />;
  }
  return <InvestigationRow step={step as InvestigationLogEntry} isLast={isLast} />;
};

// ─── Agent Step Log ───────────────────────────────────────────────────────────

const AgentStepLog = ({ runId, autoScroll = true }: { runId: string; autoScroll?: boolean }) => {
  const [open, setOpen]           = useState(true);
  const [steps, setSteps]         = useState<AgentTraceEvent[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [done, setDone]           = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const bottomRef                 = useRef<HTMLDivElement>(null);
  const stopRef                   = useRef<(() => void) | null>(null);

  const start = () => {
    if (stopRef.current) stopRef.current();
    setSteps([]);
    setDone(false);
    setError(null);
    setStreaming(true);
    stopRef.current = streamRun(
      runId,
      (step) => setSteps((prev) => [...prev, step]),
      () => { setStreaming(false); setDone(true); },
      (err) => { setStreaming(false); setError(err.message); },
    );
  };

  useEffect(() => {
    start();
    return () => stopRef.current?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  useEffect(() => {
    if (open && streaming && autoScroll) {
      window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
    }
  }, [steps, open, streaming, autoScroll]);

  return (
    <div className="card">
      {/* Header */}
      <button
        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors rounded-t-xl"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="flex items-center gap-2.5">
          <KeenIcon icon="code" className="text-gray-500" />
          <span className="text-sm font-semibold text-gray-800 dark:text-white">Agent Trace</span>
          {streaming && (
            <span className="flex items-center gap-1.5 text-[11px] text-primary font-medium">
              <span className="size-1.5 rounded-full bg-primary animate-pulse" />
              Streaming…
            </span>
          )}
          {done && steps.length > 0 && (
            <span className="text-[11px] text-gray-400">{steps.length} events</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {!streaming && (
            <span
              role="button"
              className="btn btn-xs btn-light"
              onClick={(e) => { e.stopPropagation(); start(); }}
            >
              <KeenIcon icon="arrows-circle" className="text-xs" />
              {!done && 'Start'}
            </span>
          )}
          <KeenIcon
            icon="down"
            className={`text-gray-400 transition-transform duration-200 ${open ? '' : '-rotate-90'}`}
          />
        </div>
      </button>

      {/* Body */}
      {open && (
        <div className="border-t border-gray-100 dark:border-gray-800 px-5 pb-5 pt-4">
          {error && (
            <div className="flex items-center gap-2 px-3 py-2 bg-danger-light border border-danger/20 rounded-lg text-xs text-danger mb-3">
              <KeenIcon icon="information-2" className="shrink-0" />
              <span>Can not connect SSE: <code className="font-mono">{error}</code></span>
              <button className="ms-auto btn btn-xs btn-clear btn-danger" onClick={start}>Retry</button>
            </div>
          )}

          {steps.length === 0 && !streaming && !error && (
            <div className="flex flex-col items-center justify-center py-10 gap-2 text-gray-400">
              <KeenIcon icon="code" className="text-3xl text-gray-200" />
              <p className="text-xs">No trace data is available</p>
            </div>
          )}

          <div className="flex flex-col gap-0">
            {steps.map((step, idx) => (
              <TraceStep key={idx} step={step} isLast={idx === steps.length - 1 && !streaming} />
            ))}

            {streaming && (
              <div className="flex gap-3 items-center py-1">
                {/* Animated avatar ring */}
                <div className="relative size-7 shrink-0">
                  <div className="absolute inset-0 rounded-full bg-primary/20 animate-ping" />
                  <div className="relative size-7 rounded-full bg-primary/10 flex items-center justify-center">
                    <svg className="size-3.5 animate-spin text-primary" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                      <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  </div>
                </div>
                {/* Typing dots + label */}
                <div className="flex items-center gap-2 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl rounded-tl-sm px-3 py-2">
                  <span className="text-xs text-gray-500 italic">Reasoning</span>
                  <span className="flex gap-0.5 items-end h-3">
                    <span className="w-1 h-1 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                    <span className="w-1 h-1 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                    <span className="w-1 h-1 rounded-full bg-gray-400 animate-bounce" style={{ animationDelay: '300ms' }} />
                  </span>
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        </div>
      )}
    </div>
  );
};

// ─── Main Page ────────────────────────────────────────────────────────────────

const InvestigationDetailPage = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [run, setRun] = useState<RunOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchRun = async () => {
    if (!id) return;
    try {
      const data = await getRun(id);
      setRun(data);
      setError(null);
      if (data.status !== 'running' && pollRef.current) {
        clearInterval(pollRef.current);
      }
    } catch {
      setError('Failed to load investigation. Check that the agent is running.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRun();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (run?.status === 'running') {
      pollRef.current = setInterval(fetchRun, 4000);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.status]);

  if (loading) {
    return (
      <Container>
        <div className="flex items-center justify-center min-h-[60vh] gap-3 text-gray-500">
          <span className="spinner-border spinner-border-sm" />
          Loading investigation...
        </div>
      </Container>
    );
  }

  if (error || !run) {
    return (
      <Container>
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <KeenIcon icon="information-2" className="text-5xl text-gray-300" />
        <p className="text-gray-500 text-sm">{error ?? 'Investigation not found.'}</p>
        <button className="btn btn-sm btn-light" onClick={() => navigate('/ai-investigation')}>
          <KeenIcon icon="arrow-left" className="me-1" /> Back to list
        </button>
      </div>
      </Container>
    );
  }

  const status = STATUS_CONFIG[run.status];
  const anomaly = run.anomaly_decision;
  const report = run.investigation_report;
  const ruleJson = run.rule_json;
  const noAction = run.no_action_report;

  return (
    <Container>
    <div className="grid gap-5 lg:gap-7.5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          className="btn btn-sm btn-icon btn-clear btn-light"
          onClick={() => navigate('/ai-investigation')}
        >
          <KeenIcon icon="arrow-left" />
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-lg font-semibold text-gray-900 truncate">
              {ruleJson?.description ?? noAction?.recommendation ?? `Run ${run.run_id}`}
            </h1>
            <span className={`badge badge-${status.color} badge-outline rounded-[30px]`}>
              {run.status === 'running' && (
                <span className={`size-1.5 rounded-full bg-${status.color} me-1.5 animate-pulse`} />
              )}
              {run.status !== 'running' && (
                <span className={`size-1.5 rounded-full bg-${status.color} me-1.5`} />
              )}
              {status.label}
            </span>
          </div>
          <p className="text-sm text-gray-400 font-mono mt-0.5">{run.run_id}</p>
        </div>
        <button
          className="btn btn-sm btn-icon btn-light"
          title="Refresh"
          onClick={fetchRun}
        >
          <KeenIcon icon="arrows-circle" />
        </button>
        <button
          className="btn btn-sm btn-icon btn-light-danger"
          title={run.status === 'running' ? 'Stop & delete run' : 'Delete run'}
          disabled={deleting}
          onClick={async () => {
            if (!confirm(`Delete run ${run.run_id}?`)) return;
            setDeleting(true);
            try {
              await deleteRun(run.run_id);
              navigate('/ai-investigation');
            } catch {
              setDeleting(false);
            }
          }}
        >
          {deleting
            ? <span className="spinner-border spinner-border-sm" />
            : <KeenIcon icon={run.status === 'running' ? 'stop' : 'trash'} />
          }
        </button>
      </div>

      {/* Running state */}
      {run.status === 'running' && (
        <div className="card p-5">
          <div className="flex items-center gap-3">
            <span className="spinner-border spinner-border-sm text-primary" />
            <div>
              <p className="text-sm font-medium text-gray-800">Agent is investigating...</p>
              <p className="text-xs text-gray-500 mt-0.5">
                The agent is analyzing and processing the data. This may take a few minutes.
              </p>
            </div>
          </div>
          {report && (
            <div className="mt-4 pt-4 border-t border-gray-100">
              <p className="text-xs text-gray-500 mb-2">
                Iteration {report.iteration_count} — patterns tested:{' '}
                {report.patterns_attempted.length}
              </p>
              <div className="flex flex-col gap-2">
                {report.patterns_attempted.slice(-3).map((p, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs text-gray-600">
                    <span
                      className={`size-2 rounded-full bg-${PATTERN_STATUS_COLOR[p.status] ?? 'gray-300'} shrink-0`}
                    />
                    {p.description}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 1 — Anomaly Detection */}
      {anomaly && (
        <div className="card p-5">
          <h3 className="text-base font-semibold text-gray-800 mb-4 flex items-center gap-2">
            <KeenIcon icon="shield-search" className="text-gray-500" />
            Anomaly Detection
          </h3>
          <div className="flex items-center gap-4 flex-wrap">
            <div
              className={`flex items-center gap-2 px-4 py-2.5 rounded-lg ${
                anomaly.is_anomalous
                  ? 'bg-danger-light text-danger'
                  : 'bg-success-light text-success'
              }`}
            >
              <KeenIcon
                icon={anomaly.is_anomalous ? 'shield-cross' : 'shield-tick'}
                className="text-xl"
              />
              <div>
                <p className="text-sm font-semibold">
                  {anomaly.is_anomalous ? 'Anomaly Detected' : 'No Anomaly'}
                </p>
                <p className="text-xs opacity-80">
                  Confidence: {(anomaly.confidence * 100).toFixed(0)}%
                </p>
              </div>
            </div>
            <p className="text-sm text-gray-600 flex-1">{anomaly.reasoning}</p>
          </div>
          {anomaly.evidence.length > 0 && (
            <div className="mt-4 pt-4 border-t border-gray-100 grid gap-2">
              {anomaly.evidence.map((ev, i) => (
                <div key={i} className="flex items-start gap-2 text-sm text-gray-600">
                  <KeenIcon icon="arrow-right" className="text-gray-400 mt-0.5 shrink-0" />
                  {ev.observation}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 2 — Pattern Attempts */}
      {report && report.patterns_attempted.length > 0 && (
        <div className="card p-5">
          <h3 className="text-base font-semibold text-gray-800 mb-1 flex items-center gap-2">
            <KeenIcon icon="graph-up" className="text-gray-500" />
            Pattern Attempts
            <span className="badge badge-light badge-outline rounded-full text-xs ml-1">
              {report.patterns_attempted.length}
            </span>
          </h3>
          <p className="text-xs text-gray-500 mb-4">
            Stop reason:{' '}
            <span className="font-medium text-gray-700">{report.stop_reason}</span>
          </p>
          <div className="flex flex-col gap-3">
            {report.patterns_attempted.map((p, i) => (
              <PatternCard key={i} p={p} index={i} />
            ))}
          </div>
        </div>
      )}

      {/* 3 — Final Recommendation */}
      {(report?.recommendation || noAction?.recommendation) && (
        <div className="card p-5">
          <h3 className="text-base font-semibold text-gray-800 mb-3 flex items-center gap-2">
            <KeenIcon icon="check-circle" className={noAction ? 'text-success' : 'text-primary'} />
            Final Recommendation
          </h3>
          <p className="text-sm text-gray-600 leading-relaxed">
            {report?.recommendation ?? noAction?.recommendation}
          </p>
        </div>
      )}

      {/* 4 — Generated Rule */}
      {ruleJson && (
        <div className="card p-5">
          <h3 className="text-base font-semibold text-gray-800 mb-4 flex items-center gap-2">
            <KeenIcon icon="document-up" className="text-gray-500" />
            Generated Rule
          </h3>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-5">
            <div className="p-3 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 mb-1">Rule Name</p>
              <p className="text-sm font-mono font-medium text-gray-800">{ruleJson.rule_name}</p>
            </div>
            <div className="p-3 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 mb-1">Fraud Type</p>
              <p className="text-sm font-medium text-gray-800">{ruleJson.fraud_type}</p>
            </div>
            <div className="p-3 bg-gray-50 rounded-lg">
              <p className="text-xs text-gray-500 mb-1">Recommended Action</p>
              <span
                className={`badge badge-${ACTION_COLOR[ruleJson.recommended_action] ?? 'secondary'} badge-outline rounded-[30px] text-xs mt-1`}
              >
                {ruleJson.recommended_action}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <p className="text-xs text-gray-500 mb-2">Metrics</p>
              <div className="flex flex-col gap-2">
                <MetricBar label="Precision" value={ruleJson.metrics.precision} />
                <MetricBar label="Recall" value={ruleJson.metrics.recall} />
              </div>
            </div>
            <div>
              <p className="text-xs text-gray-500 mb-2">Signal Columns</p>
              <div className="flex flex-wrap gap-1.5">
                {ruleJson.signal_columns.map((col) => (
                  <span key={col} className="badge badge-light badge-outline text-xs font-mono rounded">
                    {col}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 5 — Route to Config Agent */}
      {ruleJson && (
        <div className="card p-5 border-2 border-primary/20 bg-primary/5">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="flex items-center justify-center size-7 rounded-full bg-success text-white text-xs font-bold shrink-0">✓</span>
                <span className="text-sm text-gray-500">Investigation</span>
                <KeenIcon icon="arrow-right" className="text-gray-400 text-xs" />
                <span className="flex items-center justify-center size-7 rounded-full bg-primary text-white text-xs font-bold shrink-0">2</span>
                <span className="text-sm font-semibold text-gray-800">Configure &amp; Deploy Rule</span>
              </div>
              <p className="text-sm text-gray-500 hidden lg:block">
                Open the Config Agent to resolve dependencies, dry-run and deploy{' '}
                <span className="font-mono text-xs text-gray-700">{ruleJson.rule_name}</span> to the rule engine.
              </p>
            </div>
            <button
              className="btn btn-primary btn-sm shrink-0"
              onClick={() => navigate(`/ai-investigation/${run.run_id}/assistant`)}
            >
              Open Config Agent
              <KeenIcon icon="arrow-right" className="ms-1" />
            </button>
          </div>
        </div>
      )}

      {/* 6 — Agent Trace */}
      <AgentStepLog runId={run.run_id} autoScroll={run.status === 'running'} />

      {/* Pretty report markdown fallback */}
      {run.pretty_report && !ruleJson && !noAction && (
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
            <KeenIcon icon="document" className="text-gray-400" />
            Full Report
          </h3>
          <pre className="text-xs text-gray-600 whitespace-pre-wrap font-mono leading-relaxed">
            {run.pretty_report}
          </pre>
        </div>
      )}
    </div>
    </Container>
  );
};

export { InvestigationDetailPage };
