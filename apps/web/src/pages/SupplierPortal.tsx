import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, AuditItem, CaseSummary, eur, Me, num, Offer, SupplierCaseDetail } from "../api";
import { Digest, ErrorNote, Section, StatusTag } from "../components/ui";

export function SupplierPortal({ me }: { me: Me }) {
  const { caseId } = useParams();
  const nav = useNavigate();
  const cases = useQuery({ queryKey: ["cases", "supplier"], queryFn: () => api<{ items: CaseSummary[] }>("/cases") });
  return (
    <div className="workspace" style={{ gridTemplateColumns: "var(--queue) 1fr" }}>
      <aside className="pane queue" aria-label="Pending proposals">
        <div className="pane-head"><h2>Proposals for {me.org_name}</h2></div>
        <ul className="queue-list" role="listbox">
          {cases.data?.items.map((c) => (
            <li key={c.case_id} className="queue-item" role="option" aria-selected={c.case_id === caseId} onClick={() => nav(`/supplier/${c.case_id}`)}>
              <span className="id">{c.case_id}</span><StatusTag value={c.state} />
              <span className="title">{c.title} · from {c.buyer_org_id}</span>
            </li>))}
          {cases.data?.items.length === 0 && <li className="empty">No proposals have been sent to your organization.</li>}
        </ul>
      </aside>
      <div className="case-area"><div className="case-body">
        {caseId ? <SupplierCase caseId={caseId} me={me} /> : <div className="empty">Select a proposal.</div>}
      </div></div>
    </div>
  );
}

function SupplierCase({ caseId, me }: { caseId: string; me: Me }) {
  const qc = useQueryClient();
  const d = useQuery({ queryKey: ["supplier-case", caseId], queryFn: () => api<SupplierCaseDetail>(`/cases/${caseId}`) });
  const events = useQuery({ queryKey: ["events", caseId], queryFn: () => api<{ items: AuditItem[] }>(`/cases/${caseId}/events`) });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["supplier-case", caseId] }); qc.invalidateQueries({ queryKey: ["cases"] }); qc.invalidateQueries({ queryKey: ["events", caseId] }); };
  if (d.isError) return <div className="empty">Not found or not accessible.</div>;
  if (!d.data) return <div className="empty">Loading…</div>;
  return (
    <div className="stack">
      <h1 style={{ fontSize: 16, margin: 0 }}><span className="mono">{caseId}</span> capacity request from {d.data.case.buyer_org_id}</h1>
      <p className="small muted">You see only the terms shared with {me.org_name}, your own capacity, and your own private evaluation. The buyer cannot see your evaluation.</p>
      {d.data.offers.slice().reverse().map((o) => <SupplierOffer key={o.offer_id} offer={o} onChange={refresh} />)}
      <Section title="Activity visible to you">
        <ul className="timeline">{events.data?.items.map((e) => (
          <li key={e.event_id}><span className="small muted">{new Date(e.at).toLocaleString()}</span><span><b>{e.action}</b> · {e.actor_org} · {e.summary}</span></li>))}</ul>
      </Section>
    </div>
  );
}

