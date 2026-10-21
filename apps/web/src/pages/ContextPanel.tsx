import { CaseDetail, eur, Run } from "../api";
import { AgentPanel } from "../components/AgentPanel";
import { StatusTag } from "../components/ui";

export function ContextPanel({ detail, run, mode }: { detail?: CaseDetail; run?: Run; mode: string }) {
  if (!detail) return <aside className="pane context" aria-label="Context" />;
  const r = run?.results?.[mode];
  return (
    <aside className="pane context stack" aria-label="Context">
      <AgentPanel caseId={detail.case.case_id} />
      <div>
        <h3 className="small muted" style={{ textTransform: "uppercase", letterSpacing: ".06em", margin: "0 0 6px" }}>Case facts</h3>
        <dl className="kv">
          <dt>Tenant</dt><dd className="mono">{detail.case.tenant_id}</dd>
          <dt>Snapshot</dt><dd className="mono">{detail.case.snapshot_id}</dd>
          <dt>Input version</dt><dd>v{detail.case.input_version}</dd>
          <dt>Dataset</dt><dd>{detail.dataset}</dd>
          <dt>Suppliers in scope</dt><dd>{detail.supplier_org_ids.length}</dd>
          <dt>Seeded demo script</dt><dd>{detail.case.seeded_script_status ?? "—"}</dd>
        </dl>
      </div>
      <div>
        <h3 className="small muted" style={{ textTransform: "uppercase", letterSpacing: ".06em", margin: "8px 0 6px" }}>Restrictions</h3>
        <ul className="small" style={{ paddingLeft: 16, margin: 0 }}>
          <li>Supplier machine hours and internal costs are not visible to the buyer.</li>
          <li>Suppliers see only offers sent to them, never scenarios or other suppliers.</li>
          <li>Offers require a validated, non-stale plan; approvals reference an exact terms digest.</li>
          <li>No ERP write-back; exports are previews.</li>
        </ul>
      </div>
      {r && (
        <div>
          <h3 className="small muted" style={{ textTransform: "uppercase", letterSpacing: ".06em", margin: "8px 0 6px" }}>Selected plan · {mode}</h3>
          <dl className="kv">
            <dt>Status</dt><dd><StatusTag value={r.status} /></dd>
            <dt>Unmet at end</dt><dd>{r.kpis.unmet_units_at_end ?? "—"}</dd>
            <dt>Incremental cost</dt><dd>{eur(r.financials?.incremental_buyer_cost_eur)}</dd>
            <dt>Overtime premium</dt><dd>{eur(r.financials?.overtime_premium_eur)}</dd>
            <dt>Alternate price delta</dt><dd>{eur(r.financials?.alternate_price_delta_eur)}</dd>
            <dt>Holding cost</dt><dd>{eur(r.financials?.holding_cost_eur)}</dd>
            <dt>Working capital peak</dt><dd>{eur(r.financials?.working_capital_peak_eur)}</dd>
            <dt>Exposure proxy</dt><dd>{eur(r.financials?.shortage_exposure_proxy_eur)}</dd>
            <dt>Joint resource cost</dt><dd className="small">not computed (Mode A)</dd>
          </dl>
          {r.binding_constraints.length > 0 && <div className="notice small" style={{ marginTop: 6 }}>{r.binding_constraints.join("; ")}</div>}
        </div>
      )}
    </aside>
  );
}
