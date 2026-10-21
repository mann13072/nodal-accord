// Typed client for /api/v1. Business numbers are always server-calculated; the UI only formats them.

export type Principal = {
  principal_id: string; org_id: string; org_name: string; role: string; tenant_scopes: string[];
};
export type Me = Principal & { environment: string; dataset: string; snapshot_id: string; snapshot_generated_at?: string };

export type CaseSummary = {
  case_id: string; title: string; category?: string; state: string; impact_score?: number; tenant_id?: string;
  snapshot_id?: string; input_version?: number; version?: number; opened_at?: string; updated_at: string;
  seeded_script_status?: string; buyer_org_id?: string;
};

export type LedgerWeek = {
  week_start: string; opening_usable: number; receipts: number; demand: number; prior_backlog: number;
  fulfilled: number; closing_usable: number; closing_backlog: number; is_short: boolean;
};
export type ItemLedger = {
  part_id: string; plant_id: string; opening_usable: number; baseline: LedgerWeek[]; disrupted: LedgerWeek[];
  baseline_first_shortage_week: string | null; disrupted_first_shortage_week: string | null;
  baseline_peak_backlog: number; disrupted_peak_backlog: number;
  affected_receipts: { receipt_id: string; lane_id: string; arrival_week: string; planned_units: number; disrupted_units: number }[];
};
export type FixtureView = {
  week_start: string; prebuild_prior_week: string; alternate_qualified: boolean; alternate_arrives_in_time: boolean;
  overtime_available: boolean; other_relationships_on_shared_resource: number; scope: string;
  lines: { lane_id: string; part_id: string; demand_units: number; usable_stock: number; lane_ceiling_units: number;
           alternate_lane_id: string | null; alternate_offered_units: number }[];
};
export type CaseDetail = {
  case: CaseSummary; supplier_org_ids: string[]; suppliers: { org_id: string; display_name: string }[];
  disruption: Record<string, unknown> & { disruption_id: string; event_type: string; window: string[] } | null;
  fixture: FixtureView | null; snapshot_horizon: { weeks: string[]; items: ItemLedger[]; note: string };
  input_overrides: Record<string, unknown>; dataset: string;
};
export type SupplierCaseDetail = { case: CaseSummary; offers: Offer[] };

export type Financials = Record<string, string | null | string[]> & {
  incremental_buyer_cost_eur: string; purchase_spend_eur: string; premium_spend_eur: string; holding_cost_eur: string;
  working_capital_peak_eur: string; shortage_exposure_proxy_eur: string; overtime_premium_eur: string;
  alternate_price_delta_eur: string; basis: string[];
};
export type Release = {
  lane_id: string; supplier_org_id: string; part_id: string; plant_id: string; role: string; release_week: string;
  arrival_week: string; regular_units: number; overtime_units: number; unit_price_eur: string; disclosed_premium_eur: string;
};
export type ModeResult = {
  status: string; message: string; offer_eligible: boolean;
  kpis: { unmet_units_at_end: number | null; late_unit_weeks: number | null; peak_backlog_units: number | null;
          primary_units: number | null; alternate_units: number | null; overtime_units: number | null;
          prebuild_peak_units: number | null; earliest_relief_week: string | null; note?: string };
  financials: Financials | null;
  solver: { relative_gap: number | null; solver_wall_seconds: number; build_seconds: number; model_size: Record<string, number>;
            stage1_termination: string | null; stage2_termination: string | null };
  releases: Release[]; item_weeks: Record<string, number | string>[];
  resource_weeks: { resource_id: string; week_start: string; binding: boolean }[];
  binding_constraints: string[]; diagnostics: string[]; warnings: string[]; validation_errors: string[]; assumptions: string[];
  lane_provenance: Record<string, { role: string; supplier_org_id: string; qualified: boolean; lead_weeks: number; provenance: string }>;
  hidden_other_relationship_lines: number; input_hash: string;
};
export type Run = {
  run_id: string; case_id: string; state: string; status: string; model_version: string; input_version: number;
  input_snapshot_hash: string | null; requested_by: string; request: Record<string, unknown>; created_at: string;
  finished_at: string | null; wall_seconds: number | null; error: string | null; stale?: boolean;
  results?: Record<string, ModeResult>;
};
export type OfferLine = {
  line_id: string; kind: string; lane_id: string; part_id: string; plant_id: string; delivery_week: string;
  additional_qty: number; unit_premium_eur: string; payment_days: number; release_week?: string;
};
export type Offer = {
  offer_id: string; offer_group_id: string; case_id: string; sender_org_id: string; recipient_org_id: string;
  offer_version: number; status: string; source_mode: string; source_run_id?: string; input_version: number; lines: OfferLine[];
  terms_digest: string; expires_at: string; created_at: string; sent_at: string | null; premium_total_eur: string;
  your_private_evaluation?: { visible_to: string; note: string; lines: Record<string, string | number | null>[] };
  your_lane_capacity?: Record<string, string | number>[];
};
export type Agreement = {
  agreement_id: string; case_id: string; offer_id: string; offer_version: number; supplier_org_id: string;
  terms_digest: string; status: string; required_roles: string[]; premium_total_eur: string; input_version: number;
  export_status: string; approvals: { role: string; principal: string; decision: string; at: string }[];
};
export type Counter = { counteroffer_id: string; parent_offer_id: string; parent_version: number; reason_code: string;
  created_at: string; lines: Record<string, string | number>[] };
export type AuditItem = { event_id: string; at: string; actor_id: string; actor_org: string; action: string;
  resource_type: string; resource_id: string; decision: string; summary: string; payload_digest: string | null };
export type Graph = { nodes: { id: string; kind: string; label: string; highlighted?: boolean; note?: string }[];
  edges: { source: string; target: string; kind: string; role?: string; lane_id?: string; qualified?: boolean; lead_time_days?: number }[];
  hidden_nodes: number; max_nodes: number; other_relationships_sharing_resource: number; completeness_note: string };

const PRINCIPAL_KEY = "nodal.principal";

export function getPrincipalId(): string {
  try {
    return localStorage.getItem(PRINCIPAL_KEY) || "demo.buyer001.planner";
  } catch {
    return "demo.buyer001.planner";
  }
}
export function setPrincipalId(id: string) {
  try { localStorage.setItem(PRINCIPAL_KEY, id); } catch { /* storage unavailable: session-only */ }
}

export class ApiError extends Error {
  constructor(public status: number, public body: unknown) {
    super(typeof body === "object" && body && "detail" in body
      ? typeof (body as { detail: unknown }).detail === "string"
        ? (body as { detail: string }).detail
        : JSON.stringify((body as { detail: unknown }).detail)
      : `HTTP ${status}`);
  }
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Demo-Principal": getPrincipalId(), "X-Correlation-ID": crypto.randomUUID() };
  if (init.json !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api/v1${path}`, { ...init, headers: { ...headers, ...(init.headers as Record<string, string>) },
    body: init.json !== undefined ? JSON.stringify(init.json) : init.body });
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, body);
  return body as T;
}

export const isBuyer = (role?: string) => !!role && role.startsWith("BUYER");
export const isSupplier = (role?: string) => role === "SUPPLIER_PLANNER";
export const eur = (v: string | number | null | undefined) =>
  v === null || v === undefined ? "—" : `€${Number(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
export const num = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toLocaleString("en-GB"));
