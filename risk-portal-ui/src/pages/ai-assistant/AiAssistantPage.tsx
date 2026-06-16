import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { KeenIcon } from '@/components';
import { Container } from '@/components/container';
import { getRun, RuleJSON, PatternAttempt } from '@/services/apis/Agent';
import { chatWithConfigAgent, ConfigAgentChatResponse } from '@/services/apis/configAgentService';
import { reviewRun } from '@/services/apis/configAgentV2Service';

// ─── Types ────────────────────────────────────────────────────────────────────

type UIState = 'confirm' | 'generating' | 'clarifying' | 'confirm_deploy' | 'deployed' | 'done';

type MsgRole = 'system' | 'user' | 'assistant' | 'config_preview' | 'hitl';

interface HitlDetail {
  label: string;
  value: string;
  status?: 'new' | 'reuse' | 'warn' | 'ok';
}

interface Msg {
  id: string;
  role: MsgRole;
  content: string;
  hitlTitle?: string;
  hitlDetails?: HitlDetail[];
  hitlApproved?: boolean | null;
  isThinking?: boolean;
  timestamp: Date;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

let _id = 0;
const uid = () => `m${++_id}`;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ─── Thinking animation ───────────────────────────────────────────────────────

const ThinkingBubble = ({ label = 'Generating config…' }: { label?: string }) => (
  <div className="flex gap-3 mb-3">
    <div className="relative size-7 shrink-0 mt-0.5">
      <div className="absolute inset-0 rounded-full bg-primary/20 animate-ping" />
      <div className="size-7 rounded-full bg-primary/10 flex items-center justify-center relative">
        <KeenIcon icon="robot" className="text-primary text-[11px]" />
      </div>
    </div>
    <div className="flex items-center gap-3 bg-white dark:bg-gray-800 border border-primary/25 rounded-2xl rounded-tl-sm px-4 py-2.5 shadow-sm shadow-primary/10">
      <svg className="size-3.5 animate-spin text-primary shrink-0" viewBox="0 0 24 24" fill="none">
        <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
        <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      <span className="text-sm text-gray-400">{label}</span>
    </div>
  </div>
);

// ─── Config preview ───────────────────────────────────────────────────────────

const ConfigPreview = ({ content }: { content: string }) => {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="flex gap-3 mb-3">
      <div className="size-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
        <KeenIcon icon="robot" className="text-primary text-[11px]" />
      </div>
      <div className="flex-1 max-w-[85%] border border-primary/20 rounded-2xl rounded-tl-sm overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 bg-primary/5 border-b border-primary/15">
          <span className="text-xs font-semibold text-primary/80">Generated Config</span>
          <button onClick={copy} className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors">
            <KeenIcon icon={copied ? 'check' : 'copy'} className="text-xs" />
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
        <pre className="px-4 py-3 bg-white dark:bg-gray-900 text-xs font-mono text-gray-700 dark:text-gray-300 overflow-x-auto whitespace-pre-wrap leading-relaxed max-h-96">
          {content}
        </pre>
      </div>
    </div>
  );
};

// ─── HITL confirm card ────────────────────────────────────────────────────────

const STATUS_STYLE: Record<string, string> = {
  new:   'text-primary bg-primary/10',
  reuse: 'text-success bg-success/10',
  warn:  'text-warning bg-warning/10',
  ok:    'text-success bg-success/10',
};

