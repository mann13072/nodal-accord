import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Agreement, api, CaseDetail, Counter, eur, Me, num, Offer, OfferLine, Run } from "../api";
import { Digest, ErrorNote, Section, StatusTag } from "../components/ui";

type OffersResp = { items: Offer[]; counteroffers: Counter[]; agreements: Agreement[] };

export function Resolve({ detail, me, runs }: { detail: CaseDetail; me: Me; runs: Run[] }) {
  const qc = useQueryClient();
  const caseId = detail.case.case_id;
  const [params] = useSearchParams();
  const offers = useQuery({ queryKey: ["offers", caseId], queryFn: () => api<OffersResp>(`/cases/${caseId}/offers`) });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["offers", caseId] }); qc.invalidateQueries({ queryKey: ["case", caseId] });
    qc.invalidateQueries({ queryKey: ["cases"] }); qc.invalidateQueries({ queryKey: ["runs", caseId] }); };

  const usable = runs.filter((r) => r.state === "COMPLETED" && !r.stale);
  const [runId, setRunId] = useState(params.get("run") ?? usable[0]?.run_id ?? "");
  const [mode, setMode] = useState(params.get("mode") ?? "hybrid");
  const [recipient, setRecipient] = useState("");
  const [hours, setHours] = useState(72);
  useEffect(() => { if (!runId && usable[0]) setRunId(usable[0].run_id); }, [usable, runId]);
  const result = useQuery({ queryKey: ["results", runId], enabled: !!runId, queryFn: () => api<Run>(`/scenario-runs/${runId}/results`) });
  const modeRes = result.data?.results?.[mode];
  const candidates = useMemo(() => {
    const s = new Set<string>();
    modeRes?.releases.forEach((r) => { if (r.role === "ALTERNATE" || r.overtime_units > 0 || mode === "prebuild") s.add(r.supplier_org_id); });
    return [...s];
  }, [modeRes, mode]);
  useEffect(() => { if (!candidates.includes(recipient)) setRecipient(candidates[0] ?? ""); }, [candidates, recipient]);

  const draft = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<Offer>(`/cases/${caseId}/offers`, { method: "POST", json: body }),
    onSuccess: refresh,
  });
  const canDraft = ["BUYER_PLANNER", "BUYER_PROCUREMENT"].includes(me.role);
  const groups = useMemo(() => {
    const g: Record<string, Offer[]> = {};
    offers.data?.items.forEach((o) => { (g[o.offer_group_id] ||= []).push(o); });
    return Object.entries(g);
  }, [offers.data]);

  return (
    <div className="stack">
      <Section title="Offer composer" actions={<span className="small muted">Only shareable terms are included: quantities, weeks, premiums, payment days. Internal penalties and supplier costs never appear.</span>}>
        {usable.length === 0 ? <div className="notice warn">No current (non-stale) completed scenario run. Run a comparison in Simulate first.</div> : (
          <>
            <div className="form-row">
              <label className="lbl">Scenario run
                <select className="field" value={runId} onChange={(e) => setRunId(e.target.value)}>
                  {usable.map((r) => <option key={r.run_id} value={r.run_id}>{r.run_id} · {r.status}</option>)}
                </select></label>
              <label className="lbl">Plan
                <select className="field" value={mode} onChange={(e) => setMode(e.target.value)}>
                  {Object.entries(result.data?.results ?? {}).map(([m, r]) => <option key={m} value={m} disabled={!r.offer_eligible}>{m} · {r.status}{r.offer_eligible ? "" : " (not offerable)"}</option>)}
                </select></label>
              <label className="lbl">Supplier
                <select className="field" value={recipient} onChange={(e) => setRecipient(e.target.value)}>
                  {candidates.length === 0 && <option value="">— plan requests no supplier action —</option>}
                  {candidates.map((s) => <option key={s} value={s}>{s} · {detail.suppliers.find((x) => x.org_id === s)?.display_name ?? ""}</option>)}
                </select></label>
              <label className="lbl">Validity (hours)
                <input className="field narrow" type="number" min={1} max={720} value={hours} onChange={(e) => setHours(Number(e.target.value))} /></label>
              <button className="btn primary" disabled={!canDraft || !recipient || !modeRes?.offer_eligible || draft.isPending}
                      onClick={() => draft.mutate({ run_id: runId, mode, recipient_org_id: recipient, expires_in_hours: hours })}>Draft offer</button>
            </div>
            {modeRes && !modeRes.offer_eligible && <div className="notice warn" style={{ marginTop: 8 }}>This plan has status {modeRes.status}; only validated feasible plans can become offers.</div>}
            <ErrorNote error={draft.error} />
          </>
        )}
      </Section>

      {groups.length === 0 && <div className="empty">No offers yet for this case.</div>}
      {groups.map(([gid, versions]) => (
        <OfferGroup key={gid} versions={versions} me={me} caseId={caseId} counters={offers.data!.counteroffers}
                    agreements={offers.data!.agreements} onChange={refresh} />
      ))}
    </div>
  );
}

