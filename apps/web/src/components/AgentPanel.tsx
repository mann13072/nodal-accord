import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { Markdown, quotedText, toPlainText } from "./Markdown";
import { ErrorNote, StatusTag } from "./ui";

type AgentStatus = { enabled: boolean; provider: string | null; model: string | null; requires_access_code: boolean; disclosure: string };
type TraceItem = { tool: string; arguments: string; ok: boolean; output_chars: number; ms: number; redacted_fields?: string[]; truncated?: boolean };
type AgentRun = { agent_run_id: string; state: string; answer: string | null; trace: TraceItem[]; unverified_numbers: string[];
  error: string | null; model: string | null };

const CODE_KEY = "nodal.ai_code";
const SUGGESTIONS: [string, string][] = [
  ["Why is it short?", "Explain why this case is short"],
  ["Compare latest run", "Compare the latest scenario run"],
  ["Draft supplier message", "Draft a short message to the supplier for the best plan"],
];

function readCode() { try { return sessionStorage.getItem(CODE_KEY) || ""; } catch { return ""; } }

/** Optional AI assistant. Read/explain only: it cannot send, accept or approve anything. */
export function AgentPanel({ caseId }: { caseId: string }) {
  const status = useQuery({ queryKey: ["agent-status"], queryFn: () => api<AgentStatus>("/agent/status"), staleTime: 60_000 });
  const [question, setQuestion] = useState("");
  const [code, setCode] = useState(readCode);
  const [editCode, setEditCode] = useState(() => !readCode());
  const [runId, setRunId] = useState<string | null>(null);
  useEffect(() => { setRunId(null); }, [caseId]);

  const ask = useMutation({
    mutationFn: (q: string) => api<{ agent_run_id: string }>("/agent/ask", { method: "POST", json: { question: q, case_id: caseId },
      headers: code ? { "X-AI-Access-Code": code } : {} }),
    onSuccess: (r) => {
      try { if (code) sessionStorage.setItem(CODE_KEY, code); } catch { /* session-only convenience */ }
      setEditCode(false);
      setRunId(r.agent_run_id);
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 403) {
        try { sessionStorage.removeItem(CODE_KEY); } catch { /* ignore */ }
        setEditCode(true);
      }
    },
  });
  const run = useQuery({
    queryKey: ["agent-run", runId], enabled: !!runId, queryFn: () => api<AgentRun>(`/agent/runs/${runId}`),
    refetchInterval: (q) => (["QUEUED", "RUNNING"].includes(q.state.data?.state ?? "QUEUED") ? 1000 : false),
  });

  if (!status.data) return null;
  if (!status.data.enabled) {
    return <div className="small muted">AI assistant: off on this deployment (no API key configured). Everything else works without it.</div>;
  }
  const s = status.data;
  const r = run.data;
  const busy = ask.isPending || (r && ["QUEUED", "RUNNING"].includes(r.state));
  const needCode = s.requires_access_code && !code.trim();
  const submit = (q: string) => { if (q.trim().length >= 3 && !needCode) { setQuestion(q); ask.mutate(q.trim()); } };
  const wrongCode = ask.error instanceof ApiError && ask.error.status === 403;

  return (
    <div className="ai stack" aria-label="AI assistant">
      <div className="ai-head">
        <h3 className="pane-title">Ask AI</h3>
        <span className="tag gray" title="Model">{s.model}</span>
      </div>

      {s.requires_access_code && (editCode ? (
        <input className="field" type="password" placeholder="Access code (from the demo owner)" aria-label="AI access code"
               value={code} onChange={(e) => setCode(e.target.value)} autoComplete="new-password" />
      ) : (
        <div className="small muted">Access code set for this tab · <button className="linkish" onClick={() => setEditCode(true)}>change</button></div>
      ))}

      <textarea className="field ai-q" maxLength={1000} rows={2} placeholder={`Ask about ${caseId}…`} aria-label="Question" value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit(question); }} />
      <div className="ai-actions">
        <button className="btn primary sm" disabled={busy || needCode || question.trim().length < 3} onClick={() => submit(question)}
                title={needCode ? "Enter the access code first" : "Ctrl+Enter"}>Ask</button>
        {SUGGESTIONS.map(([label, q]) => (
          <button key={label} className="chip-btn" disabled={busy || needCode} onClick={() => submit(q)} title={q}>{label}</button>))}
      </div>

      {wrongCode
        ? <div className="notice err small" role="alert">That access code was not accepted. Clear the field and type it by hand; browser autofill can insert a saved password.</div>
        : <ErrorNote error={ask.error} />}

      {busy && <div className="small muted">Thinking with tools…</div>}
      {r && !busy && (
        <div className="ai-answer">
          {r.state !== "COMPLETED" && <div className="small"><StatusTag value={r.state === "STOPPED" ? "TIME_LIMIT" : r.state} /></div>}
          {r.error && <div className="notice err small">{r.error}</div>}
          {r.answer && <Markdown text={r.answer} />}
          {r.unverified_numbers.length > 0 && (
            <div className="notice warn small">Unverified numbers (not found in any tool result): {r.unverified_numbers.join(", ")}. Check them in the workbench.</div>
          )}
          {r.answer && <CopyButtons answer={r.answer} />}
          {r.trace.length > 0 && (
            <details><summary>How it answered ({r.trace.length} tool call{r.trace.length === 1 ? "" : "s"})</summary>
              <ul className="small" style={{ paddingLeft: 16, margin: "4px 0" }}>
                {r.trace.map((t, i) => <li key={i}><span className="mono">{t.tool}</span> {t.ok ? "✓" : "✗"} <span className="muted mono">{t.arguments}</span>
                  {t.redacted_fields?.length ? <span className="tag amber">redacted {t.redacted_fields.length}</span> : null}</li>)}
              </ul></details>
          )}
        </div>
      )}

      <p className="small muted" style={{ margin: 0 }} title={s.disclosure}>
        Your question and the case data you can see are sent to {s.provider ?? "the AI provider"}. Read-only: it cannot send, accept or approve offers.
      </p>
    </div>
  );
}

function CopyButtons({ answer }: { answer: string }) {
  const [copied, setCopied] = useState<string | null>(null);
  const quote = quotedText(answer);
  const copy = async (label: string, text: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(label); setTimeout(() => setCopied(null), 1500); } catch { setCopied("failed"); }
  };
  return (
    <div className="ai-actions">
      {quote && <button className="btn sm" onClick={() => copy("draft", quote)}>{copied === "draft" ? "Copied ✓" : "Copy draft"}</button>}
      <button className="btn sm" onClick={() => copy("answer", toPlainText(answer))}>{copied === "answer" ? "Copied ✓" : "Copy answer"}</button>
      {copied === "failed" && <span className="small muted">Copy not allowed by the browser; select the text instead.</span>}
    </div>
  );
}
