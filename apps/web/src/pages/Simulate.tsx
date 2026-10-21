import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, CaseDetail, eur, Me, ModeResult, num, Run } from "../api";
import { ErrorNote, Section, StatusTag } from "../components/ui";

const MODES = ["baseline", "overtime", "alternate", "prebuild", "hybrid"] as const;
const MODE_LABEL: Record<string, string> = { baseline: "Baseline", overtime: "Overtime", alternate: "Alternate source", prebuild: "Prebuild", hybrid: "Hybrid (OT + alt.)" };

type Props = { detail: CaseDetail; me: Me; runs: Run[]; run?: Run; runId: string | null; setRunId: (id: string) => void;
  selectedMode: string; setSelectedMode: (m: string) => void };

export function Simulate({ detail, me, runs, run, runId, setRunId, selectedMode, setSelectedMode }: Props) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const caseId = detail.case.case_id;
  const [modes, setModes] = useState<string[]>([...MODES]);
  const [scope, setScope] = useState("CASE_FIXTURE");
  const [budget, setBudget] = useState("");
  const [zero, setZero] = useState(false);
  const [timeLimit, setTimeLimit] = useState(30);
  const canRun = ["BUYER_PLANNER", "BUYER_PROCUREMENT", "BUYER_FINANCE"].includes(me.role);

  const submit = useMutation({
    mutationFn: () => api<{ run_id: string }>(`/cases/${caseId}/scenarios`, {
      method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
      json: { modes, scope, constraints: { max_incremental_cost_eur: budget || null, require_zero_shortage: zero },
              solver: { time_limit_seconds: timeLimit, max_relative_gap: scope === "SNAPSHOT_HORIZON" ? 0.01 : 0 } },
    }),
    onSuccess: (r) => { setRunId(r.run_id); qc.invalidateQueries({ queryKey: ["runs", caseId] }); qc.invalidateQueries({ queryKey: ["case", caseId] }); },
  });
  const active = runs.find((r) => r.run_id === runId);
  const pending = active && ["QUEUED", "RUNNING", "VALIDATING"].includes(active.state);
  const results = run?.run_id === runId ? run?.results : undefined;
  const shown = MODES.filter((m) => results?.[m]);
  const sel: ModeResult | undefined = results?.[selectedMode];
  const best = bestMode(results);

  return (
    <div className="stack">
      <Section title="Constraint editor" actions={<span className="small muted">Each run is an immutable job; inputs are never edited in place.</span>}>
        <div className="form-row">
          <fieldset style={{ border: "none", padding: 0, margin: 0 }}>
            <legend className="small muted">Mitigation options</legend>
            {MODES.map((m) => (
              <label key={m} className="check" style={{ marginRight: 10 }}>
                <input type="checkbox" checked={modes.includes(m)} onChange={(e) => setModes(e.target.checked ? [...modes, m] : modes.filter((x) => x !== m))} />
                {MODE_LABEL[m]}
              </label>))}
          </fieldset>
        </div>
        <div className="form-row" style={{ marginTop: 10 }}>
          <label className="lbl">Scope
            <select className="field" value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value="CASE_FIXTURE">Case fixture (disrupted week)</option>
              <option value="SNAPSHOT_HORIZON">12-week snapshot horizon</option>
            </select></label>
          <label className="lbl">Max incremental buyer cost (EUR)
            <input className="field" inputMode="decimal" placeholder="no cap" value={budget} onChange={(e) => setBudget(e.target.value.replace(/[^0-9.]/g, ""))} /></label>
          <label className="lbl">Solver time limit (s)
            <input className="field narrow" type="number" min={1} max={600} value={timeLimit} onChange={(e) => setTimeLimit(Number(e.target.value))} /></label>
          <label className="check"><input type="checkbox" checked={zero} onChange={(e) => setZero(e.target.checked)} /> Require zero shortage (hard)</label>
          <div style={{ flex: 1 }} />
          <button className="btn primary" disabled={!canRun || modes.length === 0 || submit.isPending} onClick={() => submit.mutate()}>
            {submit.isPending ? "Submitting…" : "Run comparison"}</button>
        </div>
        <ErrorNote error={submit.error} />
      </Section>

      <Section title="Runs" actions={pending && <span className="small"><StatusTag value={active!.state} /> solving in worker…</span>}>
        {runs.length === 0 ? <div className="muted">No scenario runs yet.</div> : (
          <table className="data">
            <thead><tr><th>Run</th><th>State</th><th>Status</th><th>Scope</th><th>Inputs</th><th className="n">Wall s</th><th>Requested</th></tr></thead>
            <tbody>{runs.slice(0, 8).map((r) => (
              <tr key={r.run_id} className={`clickable ${r.run_id === runId ? "sel" : ""}`} onClick={() => setRunId(r.run_id)}>
                <td className="mono">{r.run_id}</td><td><StatusTag value={r.state} /></td><td><StatusTag value={r.status} /></td>
                <td className="small">{String((r.request as { scope?: string }).scope ?? "")}</td>
                <td>v{r.input_version} {r.stale && <span className="tag amber" title="Inputs changed since this run">STALE</span>}</td>
                <td className="n">{r.wall_seconds ?? "—"}</td><td className="small muted">{r.requested_by}</td></tr>))}
            </tbody>
          </table>)}
      </Section>

      {results && (
        <Section title={`Comparison — ${runId}`} actions={active?.stale && <span className="tag amber">STALE: inputs changed, re-run before offering</span>}>
          <div style={{ overflowX: "auto" }}>
            <table className="data matrix">
              <thead><tr><th>KPI</th>{shown.map((m) => (
                <th key={m} className="n mode" style={{ cursor: "pointer", color: m === selectedMode ? "var(--accent)" : undefined }}
                    onClick={() => setSelectedMode(m)} aria-sort="none" scope="col">{MODE_LABEL[m]}{m === best ? " ★" : ""}</th>))}</tr></thead>
              <tbody>
                <Row label="Solution status" modes={shown} r={results} f={(x) => <StatusTag value={x.status} />} />
                <Row label="Units unmet at horizon end" modes={shown} r={results} f={(x) => num(x.kpis.unmet_units_at_end)} />
                <Row label="Late unit-weeks" modes={shown} r={results} f={(x) => num(x.kpis.late_unit_weeks)} />
                <Row label="Alternate-source units" modes={shown} r={results} f={(x) => num(x.kpis.alternate_units)} />
                <Row label="Overtime units" modes={shown} r={results} f={(x) => num(x.kpis.overtime_units)} />
                <Row label="Prebuild peak units" modes={shown} r={results} f={(x) => num(x.kpis.prebuild_peak_units)} />
                <Row label="Incremental buyer cost" modes={shown} r={results} f={(x) => eur(x.financials?.incremental_buyer_cost_eur)} title="Premiums + alternate price delta + holding cost, vs planned price" />
                <Row label="Purchase spend (horizon)" modes={shown} r={results} f={(x) => eur(x.financials?.purchase_spend_eur)} />
                <Row label="Holding cost" modes={shown} r={results} f={(x) => eur(x.financials?.holding_cost_eur)} />
                <Row label="Working capital peak" modes={shown} r={results} f={(x) => eur(x.financials?.working_capital_peak_eur)} title="Inventory balance, not an expense" />
                <Row label="Shortage exposure (proxy)" modes={shown} r={results} f={(x) => eur(x.financials?.shortage_exposure_proxy_eur)} title="Scenario assumption, not a validated loss" />
                <Row label="Earliest relief week" modes={shown} r={results} f={(x) => x.kpis.earliest_relief_week ?? "—"} />
                <Row label="Solver gap" modes={shown} r={results} f={(x) => (x.solver.relative_gap === null ? "—" : `${(x.solver.relative_gap * 100).toFixed(2)}%`)} />
                <Row label="Solve time (s)" modes={shown} r={results} f={(x) => x.solver.solver_wall_seconds.toFixed(2)} />
                <Row label="Binding constraints" modes={shown} r={results} f={(x) => (x.binding_constraints.length ? x.binding_constraints.length : "—")} />
              </tbody>
            </table>
          </div>
          <p className="small muted">★ = fewest unmet units, then lowest incremental buyer cost, among validated plans. Selection is a suggestion; humans decide.</p>
        </Section>
      )}

      {sel && (
        <Section title={`${MODE_LABEL[selectedMode]} — allocation and provenance`}
                 actions={sel.offer_eligible && !active?.stale && (
                   <button className="btn primary sm" onClick={() => nav(`/cases/${caseId}/resolve?run=${runId}&mode=${selectedMode}`)}>Draft offer from this plan</button>)}>
          {sel.message && <div className={`notice ${sel.status === "OPTIMAL" ? "" : "warn"}`}>{sel.message}</div>}
          {sel.diagnostics.length > 0 && <div className="notice err"><b>Diagnostics</b><ul>{sel.diagnostics.map((d, i) => <li key={i}>{d}</li>)}</ul></div>}
          {sel.validation_errors.length > 0 && <div className="notice err"><b>Validation failed — offers suppressed</b><ul>{sel.validation_errors.map((d, i) => <li key={i}>{d}</li>)}</ul></div>}
          {sel.warnings.map((w, i) => <div key={i} className="notice warn">{w}</div>)}
          {sel.releases.length > 0 && (
            <table className="data" style={{ marginTop: 8 }}>
              <thead><tr><th>Lane</th><th>Supplier</th><th>Role</th><th>Part</th><th>Release</th><th>Arrival</th><th className="n">Regular</th><th className="n">Overtime</th><th className="n">Unit price</th><th className="n">Disclosed premium</th></tr></thead>
              <tbody>{sel.releases.map((r, i) => (
                <tr key={i}><td className="mono">{r.lane_id}</td><td className="mono">{r.supplier_org_id}</td><td>{r.role.toLowerCase()}</td><td className="mono">{r.part_id}</td>
                  <td>{r.release_week}</td><td>{r.arrival_week}</td><td className="n">{num(r.regular_units)}</td><td className="n">{num(r.overtime_units)}</td>
                  <td className="n">{eur(r.unit_price_eur)}</td><td className="n">{eur(r.disclosed_premium_eur)}</td></tr>))}
              </tbody>
            </table>)}
          {sel.hidden_other_relationship_lines > 0 && <p className="small muted">{sel.hidden_other_relationship_lines} allocation line(s) belonging to other buyers on the shared resource are hidden.</p>}
          <details style={{ marginTop: 8 }}><summary>Assumptions, provenance and model size</summary>
            <ul className="small">{sel.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
            <table className="data"><thead><tr><th>Lane</th><th>Role</th><th>Qualified</th><th className="n">Lead wk</th><th>Source of price/premium</th></tr></thead>
              <tbody>{Object.entries(sel.lane_provenance).map(([k, v]) => (
                <tr key={k}><td className="mono">{k}</td><td>{v.role.toLowerCase()}</td><td>{v.qualified ? "yes" : "no"}</td><td className="n">{v.lead_weeks}</td><td className="small">{v.provenance}</td></tr>))}</tbody></table>
            <p className="small mono">model {JSON.stringify(sel.solver.model_size)} · stage1 {sel.solver.stage1_termination} · stage2 {sel.solver.stage2_termination} · input {sel.input_hash.slice(0, 20)}…</p>
            {sel.financials && <ul className="small muted">{sel.financials.basis.map((b, i) => <li key={i}>{b}</li>)}</ul>}
          </details>
        </Section>
      )}
    </div>
  );
}

function Row({ label, modes, r, f, title }: { label: string; modes: readonly string[]; r: Record<string, ModeResult>; f: (x: ModeResult) => React.ReactNode; title?: string }) {
  return <tr><th scope="row" title={title} style={{ fontWeight: 500, textTransform: "none", fontSize: 13, color: "var(--text)" }}>{label}</th>
    {modes.map((m) => <td key={m} className="n">{f(r[m])}</td>)}</tr>;
}

function bestMode(results?: Record<string, ModeResult>): string | null {
  if (!results) return null;
  const ok = Object.entries(results).filter(([, x]) => x.offer_eligible && x.kpis.unmet_units_at_end !== null);
  ok.sort(([, a], [, b]) => (a.kpis.unmet_units_at_end! - b.kpis.unmet_units_at_end!) ||
    (Number(a.financials?.incremental_buyer_cost_eur ?? 0) - Number(b.financials?.incremental_buyer_cost_eur ?? 0)));
  return ok[0]?.[0] ?? null;
}
