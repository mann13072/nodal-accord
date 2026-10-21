import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorNote, StatusTag } from "./ui";

type AgentStatus = { enabled: boolean; provider: string | null; model: string | null; requires_access_code: boolean; disclosure: string };
type TraceItem = { tool: string; arguments: string; ok: boolean; output_chars: number; ms: number; redacted_fields?: string[]; truncated?: boolean };
type AgentRun = { agent_run_id: string; state: string; answer: string | null; trace: TraceItem[]; unverified_numbers: string[];
  error: string | null; model: string | null };

const CODE_KEY = "nodal.ai_code";
const SUGGESTIONS = ["Explain why this case is short", "Compare the latest scenario run", "Draft a short message to the supplier for the best plan"];

function readCode() { try { return sessionStorage.getItem(CODE_KEY) || ""; } catch { return ""; } }

/** Optional AI assistant. Read/explain only: it cannot send, accept or approve anything. */
export function AgentPanel({ caseId }: { caseId: string }) {
  const status = useQuery({ queryKey: ["agent-status"], queryFn: () => api<AgentStatus>("/agent/status"), staleTime: 60_000 });
  const [question, setQuestion] = useState("");
  const [code, setCode] = useState(readCode);
  const [runId, setRunId] = useState<string | null>(null);
  useEffect(() => { setRunId(null); }, [caseId]);

  const ask = useMutation({
    mutationFn: (q: string) => {
      try { if (code) sessionStorage.setItem(CODE_KEY, code); } catch { /* session-only convenience */ }
      return api<{ agent_run_id: string }>("/agent/ask", { method: "POST", json: { question: q, case_id: caseId },
        headers: code ? { "X-AI-Access-Code": code } : {} });
    },
    onSuccess: (r) => setRunId(r.agent_run_id),
  });
  const run = useQuery({
    queryKey: ["agent-run", runId], enabled: !!runId, queryFn: () => api<AgentRun>(`/agent/runs/${runId}`),
    refetchInterval: (q) => (["QUEUED", "RUNNING"].includes(q.state.data?.state ?? "QUEUED") ? 1000 : false),
  });

  if (!status.data) return null;
  if (!status.data.enabled) {
    return <div className="small muted">AI assistant: off on this deployment (no API key configured). Everything else works without it.</div>;
  }
  const r = run.data;
  const busy = ask.isPending || (r && ["QUEUED", "RUNNING"].includes(r.state));
  const submit = (q: string) => { if (q.trim().length >= 3) { setQuestion(q); ask.mutate(q.trim()); } };
  return (
    <div className="stack" aria-label="AI assistant">
      <h3 className="small muted" style={{ textTransform: "uppercase", letterSpacing: ".06em", margin: 0 }}>
        Ask AI <span className="tag gray" title="Model">{status.data.model}</span>
      </h3>
      {status.data.requires_access_code && (
        <input className="field" type="password" placeholder="AI access code (from the demo owner)" aria-label="AI access code"
               value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off" />
      )}
      <textarea className="field" style={{ height: 64, padding: 6, width: "100%", resize: "vertical" }} maxLength={1000}
                placeholder={`Ask about ${caseId}…`} aria-label="Question" value={question} onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit(question); }} />
      <div className="form-row" style={{ gap: 6 }}>
        <button className="btn primary sm" disabled={busy || question.trim().length < 3} onClick={() => submit(question)}>Ask</button>
        {SUGGESTIONS.map((s) => <button key={s} className="btn sm" disabled={busy} onClick={() => submit(s)} title={s}>{s.split(" ").slice(0, 3).join(" ")}…</button>)}
      </div>
      <ErrorNote error={ask.error} />
      {r && (
        <div className="stack">
          <div className="small">{busy ? <span className="muted">Thinking with tools…</span> : <StatusTag value={r.state === "STOPPED" ? "TIME_LIMIT" : r.state} />}</div>
          {r.error && <div className="notice err small">{r.error}</div>}
          {r.answer && <div className="small" style={{ whiteSpace: "pre-wrap", lineHeight: 1.45 }}>{r.answer}</div>}
          {r.unverified_numbers.length > 0 && (
            <div className="notice warn small">Unverified numbers (not found in any tool result): {r.unverified_numbers.join(", ")}. Check them in the workbench.</div>
          )}
          {r.trace.length > 0 && (
            <details><summary>Tool trace ({r.trace.length})</summary>
              <ul className="small" style={{ paddingLeft: 16, margin: "4px 0" }}>
                {r.trace.map((t, i) => <li key={i}><span className="mono">{t.tool}</span> {t.ok ? "✓" : "✗"} <span className="muted mono">{t.arguments}</span>
                  {t.redacted_fields?.length ? <span className="tag amber">redacted {t.redacted_fields.length}</span> : null}</li>)}
              </ul></details>
          )}
        </div>
      )}
      <p className="small muted" style={{ margin: 0 }}>{status.data.disclosure} The assistant cannot send, accept or approve offers.</p>
    </div>
  );
}