function SupplierOffer({ offer, onChange }: { offer: Offer; onChange: () => void }) {
  const [counter, setCounter] = useState<Record<string, { qty: number; week: string; premium: string; days: number }> | null>(null);
  const [ack, setAck] = useState(false);
  const decide = useMutation({
    mutationFn: (decision: string) => api(`/offers/${offer.offer_id}/decisions`, { method: "POST",
      json: { decision, offer_version: offer.offer_version, terms_digest: offer.terms_digest } }), onSuccess: onChange });
  const sendCounter = useMutation({
    mutationFn: () => api(`/offers/${offer.offer_id}/counteroffers`, { method: "POST", json: {
      offer_version: offer.offer_version, constraint_acknowledgement: ack, reason_code: "CAPACITY_CHANGE",
      lines: Object.entries(counter!).map(([line_id, c]) => ({ line_id, countered_qty: c.qty, countered_delivery_week: c.week,
        countered_premium_eur: c.premium, countered_payment_days: c.days })) } }),
    onSuccess: () => { setCounter(null); onChange(); } });
  const live = offer.status === "SENT";
  const evalById = Object.fromEntries((offer.your_private_evaluation?.lines ?? []).map((l) => [String(l.line_id), l]));
  return (
    <Section title={`Offer v${offer.offer_version}`} actions={<><StatusTag value={offer.status} /><Digest value={offer.terms_digest} /></>}>
      <div className="small" style={{ marginBottom: 6 }}>Valid until {new Date(offer.expires_at).toLocaleString()} · premium total {eur(offer.premium_total_eur)}</div>
      <table className="data">
        <thead><tr><th>Line</th><th>Requested action</th><th>Lane</th><th>Part</th><th>Delivery week</th><th className="n">Qty</th><th className="n">Premium / unit</th><th className="n">Payment days</th><th className="n">Your contribution*</th></tr></thead>
        <tbody>{offer.lines.map((l) => {
          const c = counter?.[l.line_id];
          return (
            <tr key={l.line_id}><td>{l.line_id}</td><td>{l.kind.replace(/_/g, " ").toLowerCase()}</td><td className="mono">{l.lane_id}</td><td className="mono">{l.part_id}</td>
              {c ? (<>
                <td><input className="field" style={{ width: 120 }} value={c.week} aria-label="Delivery week" onChange={(e) => setCounter({ ...counter!, [l.line_id]: { ...c, week: e.target.value } })} /></td>
                <td className="n"><input className="field narrow" type="number" min={0} value={c.qty} aria-label="Quantity" onChange={(e) => setCounter({ ...counter!, [l.line_id]: { ...c, qty: Number(e.target.value) } })} /></td>
                <td className="n"><input className="field narrow" value={c.premium} aria-label="Premium" onChange={(e) => setCounter({ ...counter!, [l.line_id]: { ...c, premium: e.target.value } })} /></td>
                <td className="n"><input className="field narrow" type="number" value={c.days} aria-label="Payment days" onChange={(e) => setCounter({ ...counter!, [l.line_id]: { ...c, days: Number(e.target.value) } })} /></td></>) : (<>
                <td>{l.delivery_week}</td><td className="n">{num(l.additional_qty)}</td><td className="n">{eur(l.unit_premium_eur)}</td><td className="n">{l.payment_days}</td></>)}
              <td className="n">{evalById[l.line_id]?.your_contribution_on_premium_eur != null ? eur(String(evalById[l.line_id].your_contribution_on_premium_eur)) : "—"}</td>
            </tr>);
        })}</tbody>
      </table>
      <p className="small muted">* {offer.your_private_evaluation?.note}</p>
      {offer.your_lane_capacity && offer.your_lane_capacity.length > 0 && (
        <details><summary>Your confirmed lane capacity for the requested weeks</summary>
          <table className="data"><thead><tr><th>Lane</th><th>Week</th><th className="n">Committed</th><th className="n">Offered flex</th></tr></thead>
            <tbody>{offer.your_lane_capacity.map((c, i) => <tr key={i}><td className="mono">{String(c.lane_id)}</td><td>{String(c.week)}</td><td className="n">{String(c.committed_units)}</td><td className="n">{String(c.supplier_offered_flex_units)}</td></tr>)}</tbody></table>
        </details>)}
      {live && !counter && (
        <div className="form-row" style={{ marginTop: 8 }}>
          <button className="btn primary" disabled={decide.isPending} onClick={() => decide.mutate("ACCEPT")}>Accept exact terms</button>
          <button className="btn" onClick={() => setCounter(Object.fromEntries(offer.lines.map((l) => [l.line_id, { qty: l.additional_qty, week: l.delivery_week, premium: l.unit_premium_eur, days: l.payment_days }])))}>Counteroffer…</button>
          <button className="btn danger" disabled={decide.isPending} onClick={() => decide.mutate("REJECT")}>Reject</button>
        </div>)}
      {counter && (
        <div className="form-row" style={{ marginTop: 8 }}>
          <label className="check"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I confirm this reflects a real change in our feasible capacity or terms.</label>
          <button className="btn primary" disabled={!ack || sendCounter.isPending} onClick={() => sendCounter.mutate()}>Send counteroffer</button>
          <button className="btn" onClick={() => setCounter(null)}>Cancel</button>
        </div>)}
      <ErrorNote error={decide.error || sendCounter.error} />
      <p className="small muted">Acceptance is a workflow acceptance, not a legally binding electronic signature.</p>
    </Section>
  );
}
