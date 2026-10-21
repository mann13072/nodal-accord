import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, getPrincipalId, isBuyer, isSupplier, Me, Principal, setPrincipalId } from "./api";
import { AgreementsPage, AuditPage, ImportsPage, NetworkPage } from "./pages/Pages";
import { CasesPage } from "./pages/CasesPage";
import { SupplierPortal } from "./pages/SupplierPortal";

export default function App() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me", getPrincipalId()], queryFn: () => api<Me>("/session/me") });
  const principals = useQuery({ queryKey: ["principals"], queryFn: () => api<{ items: Principal[] }>("/session/principals") });
  const role = me.data?.role;

  const switchPrincipal = (id: string) => {
    // Full reload: no cached data from the previous identity may survive the switch.
    setPrincipalId(id);
    qc.clear();
    window.location.assign("/");
  };

  return (
    <div className="shell">
      <header className="topbar" role="banner">
        <div className="brand" aria-label="Nodal Accord">
          <svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true"><circle cx="4" cy="8" r="2.5" fill="var(--accent)" /><circle cx="12" cy="4" r="2.5" fill="var(--accent)" /><circle cx="12" cy="12" r="2.5" fill="var(--accent)" /><path d="M4 8L12 4M4 8l8 4" stroke="var(--accent)" strokeWidth="1.2" /></svg>
          NODAL ACCORD
        </div>
        {me.data && <span className="chip tablet-up" title="Organization">{me.data.org_name}</span>}
        <label className="chip" title="Demo identity (server resolves role and tenant scope)">
          <span className="muted tablet-up">Acting as</span>
          <select aria-label="Demo identity" value={getPrincipalId()} onChange={(e) => switchPrincipal(e.target.value)}
                  style={{ border: "none", background: "transparent", fontWeight: 600 }}>
            {principals.data?.items.map((p) => (
              <option key={p.principal_id} value={p.principal_id}>{p.principal_id} · {p.role.replace(/_/g, " ").toLowerCase()}</option>
            ))}
          </select>
        </label>
        <div className="spacer" />
        {me.data && <span className="chip mono wide-only" title="Canonical snapshot">{me.data.snapshot_id}</span>}
        {me.data && <span className="chip wide-only" title="Dataset">dataset: {me.data.dataset}</span>}
        <span className="chip demo" title="Synthetic data only; not a production environment">
          <span className="tablet-up">ENVIRONMENT: </span>{me.data?.environment ?? "…"}<span className="tablet-up"> · SYNTHETIC DATA</span>
        </span>
      </header>
      <div className="body">
        <nav className="rail" aria-label="Primary">
          {isBuyer(role) && <NavLink to="/queue">Q<span>Queue</span></NavLink>}
          {isBuyer(role) && <NavLink to="/network">N<span>Network</span></NavLink>}
          {isSupplier(role) && <NavLink to="/supplier">O<span>Offers</span></NavLink>}
          {(isBuyer(role) || isSupplier(role)) && <NavLink to="/agreements">A<span>Agreem.</span></NavLink>}
          {isBuyer(role) && <NavLink to="/audit">L<span>Audit</span></NavLink>}
          {(role === "INTEGRATION_SERVICE" || role === "BUYER_PLANNER") && <NavLink to="/admin/integrations">I<span>Imports</span></NavLink>}
        </nav>
        <main className="main">
          {me.isError && <div className="notice err" style={{ margin: 12 }}>Cannot reach the API: {(me.error as Error).message}. Start it with <span className="mono">npm run dev</span>.</div>}
          {me.data && (
            <Routes>
              <Route path="/" element={<Navigate to={isSupplier(role) ? "/supplier" : isBuyer(role) ? "/queue" : "/ops"} replace />} />
              <Route path="/queue" element={<CasesPage me={me.data} />} />
              <Route path="/cases/:caseId/:mode" element={<CasesPage me={me.data} />} />
              <Route path="/supplier" element={<SupplierPortal me={me.data} />} />
              <Route path="/supplier/:caseId" element={<SupplierPortal me={me.data} />} />
              <Route path="/network" element={<NetworkPage />} />
              <Route path="/agreements" element={<AgreementsPage me={me.data} />} />
              <Route path="/audit" element={<AuditPage />} />
              <Route path="/admin/integrations" element={<ImportsPage />} />
              <Route path="/ops" element={<OpsPage />} />
              <Route path="*" element={<div className="empty">Not available for this role.</div>} />
            </Routes>
          )}
        </main>
      </div>
    </div>
  );
}

function OpsPage() {
  const m = useQuery({ queryKey: ["ops-metrics"], queryFn: () => api<Record<string, unknown>>("/metrics/resolution") });
  return (
    <div className="page">
      <h1>Platform operations</h1>
      <p className="muted">Operational metadata only. The platform operator has no default access to buyer or supplier commercial data.</p>
      <pre className="section content mono">{JSON.stringify(m.data ?? m.error?.message, null, 2)}</pre>
    </div>
  );
}
