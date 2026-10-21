import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment } from "react";
import { Link } from "react-router-dom";
import { Agreement, api, AuditItem, CaseSummary, isBuyer, Me, num } from "../api";
import { ErrorNote, Section, StatusTag } from "../components/ui";
import { AgreementCard } from "./Resolve";

export function NetworkPage() {
  const s = useQuery({ queryKey: ["network-summary"], queryFn: () => api<Record<string, number | string | string[]>>("/network/summary") });
  return (
    <div className="page">
      <h1>Supplier network</h1>
      <Section title="Authorized network summary">
        {s.data && <dl className="kv" style={{ maxWidth: 420 }}>
          {["suppliers", "parts", "plants", "lanes", "qualified_lanes"].map((k) => <Fragment key={k}><dt>{k.replace("_", " ")}</dt><dd>{num(Number(s.data[k]))}</dd></Fragment>)}
          <dt>Tenants</dt><dd>{(s.data.tenant_ids as string[]).join(", ")}</dd><dt>Dataset</dt><dd>{String(s.data.dataset)}</dd>
        </dl>}
        <p className="small muted">The full network is never rendered at once. Open a case to explore its bounded, authorized impact subgraph.</p>
      </Section>
    </div>
  );
}

export function AgreementsPage({ me }: { me: Me }) {
  const qc = useQueryClient();
  const a = useQuery({ queryKey: ["agreements"], queryFn: () => api<{ items: Agreement[] }>("/agreements") });
  return (
    <div className="page">
      <h1>Agreements</h1>
      {a.data?.items.length === 0 && <div className="empty">No agreements yet.</div>}
      <div className="stack">
        {a.data?.items.map((ag) => (
          <div key={ag.agreement_id}>
            <div className="small" style={{ marginBottom: 4 }}>{isBuyer(me.role) ? <Link to={`/cases/${ag.case_id}/resolve`} className="mono">{ag.case_id}</Link> : <span className="mono">{ag.case_id}</span>} · supplier {ag.supplier_org_id} · premium €{ag.premium_total_eur}</div>
            <AgreementCard ag={ag} me={me} onChange={() => qc.invalidateQueries({ queryKey: ["agreements"] })} />
          </div>))}
      </div>
    </div>
  );
}

export function AuditPage() {
  const cases = useQuery({ queryKey: ["cases", "", ""], queryFn: () => api<{ items: CaseSummary[] }>("/cases?limit=500") });
  const active = (cases.data?.items ?? []).filter((c) => c.state !== "DETECTED").slice(0, 20);
  return (
    <div className="page">
      <h1>Audit trail</h1>
      <p className="small muted">Append-only application events for cases you are authorized to see. Payloads are stored as digests; private values are never logged.</p>
      {active.length === 0 && <div className="empty">No activity yet.</div>}
      {active.map((c) => <CaseAudit key={c.case_id} c={c} />)}
    </div>
  );
}

function CaseAudit({ c }: { c: CaseSummary }) {
  const e = useQuery({ queryKey: ["events", c.case_id], queryFn: () => api<{ items: AuditItem[] }>(`/cases/${c.case_id}/events`) });
  return (
    <Section title={`${c.case_id} · ${c.title}`} actions={<StatusTag value={c.state} />}>
      <table className="data"><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Resource</th><th>Decision</th><th>Summary</th></tr></thead>
        <tbody>{e.data?.items.map((x) => <tr key={x.event_id}><td className="small">{new Date(x.at).toLocaleString()}</td><td className="small mono">{x.actor_id}</td>
          <td>{x.action}</td><td className="mono small">{x.resource_id}</td><td><StatusTag value={x.decision} /></td><td className="small">{x.summary}</td></tr>)}</tbody></table>
    </Section>
  );
}

type ImportResult = { import_id: string; connector: string; status: string; accepted_count: number; rejected_count: number; payload_checksum: string;
  idempotent_replay?: boolean; report: { entities: { entity: string; accepted: number; quarantined: number; reasons: Record<string, number> }[];
  reconciliation: { entity: string; matched: number; differences: number; missing_in_canonical: number }[]; note: string } };

export function ImportsPage() {
  const run = useMutation({ mutationFn: (connector: string) => api<ImportResult>("/imports", { method: "POST", json: { connector, dry_run: true } }) });
  const r = run.data;
  return (
    <div className="page">
      <h1>Integrations</h1>
      <Section title="Mock connectors" actions={<span className="small muted">Illustrative schemas only — not real ERP or SupplyOn payloads.</span>}>
        <div className="form-row">
          <button className="btn" onClick={() => run.mutate("mock_erp")} disabled={run.isPending}>Validate mock ERP feed</button>
          <button className="btn" onClick={() => run.mutate("mock_collaboration")} disabled={run.isPending}>Validate mock collaboration feed</button>
        </div>
        <ErrorNote error={run.error} />
      </Section>
      {r && (
        <Section title={`Import ${r.import_id} · ${r.connector}`} actions={<><StatusTag value={r.status === "COMMITTED_DRY_RUN" ? "COMPLETED" : r.status} />{r.idempotent_replay && <span className="tag gray">IDEMPOTENT REPLAY</span>}</>}>
          <div className="small mono">{r.payload_checksum}</div>
          <table className="data" style={{ marginTop: 8 }}><thead><tr><th>Entity</th><th className="n">Accepted</th><th className="n">Quarantined</th><th>Reason codes</th><th className="n">Matched canonical</th><th className="n">Differences</th></tr></thead>
            <tbody>{r.report.entities.map((e) => {
              const rc = r.report.reconciliation.find((x) => x.entity === e.entity);
              return <tr key={e.entity}><td>{e.entity}</td><td className="n">{num(e.accepted)}</td><td className="n">{num(e.quarantined)}</td>
                <td className="small">{Object.entries(e.reasons).map(([k, v]) => `${k}: ${v}`).join(", ") || "—"}</td>
                <td className="n">{num(rc?.matched)}</td><td className="n">{num(rc?.differences)}</td></tr>;
            })}</tbody></table>
          <p className="small muted">{r.report.note}</p>
        </Section>)}
    </div>
  );
}