const HitlCard = ({
  msg, onApprove, onRequestChange, approveLabel = 'Confirm',
}: {
  msg: Msg;
  onApprove: () => void;
  onRequestChange?: () => void;
  approveLabel?: string;
}) => {
  if (msg.hitlApproved === true) {
    return (
      <div className="flex gap-3 mb-4">
        <div className="size-7 shrink-0" />
        <div className="flex items-center gap-2 px-4 py-2.5 bg-success/10 border border-success/25 rounded-2xl text-sm text-success">
          <KeenIcon icon="check-circle" />
          <span className="font-medium">{msg.hitlTitle} — Confirmed</span>
        </div>
      </div>
    );
  }

  if (msg.hitlApproved === false) {
    return (
      <div className="flex gap-3 mb-4">
        <div className="size-7 shrink-0" />
        <div className="flex items-center gap-2 px-4 py-2.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl text-sm text-gray-500">
          <KeenIcon icon="message-edit" />
          <span>Changes requested — describe what to modify below.</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3 mb-4">
      <div className="size-7 rounded-full bg-warning/10 flex items-center justify-center shrink-0 mt-0.5">
        <KeenIcon icon="user" className="text-warning text-[11px]" />
      </div>
      <div className="flex-1 max-w-[90%] border-2 border-warning/30 rounded-2xl rounded-tl-sm overflow-hidden bg-white dark:bg-gray-800 shadow-sm">
        <div className="flex items-center gap-2 px-4 py-2.5 bg-warning/5 border-b border-warning/20">
          <KeenIcon icon="information-2" className="text-warning text-sm" />
          <span className="text-sm font-semibold text-gray-800 dark:text-white">{msg.hitlTitle}</span>
          <span className="ms-auto text-xs text-warning font-medium uppercase tracking-wide">Awaiting review</span>
        </div>
        {msg.hitlDetails && msg.hitlDetails.length > 0 && (
          <div className="px-4 pt-3">
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden mb-3">
              <table className="w-full text-xs">
                <tbody>
                  {msg.hitlDetails.map((d, i) => (
                    <tr key={i} className={i % 2 === 0 ? 'bg-gray-50 dark:bg-gray-700/30' : 'bg-white dark:bg-transparent'}>
                      <td className="px-3 py-2 text-gray-500 font-medium w-36 shrink-0">{d.label}</td>
                      <td className="px-3 py-2 text-gray-800 dark:text-gray-200 font-mono flex-1">{d.value}</td>
                      {d.status && (
                        <td className="px-3 py-2 text-right">
                          <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${STATUS_STYLE[d.status] ?? ''}`}>
                            {d.status}
                          </span>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        <div className="flex gap-2 px-4 py-3 bg-gray-50 dark:bg-gray-700/30 border-t border-gray-200 dark:border-gray-700">
          <button className="btn btn-sm btn-success flex-1" onClick={onApprove}>
            <KeenIcon icon="check" /> {approveLabel}
          </button>
          {onRequestChange && (
            <button className="btn btn-sm btn-light flex-1" onClick={onRequestChange}>
              <KeenIcon icon="message-edit" /> Request Changes
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

// ─── Message bubbles ──────────────────────────────────────────────────────────

const InlineCode = ({ text }: { text: string }) => {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return (
    <>
      {parts.map((p, i) => {
        if (p.startsWith('**') && p.endsWith('**')) return <strong key={i}>{p.slice(2, -2)}</strong>;
        if (p.startsWith('`') && p.endsWith('`')) return <code key={i} className="font-mono text-[0.8em] bg-gray-100 dark:bg-gray-700 px-1 py-0.5 rounded">{p.slice(1, -1)}</code>;
        return <span key={i}>{p}</span>;
      })}
    </>
  );
};

const AssistantBubble = ({ content }: { content: string }) => {
  let inCode = false;
  const codeAcc: string[] = [];
  const els: React.ReactNode[] = [];
  let key = 0;
  const flushCode = () => {
    if (codeAcc.length) {
      els.push(<pre key={key++} className="my-2 p-3 bg-gray-50 dark:bg-gray-900 rounded-xl font-mono text-xs text-gray-700 dark:text-gray-300 overflow-x-auto whitespace-pre-wrap">{codeAcc.join('\n')}</pre>);
      codeAcc.length = 0;
    }
  };
  for (const line of content.split('\n')) {
    if (line.startsWith('```')) { inCode ? (flushCode(), inCode = false) : (inCode = true); continue; }
    if (inCode) { codeAcc.push(line); continue; }
    if (line === '') { els.push(<div key={key++} className="h-2" />); continue; }
    els.push(<div key={key++} className="leading-relaxed"><InlineCode text={line} /></div>);
  }
  flushCode();
  return (
    <div className="flex gap-3 mb-3">
      <div className="size-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
        <KeenIcon icon="robot" className="text-primary text-[11px]" />
      </div>
      <div className="flex-1 max-w-[85%] bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-gray-800 dark:text-gray-200">
        {els}
      </div>
    </div>
  );
};

const UserBubble = ({ content }: { content: string }) => (
  <div className="flex justify-end mb-3">
    <div className="max-w-[70%] bg-primary text-white rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm leading-relaxed">{content}</div>
  </div>
);

const SystemMsg = ({ content }: { content: string }) => (
  <div className="flex justify-center my-3">
    <span className="text-xs text-gray-400 bg-gray-100 dark:bg-gray-800 px-3 py-1 rounded-full">{content}</span>
  </div>
);

// ─── Build config-agent input from pattern ─────────────────────────────────────

const buildConfigInput = (pattern: PatternAttempt, rule: RuleJSON | null, recommendation: string): string => {
  const action = pattern.recommended_action.toUpperCase();
  const sql = pattern.sql_predicate.toLowerCase();
  const event = sql.includes('trans_log') || sql.includes('transaction') ? 'transaction'
    : sql.includes('payment') ? 'payment'
    : sql.includes('transfer') ? 'transfer'
    : 'transaction';
  return [
    `Tạo fraud rule cho event: ${event}`,
    rule?.fraud_type ? `Loại gian lận: ${rule.fraud_type}` : '',
    `Pattern description: ${pattern.description}`,
    pattern.sql_predicate ? `SQL predicate (use this for exact conditions): ${pattern.sql_predicate}` : '',
    `Signal columns: ${pattern.signal_columns.join(', ')}`,
    `Action: ${action}`,
    pattern.rationale ? `Lý do: ${pattern.rationale}` : '',
    recommendation ? `Recommendation: ${recommendation}` : '',
  ].filter(Boolean).join('\n');
};

// ─── Main Page ────────────────────────────────────────────────────────────────

const AiAssistantPage = () => {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();

  const [finalPattern, setFinalPattern] = useState<PatternAttempt | null>(null);
  const [recommendation, setRecommendation] = useState('');
  const [rule, setRule] = useState<RuleJSON | null>(null);
  const [loading, setLoading] = useState(true);
  const [uiState, setUiState] = useState<UIState>('confirm');
  const [messages, setMessages] = useState<Msg[]>([]);
  const [thinking, setThinking] = useState(false);
  const [thinkingLabel, setThinkingLabel] = useState('Generating config…');
  const [input, setInput] = useState('');
  const [hitlId, setHitlId] = useState<string | null>(null);
  const [deployHitlId, setDeployHitlId] = useState<string | null>(null);
  const [pendingConfig, setPendingConfig] = useState<object | null>(null);
  const [outputFile, setOutputFile] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [originalInput, setOriginalInput] = useState('');
  const [configRunId, setConfigRunId] = useState<string | undefined>(undefined);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const bootedRef = useRef(false);

  const push = useCallback((msg: Msg | Msg[]) => {
    setMessages(prev => [...prev, ...(Array.isArray(msg) ? msg : [msg])]);
  }, []);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  // ── Boot ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!runId || bootedRef.current) return;
    bootedRef.current = true;
    getRun(runId).then(run => {
      const ir = run.investigation_report;
      const pattern = ir?.final_pattern ?? null;
      const rec = ir?.recommendation ?? '';
      const ruleJson = run.rule_json ?? null;
      if (!pattern && !ruleJson) { setLoading(false); return; }

      const effectivePattern: PatternAttempt = pattern ?? {
        iteration: 0,
        description: ruleJson!.description,
        sql_predicate: ruleJson!.sql_predicate,
        signal_columns: ruleJson!.signal_columns,
        rationale: '',
        metrics: { ...ruleJson!.metrics, hit_count: 0, total_fraud: 0, total_flagged: 0 },
        recommended_action: ruleJson!.recommended_action,
        status: 'passed' as const,
        notes: '',
      };

      setFinalPattern(effectivePattern);
      setRecommendation(rec);
      setRule(ruleJson);
      setLoading(false);

      const metrics = effectivePattern.metrics ?? { precision: 0, recall: 0, f1: 0, hit_count: 0, total_fraud: 0, total_flagged: 0 };
      const fraudType = ruleJson?.fraud_type ?? 'fraud';
      const ruleName = ruleJson?.rule_name ?? effectivePattern.description.slice(0, 50);

      push({ id: uid(), role: 'system', content: `Investigation ${runId} — iteration ${effectivePattern.iteration}`, timestamp: new Date() });
      push({
        id: uid(), role: 'assistant', timestamp: new Date(),
        content: [
          `I've loaded the final pattern from investigation \`${runId}\`.`,
          '',
          `**Pattern:** ${effectivePattern.description}`,
          rec ? `**Recommendation:** ${rec}` : '',
          `**Action:** \`${effectivePattern.recommended_action}\``,
          `**Fraud type:** ${fraudType}`,
          `**Metrics:** Precision ${(metrics.precision * 100).toFixed(1)}% · Recall ${(metrics.recall * 100).toFixed(1)}% · F1 ${(metrics.f1 * 100).toFixed(1)}% · ${metrics.hit_count ?? 0} hits`,
          '',
          `Confirm to send this pattern to the Config Agent.`,
        ].filter(s => s !== undefined).join('\n'),
      });

      const hId = uid();
      setHitlId(hId);
      push({
        id: hId, role: 'hitl', content: '', hitlTitle: 'Generate Config from Pattern', hitlApproved: null,
        hitlDetails: [
          { label: 'Rule',       value: ruleName,                                    status: 'new' },
          { label: 'Fraud type', value: fraudType,                                   status: 'ok'  },
          { label: 'Action',     value: effectivePattern.recommended_action,         status: 'new' },
          { label: 'Precision',  value: `${(metrics.precision * 100).toFixed(1)}%`, status: 'ok'  },
          { label: 'Recall',     value: `${(metrics.recall * 100).toFixed(1)}%`,    status: 'ok'  },
          { label: 'F1',         value: `${(metrics.f1 * 100).toFixed(1)}%`,        status: 'ok'  },
          { label: 'Hit count',  value: String(metrics.hit_count ?? 0),              status: 'ok'  },
        ],
        timestamp: new Date(),
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  // ── Shared response handler ────────────────────────────────────────────────
  const handleAgentResponse = useCallback((response: ConfigAgentChatResponse) => {
    if (response.session_id) setSessionId(response.session_id);
    if (response.run_id) setConfigRunId(response.run_id);

    if ((response.status === 'done' || response.status === 'awaiting_review' || response.status === 'completed') && response.final_output) {
      const configJson = JSON.stringify(response.final_output, null, 2);
      setPendingConfig(response.final_output);
      if (response.output_file) setOutputFile(response.output_file);
      push({ id: uid(), role: 'assistant', content: 'Config generated. Review and confirm to save:', timestamp: new Date() });
      push({ id: uid(), role: 'config_preview', content: configJson, timestamp: new Date() });

      // Show deploy confirm card
      const dId = uid();
      setDeployHitlId(dId);
      push({
        id: dId, role: 'hitl', content: '', hitlTitle: 'Save Config to config-service',
        hitlApproved: null,
        hitlDetails: [
          { label: 'Target env', value: 'production',     status: 'warn' },
          { label: 'Operation',  value: 'create / update', status: 'new'  },
          { label: 'Rollback',   value: 'manual',          status: 'ok'   },
        ],
        timestamp: new Date(),
      });
      setUiState('confirm_deploy');
    } else if (response.status === 'clarify' && response.question) {
      push({ id: uid(), role: 'assistant', content: response.question, timestamp: new Date() });
      setUiState('clarifying');
    } else {
      push({ id: uid(), role: 'assistant', content: 'Unexpected response from config agent. Try again.', timestamp: new Date() });
      setUiState('done');
    }
  }, [push]);

  // ── Show thinking helper ───────────────────────────────────────────────────
  const withThinking = useCallback(async <T,>(label: string, fn: () => Promise<T>): Promise<T> => {
    const thinkId = uid();
    setThinkingLabel(label);
    setThinking(true);
    setMessages(prev => [...prev, { id: thinkId, role: 'assistant', content: '', isThinking: true, timestamp: new Date() }]);
    try {
      const result = await fn();
      setMessages(prev => prev.filter(m => m.id !== thinkId));
      setThinking(false);
      return result;
    } catch (err) {
      setMessages(prev => prev.filter(m => m.id !== thinkId));
      setThinking(false);
      throw err;
    }
  }, []);

  // ── Confirm: initial call to config agent ──────────────────────────────────
  const handleConfirm = useCallback(async () => {
    if (!finalPattern) return;
    setMessages(prev => prev.map(m => m.id === hitlId ? { ...m, hitlApproved: true } : m));
    setHitlId(null);
    setUiState('generating');

    const input = buildConfigInput(finalPattern, rule, recommendation);
    setOriginalInput(input);

    try {
      const response = await withThinking('Generating config…', () =>
        chatWithConfigAgent(input)
      );
      handleAgentResponse(response);
    } catch {
      push({ id: uid(), role: 'assistant', content: 'Failed to reach config agent. Check the endpoint and try again.', timestamp: new Date() });
      setUiState('done');
    }
  }, [finalPattern, rule, recommendation, hitlId, push, withThinking, handleAgentResponse]);

  // ── Deploy confirm handlers ────────────────────────────────────────────────
  const handleDeploy = useCallback(async () => {
    setMessages(prev => prev.map(m => m.id === deployHitlId ? { ...m, hitlApproved: true } : m));
    setDeployHitlId(null);

    if (!configRunId) {
      push({ id: uid(), role: 'assistant', content: 'Cannot save: missing config run ID. Try regenerating.', timestamp: new Date() });
      setUiState('done');
      return;
    }

    const thinkId = uid();
    setThinking(true);
    setThinkingLabel('Saving to database…');
    push({ id: thinkId, role: 'assistant', content: '', isThinking: true, timestamp: new Date() });

    try {
      const result = await reviewRun(configRunId, 'approve');
      setMessages(prev => prev.filter(m => m.id !== thinkId));
      setThinking(false);

      if (result.write_result?.written) {
        push({
          id: uid(), role: 'assistant', timestamp: new Date(),
          content: `Config saved to database ✅\n\nRow ID: \`${result.write_result.row_id ?? '—'}\`\nRule is now active. You can monitor its performance on the risk dashboard.`,
        });
      } else {
        push({
          id: uid(), role: 'assistant', timestamp: new Date(),
          content: `Save completed but write may have been skipped.\n\nReason: ${result.write_result?.reason ?? 'unknown'}`,
        });
      }
      setUiState('deployed');
    } catch (err) {
      setMessages(prev => prev.filter(m => m.id !== thinkId));
      setThinking(false);
      push({ id: uid(), role: 'assistant', content: `Failed to save config: ${(err as Error).message}`, timestamp: new Date() });
      setUiState('done');
    }
  }, [deployHitlId, configRunId, push]);

  const handleRequestDeployChange = useCallback(() => {
    setMessages(prev => prev.map(m => m.id === deployHitlId ? { ...m, hitlApproved: false } : m));
    setDeployHitlId(null);
    setPendingConfig(null);
    setUiState('done');
  }, [deployHitlId]);

  // ── Send message (clarification answer or free-text modification) ──────────
  const sendMessage = async () => {
    const text = input.trim();
    if (!text || thinking) return;
    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    push({ id: uid(), role: 'user', content: text, timestamp: new Date() });

    try {
      if (uiState === 'clarifying') {
        // Answer to agent's clarification question — re-send original input + answer
        const response = await withThinking('Processing your answer…', () =>
          chatWithConfigAgent(originalInput, sessionId, text)
        );
        handleAgentResponse(response);
      } else {
        // Modification request after config is shown
        const response = await withThinking('Updating config…', () =>
          chatWithConfigAgent(text, sessionId)
        );
        handleAgentResponse(response);
      }
    } catch {
      push({ id: uid(), role: 'assistant', content: 'Could not reach config agent. Check connection and retry.', timestamp: new Date() });
    }
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  };

  // ─────────────────────────────────────────────────────────────────────────

  if (loading) return (
    <div className="flex items-center justify-center h-[80vh] gap-3 text-gray-500">
      <span className="spinner-border spinner-border-sm" /> Loading investigation…
    </div>
  );

  if (!finalPattern) return (
    <Container>
      <div className="flex flex-col items-center justify-center h-[60vh] gap-4">
        <KeenIcon icon="information-2" className="text-4xl text-gray-300" />
        <p className="text-gray-500 text-sm">No final pattern found for this investigation.</p>
        <button className="btn btn-sm btn-light" onClick={() => navigate(`/ai-investigation/${runId}`)}>
          <KeenIcon icon="arrow-left" className="me-1" /> Back
        </button>
      </div>
    </Container>
  );

  const inputBlocked = !!hitlId || !!deployHitlId || thinking || uiState === 'deployed';
  const isClarifying = uiState === 'clarifying';

  return (
    <div className="flex flex-col" style={{ height: 'calc(100vh - 70px)' }}>

      {/* ── Top bar ── */}
      <div className="shrink-0 flex items-center gap-3 px-5 py-2.5 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
        <button className="btn btn-sm btn-icon btn-clear btn-light" onClick={() => navigate(`/ai-investigation/${runId}`)}>
          <KeenIcon icon="arrow-left" />
        </button>
        <div className="flex items-center gap-2 shrink-0">
          <div className="size-7 rounded-lg bg-primary/10 flex items-center justify-center">
            <KeenIcon icon="robot" className="text-primary text-sm" />
          </div>
          <span className="text-sm font-semibold text-gray-800 dark:text-white hidden sm:block">Config Agent</span>
          <span className="text-xs text-gray-400 font-mono hidden md:block">
            · {rule?.rule_name ?? finalPattern.description.slice(0, 40)}
          </span>
        </div>
        <div className="flex-1" />
        <span className={`badge rounded-[30px] text-xs shrink-0 ${
          uiState === 'deployed'        ? 'badge-success badge-outline' :
          uiState === 'confirm_deploy'  ? 'badge-warning badge-outline' :
          uiState === 'clarifying'      ? 'badge-warning badge-outline' :
          uiState === 'done'            ? 'badge-light badge-outline'   :
                                          'badge-primary badge-outline'
        }`}>
          <span className={`size-1.5 rounded-full me-1.5 ${
            uiState === 'deployed'       ? 'bg-success' :
            uiState === 'confirm_deploy' ? 'bg-warning animate-pulse' :
            uiState === 'clarifying'     ? 'bg-warning animate-pulse' :
            uiState === 'done'           ? 'bg-gray-400' :
                                           'bg-primary animate-pulse'
          }`} />
          {uiState === 'deployed'       ? 'Deployed' :
           uiState === 'confirm_deploy' ? 'Awaiting deploy confirm' :
           uiState === 'clarifying'     ? 'Clarifying' :
           uiState === 'generating'     ? 'Generating…' :
           uiState === 'done'           ? 'Changes requested' :
                                          'Awaiting confirm'}
        </span>
      </div>

      {/* ── Messages ── */}
      <div className="flex-1 overflow-y-auto px-5 py-5 bg-gray-50 dark:bg-gray-950">
        <div className="max-w-3xl mx-auto">
          {messages.map(msg => {
            if (msg.isThinking)            return <ThinkingBubble key={msg.id} label={thinkingLabel} />;
            if (msg.role === 'system')     return <SystemMsg key={msg.id} content={msg.content} />;
            if (msg.role === 'user')       return <UserBubble key={msg.id} content={msg.content} />;
            if (msg.role === 'assistant')  return <AssistantBubble key={msg.id} content={msg.content} />;
            if (msg.role === 'config_preview') return <ConfigPreview key={msg.id} content={msg.content} />;
            if (msg.role === 'hitl') {
              if (msg.id === deployHitlId || msg.hitlTitle === 'Save Config to config-service') {
                return <HitlCard key={msg.id} msg={msg} approveLabel="Save to config-service" onApprove={handleDeploy} onRequestChange={handleRequestDeployChange} />;
              }
              return <HitlCard key={msg.id} msg={msg} approveLabel="Confirm — Generate Config" onApprove={handleConfirm} />;
            }
            return null;
          })}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* ── Input ── */}
      <div className="shrink-0 border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-5 py-3">
        <div className="max-w-3xl mx-auto">
          {uiState === 'deployed' ? (
            <div className="flex items-center justify-center gap-3 py-2 text-sm text-success flex-wrap">
              <KeenIcon icon="check-circle" className="text-lg shrink-0" />
              <span>Config saved. Rule is now active.</span>
              {pendingConfig && (
                <button
                  className="btn btn-sm btn-light"
                  onClick={() => {
                    const blob = new Blob([JSON.stringify(pendingConfig, null, 2)], { type: 'application/json' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = outputFile?.split('/').pop() ?? 'config.json';
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                >
                  <KeenIcon icon="download" className="me-1" /> Download JSON
                </button>
              )}
              <button className="btn btn-sm btn-light" onClick={() => navigate(`/ai-investigation/${runId}`)}>
                Back to investigation
              </button>
            </div>
          ) : hitlId ? (
            <p className="text-xs text-center text-gray-400 py-2">
              Review the pattern above and click <strong>Confirm</strong> to generate config.
            </p>
          ) : deployHitlId ? (
            <p className="text-xs text-center text-gray-400 py-2">
              Review the config above — click <strong>Save to config-service</strong> or <strong>Request Changes</strong>.
            </p>
          ) : (
            <>
              {isClarifying && (
                <div className="flex items-center gap-2 mb-2 text-xs text-warning font-medium">
                  <KeenIcon icon="information-2" className="text-sm" />
                  Agent needs more info — type your answer below
                </div>
              )}
              <div className={`flex items-end gap-2 bg-gray-50 dark:bg-gray-800 border rounded-xl px-3 py-2.5 transition-colors ${
                thinking ? 'border-gray-200 dark:border-gray-700 opacity-60' :
                isClarifying ? 'border-warning/40 focus-within:border-warning' :
                               'border-gray-200 dark:border-gray-600 focus-within:border-primary'
              }`}>
                <textarea
                  ref={textareaRef}
                  rows={1}
                  className="flex-1 bg-transparent resize-none outline-none text-sm text-gray-800 dark:text-white placeholder-gray-400 leading-relaxed"
                  placeholder={
                    uiState === 'clarifying' ? 'Type your answer…' :
                    uiState === 'done'       ? 'Describe what to change in the config…' :
                                              'Ask a question…'
                  }
                  value={input}
                  onChange={e => {
                    setInput(e.target.value);
                    if (textareaRef.current) {
                      textareaRef.current.style.height = 'auto';
                      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + 'px';
                    }
                  }}
                  onKeyDown={onKey}
                  disabled={inputBlocked}
                />
                <button
                  className={`btn btn-sm btn-icon shrink-0 ${isClarifying ? 'btn-warning' : 'btn-primary'}`}
                  onClick={sendMessage}
                  disabled={!input.trim() || inputBlocked}
                >
                  {thinking ? <span className="spinner-border spinner-border-sm" /> : <KeenIcon icon="paper-plane" />}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export { AiAssistantPage };