function OfferGroup({ versions, me, caseId, counters, agreements, onChange }: { versions: Offer[]; me: Me; caseId: string;
  counters: Counter[]; agreements: Agreement[]; onChange: () => void }) {
  const latest = versions[versions.length - 1];
  const [edit, setEdit] = useState<OfferLine[] | null>(null);
  const send = useMutation({ mutationFn: (o: Offer) => api(`/offers/${o.offer_id}/send`, { method: "POST", json: { terms_digest: o.terms_digest } }), onSuccess: onChange });
  const revise = useMutation({
    mutationFn: (lines: OfferLine[]) => api(`/cases/${caseId}/offers`, { method: "POST", json: {
      run_id: latest.source_run_id, mode: latest.source_mode, recipient_org_id: latest.recipient_org_id,
      offer_group_id: latest.offer_group_id, lines: lines.map((l) => ({ kind: l.kind, lane_id: l.lane_id, delivery_week: l.delivery_week,
        additional_qty: l.additional_qty, unit_premium_eur: l.unit_premium_eur, payment_days: l.payment_days })) } }),
    onSuccess: () => { setEdit(null); onChange(); },
  });
  return (
    <Section title={`Offer ${latest.offer_group_id} → ${latest.recipient_org_id}`} actions={<StatusTag value={latest.status} />}>
      {versions.slice().reverse().map((o) => {
        const ag = agreements.find((a) => a.offer_id === o.offer_id);
        const co = counters.filter((c) => c.parent_offer_id === o.offer_id);
        const lines = edit && o === latest ? edit : o.lines;
        return (
          <div key={o.offer_id} className="stack" style={{ borderBottom: "1px solid var(--border)", paddingBottom: 10, marginBottom: 10 }}>
            <div className="form-row small">
              <b>v{o.offer_version}</b> <StatusTag value={o.status} /> <span>plan <b>{o.source_mode}</b></span>
              <span>inputs v{o.input_version}</span><span>expires {new Date(o.expires_at).toLocaleString()}</span>
              <span>premium total <b className="num">{eur(o.premium_total_eur)}</b></span><Digest value={o.terms_digest} />
            </div>
            <table className="data">
              <thead><tr><th>Line</th><th>Action</th><th>Lane</th><th>Part</th><th>Delivery week</th><th className="n">Qty</th><th className="n">Premium / unit</th><th className="n">Payment days</th></tr></thead>
              <tbody>{lines.map((l, i) => (
                <tr key={l.line_id}><td>{l.line_id}</td><td>{l.kind.replace(/_/g, " ").toLowerCase()}</td><td className="mono">{l.lane_id}</td><td className="mono">{l.part_id}</td><td>{l.delivery_week}</td>
                  {edit && o === latest ? (<>
                    <td className="n"><input className="field narrow" type="number" min={1} max={o.lines[i].additional_qty} value={l.additional_qty}
                      aria-label="Quantity" onChange={(e) => setEdit(edit.map((x, j) => j === i ? { ...x, additional_qty: Number(e.target.value) } : x))} /></td>
                    <td className="n"><input className="field narrow" inputMode="decimal" value={l.unit_premium_eur} aria-label="Premium"
                      onChange={(e) => setEdit(edit.map((x, j) => j === i ? { ...x, unit_premium_eur: e.target.value } : x))} /></td>
                    <td className="n"><input className="field narrow" type="number" min={0} max={180} value={l.payment_days} aria-label="Payment days"
                      onChange={(e) => setEdit(edit.map((x, j) => j === i ? { ...x, payment_days: Number(e.target.value) } : x))} /></td></>) : (<>
                    <td className="n">{num(l.additional_qty)}</td><td className="n">{eur(l.unit_premium_eur)}</td><td className="n">{l.payment_days}</td></>)}
                </tr>))}
              </tbody>
            </table>
            {o === latest && o.status === "DRAFT" && (
              <div className="form-row">
                {!edit && <button className="btn sm" onClick={() => setEdit(o.lines.map((l) => ({ ...l })))}>Edit terms (new version)</button>}
                {edit && <><button className="btn sm primary" disabled={revise.isPending} onClick={() => revise.mutate(edit)}>Save as v{o.offer_version + 1}</button>
                  <button className="btn sm" onClick={() => setEdit(null)}>Cancel</button></>}
                <button className="btn sm primary" disabled={me.role !== "BUYER_PROCUREMENT" || send.isPending} onClick={() => send.mutate(o)}
                        title={me.role !== "BUYER_PROCUREMENT" ? "Only buyer procurement can send" : ""}>Send to supplier</button>
                {me.role !== "BUYER_PROCUREMENT" && <span className="small muted">Sending requires the procurement role.</span>}
              </div>)}
            <ErrorNote error={send.error || revise.error} />
            {co.map((c) => (
              <div key={c.counteroffer_id} className="notice warn">
                <b>Counteroffer {c.counteroffer_id}</b> ({c.reason_code}) on v{c.parent_version}:{" "}
                {c.lines.map((l) => `${l.line_id}: qty ${l.original_qty}→${l.countered_qty}, week ${l.original_delivery_week}→${l.countered_delivery_week}, premium ${l.original_premium_eur}→${l.countered_premium_eur}`).join("; ")}.
                {" "}Inputs changed — re-run the scenario in Simulate, then draft a revised version.
              </div>))}
            {ag && <AgreementCard ag={ag} me={me} onChange={onChange} />}
          </div>
        );
      })}
    </Section>
  );
}

