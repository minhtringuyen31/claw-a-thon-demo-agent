import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ColumnDef } from '@tanstack/react-table';
import { DataGrid, KeenIcon } from '@/components';
import { Container } from '@/components/container';
import { deleteRun, getRun, listRuns, triggerPostmortem, RunOut, RunStatus } from '@/services/apis/Agent';

// ─── Quick Test cases ─────────────────────────────────────────────────────────

interface PomTestCase {
  run_id: string;
  title: string;
  fraud_type: string;
  incident_id: string;
  period: string;
  total_count: number;
  columns: string[];
  rows: Record<string, string | number>[];
}

const TEST_CASES: PomTestCase[] = [
  {
    run_id: '84afd742',
    title: 'Chargeback Fraud — ZPCC / domestic_napas',
    fraud_type: 'CF',
    incident_id: 'INC-2025-01-CF',
    period: '2025-01-03 → 2025-01-11',
    total_count: 10,
    columns: ['appID', 'userID', 'transID', 'reqDate', 'userChargeAmount', 'integratedChannel', 'bankCode', 'bankType', 'fraud_type', 'appName', 'reportCat'],
    rows: [
      { appID: 148,  userID: 1, transID: '250103000830907', reqDate: '2025-01-03 11:42:31', userChargeAmount: 400000,   integratedChannel: 'domestic_napas', bankCode: 'ZPVCB', bankType: 'domestic_napas', fraud_type: 'CF', appName: 'Payment Direct', reportCat: 'Game'          },
      { appID: 149,  userID: 1, transID: '250103000921213', reqDate: '2025-01-03 12:28:47', userChargeAmount: 10000000, integratedChannel: 'CREDIT CARD',    bankCode: 'ZPCC',  bankType: 'international',   fraud_type: 'CF', appName: 'Mobile Payment', reportCat: 'Game'          },
      { appID: 356,  userID: 1, transID: '250106000523652', reqDate: '2025-01-06 09:45:47', userChargeAmount: 6000000,  integratedChannel: 'domestic_napas', bankCode: 'ZPVCB', bankType: 'domestic_napas', fraud_type: 'CF', appName: 'TIKI.VN.GW',    reportCat: 'Marketplace'   },
      { appID: 2391, userID: 1, transID: '250106001473963', reqDate: '2025-01-06 18:02:00', userChargeAmount: 582000,   integratedChannel: 'domestic_napas', bankCode: 'ZPTCB', bankType: 'domestic_napas', fraud_type: 'CF', appName: 'Thẻ giải trí',  reportCat: 'Telco'         },
      { appID: 148,  userID: 1, transID: '250107000750903', reqDate: '2025-01-07 11:54:57', userChargeAmount: 2000000,  integratedChannel: 'domestic_napas', bankCode: 'ZPVCB', bankType: 'domestic_napas', fraud_type: 'CF', appName: 'Payment Direct', reportCat: 'Game'          },
      { appID: 356,  userID: 1, transID: '250108001235908', reqDate: '2025-01-08 16:49:32', userChargeAmount: 9000000,  integratedChannel: 'domestic_napas', bankCode: 'ZPVCB', bankType: 'domestic_napas', fraud_type: 'CF', appName: 'TIKI.VN.GW',    reportCat: 'Marketplace'   },
      { appID: 3677, userID: 1, transID: '250110000470409', reqDate: '2025-01-10 09:09:15', userChargeAmount: 5299000,  integratedChannel: 'CREDIT CARD',    bankCode: 'ZPCC',  bankType: 'international',   fraud_type: 'CF', appName: 'Roblox',         reportCat: 'Game'          },
      { appID: 3677, userID: 1, transID: '250110002204048', reqDate: '2025-01-10 22:25:43', userChargeAmount: 499000,   integratedChannel: 'domestic_napas', bankCode: 'ZPTCB', bankType: 'domestic_napas', fraud_type: 'CF', appName: 'Roblox',         reportCat: 'Game'          },
      { appID: 3555, userID: 1, transID: '250110002308309', reqDate: '2025-01-10 23:34:47', userChargeAmount: 4000000,  integratedChannel: 'domestic_napas', bankCode: 'ZPTCB', bankType: 'domestic_napas', fraud_type: 'CF', appName: 'DEALTODAY',      reportCat: 'Entertainment' },
      { appID: 2391, userID: '', transID: '250111000461195', reqDate: '2025-01-11 09:04:39', userChargeAmount: 582000,  integratedChannel: 'ATM-API',        bankCode: 'ZPVCB', bankType: 'domestic_direct', fraud_type: 'CF', appName: 'Thẻ giải trí',  reportCat: 'Telco'         },
    ],
  },
];

