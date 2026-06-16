import { useCallback, useEffect, useRef, useState } from 'react';
import { KeenIcon } from '@/components';
import {
  chatV2,
  runFromReport,
  reviewRun,
  getRunV2,
  listRunsV2,
  ChatV2Response,
  RunSummary,
  DedupInfo,
  WriteResult,
} from '@/services/apis/configAgentV2Service';

// ─── Helpers ──────────────────────────────────────────────────────────────────

let _id = 0;
const uid = () => `m${++_id}`;
const sid = () =>
  (crypto?.randomUUID?.() ?? `s${Date.now()}-${Math.floor(Math.random() * 1e6)}`);

function fmtTime(iso?: string) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const diffMin = Math.floor((Date.now() - d.getTime()) / 60000);
    if (diffMin < 1) return 'just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffMin < 1440) return `${Math.floor(diffMin / 60)}h ago`;
    return d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit' });
  } catch {
    return '';
  }
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface ReviewState {
  runId: string;
  operation?: 'create' | 'update';
  dedup?: DedupInfo;
  config?: object;
  resolved?: 'approve' | 'reject' | null;
  writeResult?: WriteResult;
  busy?: boolean;
}

interface UIMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  isThinking?: boolean;
  config?: object; // read-only config preview
  review?: ReviewState; // interactive review card
}

const RUN_BADGE: Record<string, { label: string; cls: string }> = {
  awaiting_review: { label: 'Review', cls: 'badge-warning' },
  completed: { label: 'Written', cls: 'badge-success' },
  rejected: { label: 'Rejected', cls: 'badge-danger' },
  clarify: { label: 'Clarifying', cls: 'badge-info' },
  running: { label: 'Running', cls: 'badge-primary' },
  error: { label: 'Error', cls: 'badge-danger' },
};

// ─── Config preview (collapsible) ─────────────────────────────────────────────

