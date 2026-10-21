import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, CaseDetail, CaseSummary, Me, Run } from "../api";
import { StatusTag } from "../components/ui";
import { ContextPanel } from "./ContextPanel";
import { Investigate } from "./Investigate";
import { Resolve } from "./Resolve";
import { Simulate } from "./Simulate";

const VIEWS: [string, string][] = [["All", ""], ["Detected", "DETECTED"], ["Investigating", "INVESTIGATING"],
  ["Scenarios ready", "SCENARIOS_READY"], ["Awaiting supplier", "SENT"], ["Countered", "COUNTERED"],
  ["Needs approval", "BUYER_APPROVAL_PENDING"], ["Export ready", "EXPORT_READY"]];

export function CasesPage({ me }: { me: Me }) {
  const { caseId, mode = "investigate" } = useParams();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [state, setState] = useState("");
  const cases = useQuery({
    queryKey: ["cases", q, state],
    queryFn: () => api<{ items: CaseSummary[]; total: number }>(`/cases?limit=500${q ? `&q=${encodeURIComponent(q)}` : ""}${state ? `&state=${state}` : ""}`),
  });
  const items = cases.data?.items ?? [];
  const idx = items.findIndex((c) => c.case_id === caseId);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT" || (e.target as HTMLElement)?.tagName === "SELECT") return;
      if (e.key === "j" || e.key === "ArrowDown" || e.key === "k" || e.key === "ArrowUp") {
        const next = e.key === "j" || e.key === "ArrowDown" ? Math.min(items.length - 1, idx + 1) : Math.max(0, idx - 1);
        if (items[next]) { e.preventDefault(); nav(`/cases/${items[next].case_id}/${mode}`); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, idx, mode, nav]);

  const counts = useMemo(() => ({ open: items.filter((c) => !["EXPORT_READY", "CLOSED", "REJECTED"].includes(c.state)).length,
    pending: items.filter((c) => ["SENT", "COUNTERED", "BUYER_APPROVAL_PENDING"].includes(c.state)).length }), [items]);

  return (
    <div className="workspace">
      <aside className="pane queue" aria-label="Exception queue">
        <div className="pane-head" style={{ flexDirection: "column", alignItems: "stretch" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <h2>Exception queue</h2><div style={{ flex: 1 }} />
            <span className="small muted">{counts.open} open · {counts.pending} pending</span>
          </div>
          <input className="field" placeholder="Search case or part" aria-label="Search cases" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="field" aria-label="Saved view" value={state} onChange={(e) => setState(e.target.value)}>
            {VIEWS.map(([label, v]) => <option key={label} value={v}>{label}</option>)}
          </select>
        </div>
        <ul className="queue-list" role="listbox" aria-label="Cases">
          {items.map((c) => (
            <li key={c.case_id} role="option" aria-selected={c.case_id === caseId} className="queue-item"
                onClick={() => nav(`/cases/${c.case_id}/${mode}`)}>
              <span className="id">{c.case_id}</span>
              <StatusTag value={c.state} />
              <span className="title" title={c.title}>{c.title}</span>
              <span className="small muted">impact {c.impact_score ?? "—"} · v{c.input_version}</span>
            </li>
          ))}
          {cases.isLoading && <li className="empty">Loading…</li>}
          {!cases.isLoading && items.length === 0 && <li className="empty">No cases in this view.</li>}
        </ul>
        <div className="small muted" style={{ padding: 8, borderTop: "1px solid var(--border)" }}>↑/↓ or j/k to move · {me.tenant_scopes.join(", ")}</div>
      </aside>
      {caseId ? <CaseWorkspace caseId={caseId} mode={mode} me={me} /> : <div className="case-area"><div className="empty">Select a case from the queue.</div></div>}
    </div>
  );
}

function CaseWorkspace({ caseId, mode, me }: { caseId: string; mode: string; me: Me }) {
  const qc = useQueryClient();
  const detail = useQuery({ queryKey: ["case", caseId], queryFn: () => api<CaseDetail>(`/cases/${caseId}`) });
  const runs = useQuery({
    queryKey: ["runs", caseId], queryFn: () => api<{ items: Run[] }>(`/cases/${caseId}/scenario-runs`),
    refetchInterval: (q) => (q.state.data?.items.some((r) => ["QUEUED", "RUNNING", "VALIDATING"].includes(r.state)) ? 1000 : false),
  });
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [selectedMode, setSelectedMode] = useState<string>("hybrid");
  useEffect(() => { setSelectedRun(null); }, [caseId]);
  const latestDone = runs.data?.items.find((r) => r.state === "COMPLETED");
  // A finished run can move the case state (e.g. to SCENARIOS_READY); refresh header and queue when it lands.
  useEffect(() => {
    if (latestDone?.run_id) { qc.invalidateQueries({ queryKey: ["case", caseId] }); qc.invalidateQueries({ queryKey: ["cases"] }); }
  }, [latestDone?.run_id, caseId, qc]);
  const runId = selectedRun ?? latestDone?.run_id ?? null;
  const result = useQuery({ queryKey: ["results", runId], enabled: !!runId, queryFn: () => api<Run>(`/scenario-runs/${runId}/results`) });

  if (detail.isError) return <div className="case-area"><div className="empty">Case not found or not accessible.</div></div>;
  const c = detail.data?.case;
  return (
    <>
      <div className="case-area">
        <div className="case-head">
          <div className="row1">
            <h1><span className="mono">{caseId}</span> {c?.title}</h1>
            {c && <StatusTag value={c.state} />}
            {c && <span className="chip">{c.category?.replace(/_/g, " ").toLowerCase()}</span>}
            {c && <span className="chip mono" title="Input version: changes when supplier capacity or counteroffers change inputs">inputs v{c.input_version}</span>}
            {detail.data?.disruption && <span className="chip">first window {detail.data.disruption.window[0]} → {detail.data.disruption.window.at(-1)}</span>}
          </div>
          <nav className="tabs" aria-label="Workspace mode">
            {["investigate", "simulate", "resolve"].map((m) => (
              <Link key={m} className={m === mode ? "active" : ""} to={`/cases/${caseId}/${m}`}>{m[0].toUpperCase() + m.slice(1)}</Link>
            ))}
          </nav>
        </div>
        <div className="case-body">
          {!detail.data && <div className="empty">Loading case…</div>}
          {detail.data && mode === "investigate" && <Investigate detail={detail.data} />}
          {detail.data && mode === "simulate" && (
            <Simulate detail={detail.data} me={me} runs={runs.data?.items ?? []} run={result.data} runId={runId}
                      setRunId={setSelectedRun} selectedMode={selectedMode} setSelectedMode={setSelectedMode} />
          )}
          {detail.data && mode === "resolve" && <Resolve detail={detail.data} me={me} runs={runs.data?.items ?? []} />}
        </div>
      </div>
      <ContextPanel detail={detail.data} run={result.data} mode={selectedMode} />
    </>
  );
}