export function AgreementCard({ ag, me, onChange }: { ag: Agreement; me: Me; onChange: () => void }) {
  const [showExport, setShowExport] = useState(false);
  const approve = useMutation({
    mutationFn: (decision: string) => api(`/agreements/${ag.agreement_id}/approvals`, { method: "POST", json: { decision, terms_digest: ag.terms_digest } }),
    onSuccess: onChange,
  });
  const exp = useQuery({ queryKey: ["export", ag.agreement_id], enabled: showExport, queryFn: () => api<Record<string, unknown>>(`/agreements/${ag.agreement_id}/export`) });
  const mine = ag.required_roles.includes(me.role) && !ag.approvals.some((a) => a.role === me.role);
  return (
    <div className="section" style={{ marginBottom: 0 }}>
      <header><h3>Agreement {ag.agreement_id}</h3><StatusTag value={ag.status} /><div className="spacer" /><Digest value={ag.terms_digest} /></header>
      <div className="content stack">
        <div className="small">Required approvers: {ag.required_roles.map((r) => (
          <span key={r} style={{ marginRight: 8 }}>{r.replace(/_/g, " ").toLowerCase()} {(() => { const a = ag.approvals.find((x) => x.role === r); return a ? <StatusTag value={a.decision} title={`${a.principal} at ${a.at}`} /> : <span className="tag gray">PENDING</span>; })()}</span>))}
        </div>
        {ag.status === "PENDING_APPROVAL" && me.role.startsWith("BUYER") && (
          <div className="form-row">
            <button className="btn primary sm" disabled={!mine || approve.isPending} onClick={() => approve.mutate("APPROVE")}>Approve exact terms</button>
            <button className="btn danger sm" disabled={!mine || approve.isPending} onClick={() => approve.mutate("REJECT")}>Reject</button>
            {!mine && <span className="small muted">Your role is not a pending approver for this agreement.</span>}
          </div>)}
        <ErrorNote error={approve.error} />
        {ag.status === "EXPORT_READY" && me.role.startsWith("BUYER") && (
          <div><button className="btn sm" onClick={() => setShowExport(!showExport)}>{showExport ? "Hide" : "Show"} export preview</button>
            {exp.data && <pre className="mono" style={{ maxHeight: 280, overflow: "auto", background: "var(--surface-2)", padding: 8 }}>{JSON.stringify(exp.data, null, 2)}</pre>}
            <p className="small muted">ERP write-back is disabled in this prototype; the export is a structured preview.</p></div>)}
      </div>
    </div>
  );
}
