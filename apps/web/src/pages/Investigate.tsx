import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, CaseDetail, Graph, num } from "../api";
import { ImpactGraph, LedgerChart } from "../components/charts";
import { Section } from "../components/ui";

export function Investigate({ detail }: { detail: CaseDetail }) {
  const items = detail.snapshot_horizon.items;
  const [itemIdx, setItemIdx] = useState(0);
  const [node, setNode] = useState<string | null>(null);
  const graph = useQuery({ queryKey: ["impact", detail.case.case_id], queryFn: () => api<Graph>(`/network/impact?case_id=${detail.case.case_id}`) });
  const item = items[itemIdx];
  const ev = detail.disruption;
  const sel = graph.data?.nodes.find((n) => n.id === node);
  const selEdges = graph.data?.edges.filter((e) => e.source === node || e.target === node) ?? [];

  return (
    <div className="stack">
      <div className="grid2">
        <Section title="Disruption evidence">
          {ev ? (
            <dl className="kv">
              <dt>Event</dt><dd className="mono">{ev.disruption_id} · {String(ev.event_type)}</dd>
              <dt>Supplier</dt><dd className="mono">{String(ev.supplier_org_id)}</dd>
              <dt>Lane</dt><dd className="mono">{String(ev.lane_id)}</dd>
              <dt>Window</dt><dd>{ev.window.join(", ")}</dd>
              <dt>Capacity loss</dt><dd>{(Number(ev.capacity_loss_percent) * 100).toFixed(0)}%</dd>
              <dt>Demand increase</dt><dd>{(Number(ev.demand_increase_percent) * 100).toFixed(0)}%</dd>
              <dt>Lead-time extension</dt><dd>{String(ev.lead_time_extension_days)} d</dd>
              <dt>Confirmed</dt><dd>{ev.is_confirmed ? "confirmed" : "unconfirmed (forecast)"}</dd>
              <dt>Shared resource</dt><dd>{ev.has_resource_constraint ? "yes — one hour budget across lanes" : "no"}</dd>
            </dl>
          ) : <div className="muted">No disruption event recorded.</div>}
        </Section>
        <Section title="Case scope (curated fixture)">
          {detail.fixture ? (
            <>
              <table className="data">
                <thead><tr><th>Lane</th><th>Part</th><th className="n">Demand</th><th className="n">Usable</th><th className="n">Lane ceiling</th><th>Alternate</th><th className="n">Alt. units</th></tr></thead>
                <tbody>{detail.fixture.lines.map((l) => (
                  <tr key={l.lane_id}><td className="mono">{l.lane_id}</td><td className="mono">{l.part_id}</td><td className="n">{num(l.demand_units)}</td>
                    <td className="n">{num(l.usable_stock)}</td><td className="n">{num(l.lane_ceiling_units)}</td>
                    <td className="mono">{l.alternate_lane_id ?? "—"}</td><td className="n">{num(l.alternate_offered_units)}</td></tr>))}
                </tbody>
              </table>
              <p className="small muted">
                Disrupted week {detail.fixture.week_start}; alternate {detail.fixture.alternate_qualified ? "qualified" : "NOT qualified"},{" "}
                {detail.fixture.alternate_arrives_in_time ? "arrives in time" : "arrives too late"}; overtime {detail.fixture.overtime_available ? "offered" : "not offered"}.
                {detail.fixture.other_relationships_on_shared_resource > 0 && <> {detail.fixture.other_relationships_on_shared_resource} other relationship(s) share this resource (details withheld).</>}
              </p>
            </>
          ) : <div className="muted">No curated fixture.</div>}
        </Section>
      </div>

      <Section title="Time-phased supply — 12-week canonical snapshot"
               actions={items.length > 1 && (
                 <select className="field" aria-label="Item" value={itemIdx} onChange={(e) => setItemIdx(Number(e.target.value))}>
                   {items.map((it, i) => <option key={i} value={i}>{it.part_id} @ {it.plant_id}</option>)}
                 </select>)}>
        {item ? (
          <>
            <LedgerChart item={item} />
            <div className="form-row small" style={{ marginTop: 6 }}>
              <span>Opening usable <b className="num">{num(item.opening_usable)}</b></span>
              <span>Baseline first shortage <b>{item.baseline_first_shortage_week ?? "none"}</b></span>
              <span>Disrupted first shortage <b>{item.disrupted_first_shortage_week ?? "none"}</b></span>
              <span>Disrupted peak backlog <b className="num">{num(item.disrupted_peak_backlog)}</b></span>
            </div>
            {item.affected_receipts.length > 0 && (
              <details style={{ marginTop: 8 }}><summary>{item.affected_receipts.length} confirmed receipt(s) affected — source rows</summary>
                <table className="data"><thead><tr><th>Receipt</th><th>Lane</th><th>Arrival</th><th className="n">Planned</th><th className="n">After disruption</th></tr></thead>
                  <tbody>{item.affected_receipts.map((r) => <tr key={r.receipt_id}><td className="mono">{r.receipt_id}</td><td className="mono">{r.lane_id}</td><td>{r.arrival_week}</td><td className="n">{num(r.planned_units)}</td><td className="n">{num(r.disrupted_units)}</td></tr>)}</tbody>
                </table>
              </details>
            )}
            <p className="small muted">{detail.snapshot_horizon.note} Solver-free; the optimizer runs in Simulate.</p>
          </>
        ) : <div className="muted">No snapshot items for this tenant.</div>}
      </Section>

      <Section title="Affected network" actions={graph.data && <span className="small muted">{graph.data.nodes.length} nodes shown · {graph.data.hidden_nodes} hidden · limit {graph.data.max_nodes}</span>}>
        {graph.data && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 240px", gap: 12 }}>
            <ImpactGraph graph={graph.data} onSelect={setNode} />
            <div className="small">
              {sel ? (
                <div className="stack">
                  <div><b className="mono">{sel.id}</b> <span className="muted">{sel.kind.toLowerCase()}</span></div>
                  {sel.label !== sel.id && <div>{sel.label}</div>}
                  {sel.note && <div className="muted">{sel.note}</div>}
                  <table className="data"><tbody>{selEdges.map((e, i) => (
                    <tr key={i}><td>{e.kind.toLowerCase()}</td><td className="mono">{e.source === node ? e.target : e.source}</td>
                      <td>{e.lane_id ? <span className="mono">{e.lane_id}</span> : null}{e.role === "ALTERNATE" ? " alt" : ""}{e.lead_time_days ? ` · ${e.lead_time_days} d` : ""}</td></tr>))}
                  </tbody></table>
                </div>
              ) : <div className="muted">Select a node to inspect its relationships. Dashed edges are alternate lanes; red edges are shared-resource constraints.</div>}
              {graph.data.other_relationships_sharing_resource > 0 && <p className="notice">{graph.data.other_relationships_sharing_resource} lane(s) of other buyers share this resource; they are not shown.</p>}
              <p className="muted">{graph.data.completeness_note}</p>
            </div>
          </div>
        )}
      </Section>
    </div>
  );
}
