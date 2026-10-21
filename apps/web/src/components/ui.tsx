import { ReactNode } from "react";

const TONE: Record<string, string> = {
  OPTIMAL: "green", FEASIBLE_WITH_GAP: "amber", INFEASIBLE: "red", TIME_LIMIT: "amber", ERROR: "red", NOT_RUN: "gray",
  QUEUED: "gray", RUNNING: "blue", VALIDATING: "blue", COMPLETED: "green", FAILED: "red", CANCELLED: "gray",
  DETECTED: "red", INVESTIGATING: "amber", SCENARIOS_READY: "blue", DRAFT_OFFER: "gray", SENT: "blue", COUNTERED: "amber",
  SUPPLIER_ACCEPTED: "blue", BUYER_APPROVAL_PENDING: "amber", APPROVED: "green", EXPORT_READY: "green", CLOSED: "gray",
  REJECTED: "red", EXPIRED: "gray", DRAFT: "gray", ACCEPTED: "green", SUPERSEDED: "gray", PENDING_APPROVAL: "amber",
  APPROVE: "green", REJECT: "red", ALLOW: "green", DENY: "red", DENY_STALE: "red",
};

export function StatusTag({ value, title }: { value: string | null | undefined; title?: string }) {
  if (!value) return null;
  return <span className={`tag ${TONE[value] ?? "gray"}`} title={title}>{value.replace(/_/g, " ")}</span>;
}

export function Section({ title, actions, children, id }: { title: string; actions?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section className="section" aria-labelledby={id}>
      <header><h3 id={id}>{title}</h3><div className="spacer" />{actions}</header>
      <div className="content">{children}</div>
    </section>
  );
}

/** Wide tables scroll sideways on their own instead of pushing the surrounding text off-screen. */
export function TableScroll({ children }: { children: ReactNode }) {
  return <div className="table-scroll">{children}</div>;
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="notice err" role="alert">{error instanceof Error ? error.message : String(error)}</div>;
}

export function Digest({ value }: { value: string }) {
  return <span className="digest" title={value}>{value.slice(0, 23)}…</span>;
}