const ConfigBlock = ({ content, defaultOpen = false }: { content: string; defaultOpen?: boolean }) => {
  const [open, setOpen] = useState(defaultOpen);
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-2 border border-primary/20 rounded-xl overflow-hidden text-xs">
      <div className="flex items-center justify-between px-3 py-2 bg-primary/5 border-b border-primary/10">
        <button onClick={() => setOpen(v => !v)} className="flex items-center gap-1.5 text-primary/70 hover:text-primary font-semibold">
          <KeenIcon icon={open ? 'down' : 'right'} className="text-[10px]" />
          Config JSON
        </button>
        <button
          onClick={() => { navigator.clipboard.writeText(content); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
          className="flex items-center gap-1 text-gray-400 hover:text-gray-600"
        >
          <KeenIcon icon={copied ? 'check' : 'copy'} className="text-[10px]" />
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      {open && (
        <pre className="px-3 py-2 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-300 font-mono overflow-x-auto whitespace-pre-wrap max-h-64 leading-relaxed">
          {content}
        </pre>
      )}
    </div>
  );
};

// ─── Review card (human-in-the-loop gate) ──────────────────────────────────────

const ReviewCard = ({
  review,
  onDecision,
}: {
  review: ReviewState;
  onDecision: (decision: 'approve' | 'reject') => void;
}) => {
  const op = (review.operation ?? 'create').toUpperCase();
  const dd = review.dedup?.found
    ? ` · duplicates rule "${review.dedup.rule_name}" in event "${review.dedup.event_name}"`
    : '';

  return (
    <div className="mt-2 border border-warning/30 rounded-xl overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 bg-warning/10 border-b border-warning/20">
        <KeenIcon icon="shield-tick" className="text-warning text-sm" />
        <span className="text-xs font-semibold text-gray-700 dark:text-gray-200">
          Pending Review · {op}
        </span>
        <span className="text-[11px] text-gray-400">{dd}</span>
      </div>
      <div className="px-3 py-2">
        {review.config && <ConfigBlock content={JSON.stringify(review.config, null, 2)} defaultOpen />}

        {review.resolved == null ? (
          <div className="flex items-center gap-2 mt-2.5">
            <button
              className="btn btn-sm btn-success flex-1"
              disabled={review.busy}
              onClick={() => onDecision('approve')}
            >
              {review.busy ? <span className="spinner-border spinner-border-sm" /> : <KeenIcon icon="check" className="text-xs me-1" />}
              Approve
            </button>
            <button
              className="btn btn-sm btn-light btn-outline flex-1"
              disabled={review.busy}
              onClick={() => onDecision('reject')}
            >
              <KeenIcon icon="cross" className="text-xs me-1" />
              Reject
            </button>
          </div>
        ) : review.resolved === 'approve' ? (
          <div className="mt-2.5 text-xs text-success flex items-center gap-1.5">
            <KeenIcon icon="check-circle" />
            Written to {review.writeResult?.target ?? 'store'}
            {review.writeResult?.row_id != null && ` (row #${review.writeResult.row_id})`}.
          </div>
        ) : (
          <div className="mt-2.5 text-xs text-danger flex items-center gap-1.5">
            <KeenIcon icon="cross-circle" />
            Rejected — config not written.
          </div>
        )}
      </div>
    </div>
  );
};

// ─── Message bubble ───────────────────────────────────────────────────────────

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

const Bubble = ({
  msg,
  onDecision,
}: {
  msg: UIMessage;
  onDecision: (msgId: string, decision: 'approve' | 'reject') => void;
}) => {
  if (msg.isThinking) {
    return (
      <div className="flex gap-2.5 mb-3">
        <div className="size-6 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
          <KeenIcon icon="robot" className="text-primary text-[10px]" />
        </div>
        <div className="flex items-center gap-2 bg-white dark:bg-gray-800 border border-primary/20 rounded-2xl rounded-tl-sm px-3 py-2">
          <svg className="size-3 animate-spin text-primary" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
            <path className="opacity-80" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <span className="text-xs text-gray-400">Thinking…</span>
        </div>
      </div>
    );
  }

  if (msg.role === 'system') {
    return (
      <div className="flex justify-center my-2">
        <span className="text-[11px] text-gray-400 bg-gray-100 dark:bg-gray-800 px-3 py-1 rounded-full">{msg.content}</span>
      </div>
    );
  }

  if (msg.role === 'user') {
    return (
      <div className="flex justify-end mb-3">
        <div className="max-w-[75%] bg-primary text-white rounded-2xl rounded-tr-sm px-3 py-2 text-sm leading-relaxed">{msg.content}</div>
      </div>
    );
  }

  // assistant
  const lines = msg.content.split('\n');
  return (
    <div className="flex gap-2.5 mb-3">
      <div className="size-6 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
        <KeenIcon icon="robot" className="text-primary text-[10px]" />
      </div>
      <div className="flex-1 max-w-[80%]">
        {msg.content && (
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl rounded-tl-sm px-3 py-2.5 text-sm text-gray-800 dark:text-gray-200">
            {lines.map((line, i) =>
              line === '' ? <div key={i} className="h-1.5" /> : <div key={i} className="leading-relaxed"><InlineCode text={line} /></div>
            )}
          </div>
        )}
        {msg.review && <ReviewCard review={msg.review} onDecision={d => onDecision(msg.id, d)} />}
        {msg.config && !msg.review && <ConfigBlock content={JSON.stringify(msg.config, null, 2)} />}
      </div>
    </div>
  );
};

// ─── Runs sidebar item ──────────────────────────────────────────────────────────

const RunItem = ({ r, active, onClick }: { r: RunSummary; active: boolean; onClick: () => void }) => {
  const badge = RUN_BADGE[r.status] ?? RUN_BADGE.running;
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-2.5 rounded-xl transition-colors ${
        active ? 'bg-primary/10 border border-primary/20' : 'hover:bg-gray-100 dark:hover:bg-gray-800 border border-transparent'
      }`}
    >
      <div className="flex items-start justify-between gap-2 mb-1">
        <span className="text-xs font-mono text-gray-700 dark:text-gray-200 truncate flex-1">#{r.run_id.slice(0, 8)}</span>
        <span className={`badge ${badge.cls} badge-outline rounded-[20px] text-[10px] px-1.5 shrink-0`}>{badge.label}</span>
      </div>
      <div className="flex items-center gap-2 text-[11px] text-gray-400">
        <span className="capitalize">{r.source_type ?? 'chat'}</span>
        {r.source_run_id && <span className="text-info">· from report</span>}
        <span className="ms-auto">{fmtTime(r.created_at)}</span>
      </div>
    </button>
  );
};

// ─── Main Page ────────────────────────────────────────────────────────────────

export const ChatAssistantPage = () => {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [sessionId, setSessionId] = useState<string>(() => sid());
  const [originalInput, setOriginalInput] = useState('');
  const [isClarifying, setIsClarifying] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [input, setInput] = useState('');
  const [reportRunId, setReportRunId] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const push = useCallback((msg: UIMessage | UIMessage[]) => {
    setMessages(prev => [...prev, ...(Array.isArray(msg) ? msg : [msg])]);
  }, []);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const loadRuns = useCallback(async () => {
    const list = await listRunsV2();
    // newest first
    list.sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''));
    setRuns(list);
  }, []);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  const newSession = useCallback(() => {
    setActiveRunId(null);
    setSessionId(sid());
    setMessages([{ id: uid(), role: 'system', content: 'New session — describe a fraud pattern, or paste a fraud-analysis-agent run_id (top right) to build config from a report.' }]);
    setOriginalInput('');
    setIsClarifying(false);
    textareaRef.current?.focus();
  }, []);

  // Open a past run read-only.
  const openRun = useCallback(async (runId: string) => {
    setActiveRunId(runId);
    setMessages([]);
    const detail = await getRunV2(runId);
    if (!detail) {
      push({ id: uid(), role: 'system', content: 'Could not load run.' });
      return;
    }
    const msgs: UIMessage[] = [
      { id: uid(), role: 'system', content: `Run #${runId.slice(0, 8)} · ${detail.status}` },
    ];
    if (detail.status === 'awaiting_review') {
      msgs.push({
        id: uid(), role: 'assistant', content: 'Config plan — awaiting strategist review:',
        review: { runId, operation: detail.operation, dedup: detail.dedup, config: detail.final_output, resolved: null },
      });
    } else if (detail.final_output && Object.keys(detail.final_output).length) {
      const written = detail.write_result?.written;
      msgs.push({
        id: uid(), role: 'assistant',
        content: written ? `✅ Written to ${detail.write_result?.target ?? 'store'}${detail.write_result?.row_id != null ? ` (row #${detail.write_result.row_id})` : ''}.` : 'Config plan:',
        config: detail.final_output,
      });
    }
    setMessages(msgs);
    setIsClarifying(false);
  }, [push]);

  // Map a chat/report response into UI messages.
  const handleResponse = useCallback((resp: ChatV2Response) => {
    if (resp.session_id) setSessionId(resp.session_id);
    if (resp.run_id) setActiveRunId(resp.run_id);

    if (resp.status === 'clarify' && resp.question) {
      setIsClarifying(true);
      push({ id: uid(), role: 'assistant', content: resp.question });
    } else if (resp.status === 'awaiting_review' && resp.run_id) {
      setIsClarifying(false);
      push({
        id: uid(), role: 'assistant', content: 'Config plan built — awaiting your review:',
        review: { runId: resp.run_id, operation: resp.operation, dedup: resp.dedup, config: resp.final_output, resolved: null },
      });
    } else if (resp.status === 'completed') {
      setIsClarifying(false);
      push({ id: uid(), role: 'assistant', content: 'Done.', config: resp.final_output });
    } else {
      setIsClarifying(false);
      push({ id: uid(), role: 'assistant', content: resp.message || 'Something went wrong, please try again.' });
    }
    loadRuns();
  }, [push, loadRuns]);

  const runWithThinking = useCallback(async (fn: () => Promise<ChatV2Response>) => {
    const thinkId = uid();
    setThinking(true);
    setMessages(prev => [...prev, { id: thinkId, role: 'assistant', content: '', isThinking: true }]);
    try {
      const resp = await fn();
      setMessages(prev => prev.filter(m => m.id !== thinkId));
      setThinking(false);
      handleResponse(resp);
    } catch (e) {
      setMessages(prev => prev.filter(m => m.id !== thinkId));
      setThinking(false);
      push({ id: uid(), role: 'assistant', content: `Could not reach config agent: ${(e as Error).message}` });
    }
  }, [handleResponse, push]);

  const sendMessage = () => {
    const text = input.trim();
    if (!text || thinking) return;
    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    push({ id: uid(), role: 'user', content: text });

    if (isClarifying) {
      runWithThinking(() => chatV2(originalInput, sessionId, text));
    } else {
      setOriginalInput(text);
      runWithThinking(() => chatV2(text, sessionId));
    }
  };

  const sendFromReport = () => {
    const runId = reportRunId.trim();
    if (!runId || thinking) return;
    setReportRunId('');
    push({ id: uid(), role: 'user', content: `Build config from report #${runId.slice(0, 8)}` });
    runWithThinking(() => runFromReport(runId, sessionId));
  };

  // Handle approve/reject on a review card.
  const onDecision = async (msgId: string, decision: 'approve' | 'reject') => {
    const target = messages.find(m => m.id === msgId);
    const runId = target?.review?.runId;
    if (!runId) return;
    setMessages(prev => prev.map(m => (m.id === msgId && m.review ? { ...m, review: { ...m.review, busy: true } } : m)));
    try {
      const res = await reviewRun(runId, decision);
      setMessages(prev => prev.map(m =>
        m.id === msgId && m.review
          ? { ...m, review: { ...m.review, busy: false, resolved: decision, writeResult: res.write_result } }
          : m,
      ));
    } catch (e) {
      setMessages(prev => prev.map(m => (m.id === msgId && m.review ? { ...m, review: { ...m.review, busy: false } } : m)));
      push({ id: uid(), role: 'assistant', content: `Review failed: ${(e as Error).message}` });
    }
    loadRuns();
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  };

  const isEmpty = messages.length === 0 || (messages.length === 1 && messages[0].role === 'system');

  return (
    <div className="flex h-[calc(100vh-70px)] bg-gray-50 dark:bg-gray-950">

      {/* ── Sidebar (runs history) ── */}
      <div className={`flex flex-col shrink-0 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-700 transition-all duration-200 ${sidebarOpen ? 'w-72' : 'w-0 overflow-hidden'}`}>
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-800">
          <span className="text-sm font-semibold text-gray-800 dark:text-white">Runs</span>
          <button className="btn btn-xs btn-success btn-outline" onClick={newSession}>
            <KeenIcon icon="plus" className="text-xs" /> New
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-1">
          {runs.length === 0 ? (
            <div className="text-center py-8 text-xs text-gray-400">No runs yet</div>
          ) : (
            runs.map(r => (
              <RunItem key={r.run_id} r={r} active={activeRunId === r.run_id} onClick={() => openRun(r.run_id)} />
            ))
          )}
        </div>
      </div>

      {/* ── Chat area ── */}
      <div className="flex-1 flex flex-col min-w-0">

        {/* Header */}
        <div className="shrink-0 flex items-center gap-3 px-5 py-2.5 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
          <button className="btn btn-sm btn-icon btn-clear btn-light" onClick={() => setSidebarOpen(v => !v)}>
            <KeenIcon icon="menu" />
          </button>
          <div className="size-7 rounded-lg bg-primary/10 flex items-center justify-center">
            <KeenIcon icon="robot" className="text-primary text-sm" />
          </div>
          <div className="flex-1 min-w-0">
            <span className="text-sm font-semibold text-gray-800 dark:text-white">Config Agent</span>
            <span className="ms-2 text-xs text-gray-400 font-mono">#{sessionId.slice(0, 8)}</span>
          </div>

          {/* From report */}
          <div className="hidden md:flex items-center gap-1.5">
            <input
              className="input input-sm w-44 text-xs"
              placeholder="fraud run_id…"
              value={reportRunId}
              onChange={e => setReportRunId(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); sendFromReport(); } }}
              disabled={thinking}
            />
            <button className="btn btn-sm btn-info btn-outline" onClick={sendFromReport} disabled={!reportRunId.trim() || thinking}>
              <KeenIcon icon="entrance-left" className="text-xs me-1" /> From report
            </button>
          </div>

          {isClarifying && (
            <span className="badge badge-warning badge-outline rounded-[20px] text-xs">
              <span className="size-1.5 rounded-full bg-warning me-1.5 animate-pulse" />
              Clarifying
            </span>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-5 py-5">
          <div className="max-w-2xl mx-auto">
            {isEmpty ? (
              <div className="flex flex-col items-center justify-center py-20 gap-4">
                <div className="size-14 rounded-2xl bg-primary/10 flex items-center justify-center">
                  <KeenIcon icon="robot" className="text-primary text-2xl" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Config Agent</p>
                  <p className="text-xs text-gray-400 max-w-xs">Describe a fraud pattern to create a rule config (with human gate before writing to MySQL), or build from a fraud-analysis-agent report.</p>
                </div>
                <div className="flex flex-col gap-2 w-full max-w-sm">
                  {[
                    'appid 123, reject if total amount in 24h > 10M and account age < 7 days',
                    'Fraud CF: block international card transactions from new accounts',
                  ].map((s, i) => (
                    <button
                      key={i}
                      className="text-left text-xs text-gray-500 hover:text-primary border border-gray-200 dark:border-gray-700 hover:border-primary/30 rounded-xl px-4 py-2.5 transition-colors bg-white dark:bg-gray-800"
                      onClick={() => { setInput(s); textareaRef.current?.focus(); }}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map(msg => <Bubble key={msg.id} msg={msg} onDecision={onDecision} />)
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* Input */}
        <div className="shrink-0 border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-5 py-3">
          <div className="max-w-2xl mx-auto">
            {isClarifying && (
              <p className="text-[11px] text-warning font-medium mb-1.5 flex items-center gap-1">
                <KeenIcon icon="information-2" className="text-sm" />
                Agent needs more info — enter your answer
              </p>
            )}
            <div className={`flex items-end gap-2 bg-gray-50 dark:bg-gray-800 border rounded-xl px-3 py-2.5 transition-colors ${
              thinking ? 'opacity-60 border-gray-200' :
              isClarifying ? 'border-warning/40 focus-within:border-warning' :
                             'border-gray-200 dark:border-gray-600 focus-within:border-primary'
            }`}>
              <textarea
                ref={textareaRef}
                rows={1}
                className="flex-1 bg-transparent resize-none outline-none text-sm text-gray-800 dark:text-white placeholder-gray-400 leading-relaxed"
                placeholder={isClarifying ? 'Enter your answer…' : 'Describe a fraud pattern or rule to create…'}
                value={input}
                onChange={e => {
                  setInput(e.target.value);
                  if (textareaRef.current) {
                    textareaRef.current.style.height = 'auto';
                    textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + 'px';
                  }
                }}
                onKeyDown={onKey}
                disabled={thinking}
              />
              <button
                className={`btn btn-sm btn-icon shrink-0 ${isClarifying ? 'btn-warning' : 'btn-primary'}`}
                onClick={sendMessage}
                disabled={!input.trim() || thinking}
              >
                {thinking
                  ? <span className="spinner-border spinner-border-sm" />
                  : <KeenIcon icon="paper-plane" />
                }
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