// ─── Quick Test Modal ─────────────────────────────────────────────────────────

const QuickTestModal = ({ onRun }: { onRun: (runId: string) => void }) => {
  const [open, setOpen] = useState(false);
  const [runningId, setRunningId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open]);

  const handleRun = async (tc: PomTestCase) => {
    setRunningId(tc.run_id);
    try {
      const run = await triggerPostmortem({
        incident_id: tc.incident_id,
        summary: `${tc.title} — fraud_type=${tc.fraud_type}, period=${tc.period}, total=${tc.total_count} cases`,
        record: {
          incident_id: tc.incident_id,
          period:      tc.period,
          fraud_type:  tc.fraud_type,
          total_count: tc.total_count,
          cases:       tc.rows,
        },
      });
      setOpen(false);
      onRun(run.run_id);
    } finally {
      setRunningId(null);
    }
  };

  return (
    <>
      <button className="btn btn-sm btn-light" onClick={() => setOpen(true)}>
        <KeenIcon icon="flash" />
        Quick Test
      </button>

      {open && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => !runningId && setOpen(false)} />

          <div className="relative bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-2xl flex flex-col max-h-[88vh] overflow-hidden">

            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 dark:border-gray-800 shrink-0">
              <div className="flex items-center gap-3">
                <div className="size-8 rounded-lg bg-primary/10 flex items-center justify-center">
                  <KeenIcon icon="flash" className="text-primary text-sm" />
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-gray-900 dark:text-white">Quick Test</h4>
                  <p className="text-xs text-gray-400">{TEST_CASES.length} POM test cases — POST đến <code className="font-mono">/triggers/postmortem</code></p>
                </div>
              </div>
              <button className="btn btn-sm btn-icon btn-clear btn-light" onClick={() => setOpen(false)} disabled={!!runningId}>
                <KeenIcon icon="cross" />
              </button>
            </div>

            {/* Test case list */}
            <div className="overflow-y-auto flex-1 divide-y divide-gray-100 dark:divide-gray-800">
              {TEST_CASES.map((tc) => (
                <div key={tc.run_id} className="px-6 py-4">

                  {/* Case header */}
                  <div className="flex items-start justify-between gap-4 mb-3">
                    <div>
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-sm font-semibold text-gray-800 dark:text-white">{tc.title}</span>
                        <span className="badge badge-danger badge-outline rounded-[30px] text-[11px]">{tc.fraud_type}</span>
                      </div>
                      <p className="text-[11px] text-gray-400 font-mono">{tc.incident_id} · {tc.period}</p>
                    </div>
                    <button
                      className="btn btn-sm btn-primary shrink-0"
                      onClick={() => handleRun(tc)}
                      disabled={runningId !== null}
                    >
                      {runningId === tc.run_id ? (
                        <><span className="spinner-border spinner-border-sm" /> Starting…</>
                      ) : (
                        <><KeenIcon icon="send" /> Run</>
                      )}
                    </button>
                  </div>

                  {/* POM sample rows */}
                  <div className="border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
                    <table className="w-full text-[11px]">
                      <thead>
                        <tr className="bg-gray-50 dark:bg-gray-800 text-gray-500">
                          {tc.columns.map((col) => (
                            <th key={col} className="px-3 py-1.5 text-left font-medium whitespace-nowrap">{col}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100 dark:divide-gray-800 font-mono">
                        {tc.rows.map((row, i) => (
                          <tr key={i} className="hover:bg-gray-50 dark:hover:bg-gray-800/40">
                            {tc.columns.map((col) => (
                              <td key={col} className="px-3 py-1.5 text-gray-600 dark:text-gray-400 whitespace-nowrap">{row[col]}</td>
                            ))}
                          </tr>
                        ))}
                        <tr>
                          <td colSpan={tc.columns.length} className="px-3 py-1.5 text-gray-400 italic">
                            … {(tc.total_count - tc.rows.length).toLocaleString()} more rows
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>

            {/* Footer */}
            <div className="px-6 py-3 border-t border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/30 shrink-0">
              <p className="text-[11px] text-gray-400">
                Mock mode — Run navigates trực tiếp đến pre-built result. Đổi <code className="font-mono">index.ts</code> → <code className="font-mono">agentService</code> để trigger live agent.
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

const STATUS_CONFIG: Record<RunStatus, { label: string; color: string }> = {
  running: { label: 'Running', color: 'primary' },
  completed: { label: 'Completed', color: 'success' },
  failed: { label: 'Failed', color: 'danger' },
};

const InvestigationListPage = () => {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<RunOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [agentOnline, setAgentOnline] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchRuns = useCallback(async () => {
    try {
      const ids = await listRuns();
      const results = await Promise.all(ids.map((id) => getRun(id)));
      setRuns(results);
      setAgentOnline(true);
    } catch {
      setAgentOnline(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);


  // Poll every 4s while any run is in "running" state
  useEffect(() => {
    const hasRunning = runs.some((r) => r.status === 'running');
    if (hasRunning) {
      pollRef.current = setInterval(fetchRuns, 4000);
    } else {
      if (pollRef.current) clearInterval(pollRef.current);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [runs, fetchRuns]);

  const columns = useMemo<ColumnDef<RunOut>[]>(
    () => [
      {
        accessorKey: 'run_id',
        header: () => 'Run ID',
        enableSorting: true,
        cell: ({ row }) => (
          <span className="text-sm font-mono text-gray-600">{row.original.run_id}</span>
        ),
        meta: { className: 'min-w-[110px]' },
      },
      {
        id: 'title',
        header: () => 'Description',
        enableSorting: false,
        cell: ({ row }) => {
          const r = row.original;
          const label =
            r.rule_json?.description ??
            r.no_action_report?.recommendation ??
            r.investigation_report?.recommendation ??
            '—';
          return (
            <span className="text-sm text-gray-800 line-clamp-2 max-w-[320px]" title={label}>
              {label}
            </span>
          );
        },
        meta: { className: 'min-w-[280px]' },
      },
      {
        id: 'anomaly',
        header: () => 'Anomaly',
        enableSorting: false,
        cell: ({ row }) => {
          const dec = row.original.anomaly_decision;
          if (!dec) return <span className="text-gray-400 text-sm">—</span>;
          return dec.is_anomalous ? (
            <span className="badge badge-danger badge-outline rounded-[30px]">
              <span className="size-1.5 rounded-full bg-danger me-1.5" />
              Detected
            </span>
          ) : (
            <span className="badge badge-success badge-outline rounded-[30px]">
              <span className="size-1.5 rounded-full bg-success me-1.5" />
              Clear
            </span>
          );
        },
        meta: { className: 'min-w-[120px]' },
      },
      {
        accessorKey: 'status',
        header: () => 'Status',
        enableSorting: true,
        cell: ({ row }) => {
          const s = STATUS_CONFIG[row.original.status];
          return (
            <span className={`badge badge-${s.color} badge-outline rounded-[30px] shrink-0`}>
              {row.original.status === 'running' && (
                <span className={`size-1.5 rounded-full bg-${s.color} me-1.5 animate-pulse`} />
              )}
              {row.original.status !== 'running' && (
                <span className={`size-1.5 rounded-full bg-${s.color} me-1.5`} />
              )}
              {s.label}
            </span>
          );
        },
        meta: { className: 'min-w-[130px]' },
      },
      {
        id: 'metrics',
        header: () => 'Precision / Recall',
        enableSorting: false,
        cell: ({ row }) => {
          const m = row.original.rule_json?.metrics;
          if (!m) return <span className="text-gray-400 text-sm">—</span>;
          return (
            <span className="text-sm text-gray-700 font-mono">
              {(m.precision * 100).toFixed(0)}% / {(m.recall * 100).toFixed(0)}%
            </span>
          );
        },
        meta: { className: 'min-w-[140px]' },
      },
      {
        id: 'findings',
        header: () => 'Patterns',
        enableSorting: false,
        cell: ({ row }) => {
          const count = row.original.investigation_report?.patterns_attempted?.length ?? 0;
          return (
            <span className="text-sm text-gray-700">
              {count > 0 ? count : '—'}
            </span>
          );
        },
        meta: { className: 'min-w-[80px]' },
      },
      {
        id: 'timestamp',
        header: () => 'Emitted At',
        enableSorting: true,
        sortingFn: (a, b) => {
          const tsA = a.original.rule_json?.emitted_at ?? a.original.no_action_report?.emitted_at ?? '';
          const tsB = b.original.rule_json?.emitted_at ?? b.original.no_action_report?.emitted_at ?? '';
          return tsA < tsB ? -1 : tsA > tsB ? 1 : 0;
        },
        cell: ({ row }) => {
          const ts =
            row.original.rule_json?.emitted_at ??
            row.original.no_action_report?.emitted_at ??
            null;
          if (!ts) return <span className="text-gray-400 text-sm">—</span>;
          return (
            <span className="text-sm text-gray-600">
              {new Date(ts).toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' })}
            </span>
          );
        },
        meta: { className: 'min-w-[130px]' },
      },
      {
        id: 'actions',
        header: () => '',
        enableSorting: false,
        cell: ({ row }) => {
          const runId = row.original.run_id;
          const isRunning = row.original.status === 'running';
          const isDeleting = deletingId === runId;
          return (
            <div className="flex items-center gap-1">
              <button
                className="btn btn-sm btn-icon btn-clear btn-light"
                title="View detail"
                onClick={() => navigate(`/ai-investigation/${runId}`)}
              >
                <KeenIcon icon="eye" />
              </button>
              <button
                className="btn btn-sm btn-icon btn-clear btn-light-danger"
                title={isRunning ? 'Stop & delete run' : 'Delete run'}
                disabled={isDeleting}
                onClick={async (e) => {
                  e.stopPropagation();
                  if (!confirm(`Delete run ${runId}?`)) return;
                  setDeletingId(runId);
                  try {
                    await deleteRun(runId);
                    setRuns((prev) => prev.filter((r) => r.run_id !== runId));
                  } finally {
                    setDeletingId(null);
                  }
                }}
              >
                {isDeleting
                  ? <span className="spinner-border spinner-border-sm" />
                  : <KeenIcon icon={isRunning ? 'stop' : 'trash'} />
                }
              </button>
            </div>
          );
        },
        meta: { className: 'w-[100px]' },
      },
    ],
    [navigate]
  );

  return (
    <>
      <Container>
      <div className="grid gap-5 lg:gap-7.5">
        {!agentOnline && (
          <div className="flex items-center gap-3 px-4 py-3 bg-warning-light border border-warning rounded-lg text-sm text-warning-dark">
            <KeenIcon icon="information-2" className="shrink-0 text-warning" />
            Cannot connect to agent
            <code className="font-mono text-xs">fraud-analysis-agent</code>
          </div>
        )}

        <div className="card card-grid h-full min-w-full">
          <div className="card-header flex-wrap gap-2.5">
            <div>
              <h3 className="card-title">AI Investigations</h3>
              <p className="text-sm text-gray-500 mt-0.5">{runs.length} total runs</p>
            </div>
            <div className="flex items-center flex-wrap gap-2.5">
              <button
                className="btn btn-sm btn-icon btn-light"
                title="Refresh"
                onClick={() => { setLoading(true); fetchRuns(); }}
              >
                <KeenIcon icon="arrows-circle" />
              </button>
              <QuickTestModal onRun={(id) => navigate(`/ai-investigation/${id}`)} />
            </div>
          </div>

          <div className="card-body">
            {loading ? (
              <div className="flex items-center justify-center py-16 gap-3 text-gray-500">
                <span className="spinner-border spinner-border-sm" />
                Loading runs...
              </div>
            ) : runs.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 gap-3 text-gray-500">
                <KeenIcon icon="search-list" className="text-4xl text-gray-300" />
                <p className="text-sm">No investigations found.</p>
              </div>
            ) : (
              <DataGrid
                columns={columns}
                data={runs}
                getRowId={(row) => row.run_id}
                rowSelect={false}
                paginationSize={10}
                initialSorting={[{ id: 'timestamp', desc: true }]}
              />
            )}
          </div>
        </div>
      </div>
      </Container>
    </>
  );
};

export { InvestigationListPage };
