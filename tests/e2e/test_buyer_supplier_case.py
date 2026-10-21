"""Issue-to-agreement workflow through the public API only (blueprint §2 definition of done)."""
from api_helpers import H, run_scenario

PLANNER, PROCUREMENT, FINANCE = "demo.buyer001.planner", "demo.buyer001.procurement", "demo.buyer001.finance"


def supplier_principal(client, org_id: str) -> str:
    items = client.get("/api/v1/session/principals").json()["items"]
    return next(p["principal_id"] for p in items if p["org_id"] == org_id and p["role"] == "SUPPLIER_PLANNER")


def test_shared_machine_case_to_export(client):
    case_id = "CASE-000004"
    case = client.get(f"/api/v1/cases/{case_id}", headers=H(PLANNER)).json()
    assert case["case"]["state"] == "DETECTED"
    assert case["disruption"]["disruption_id"] == "DISR-000004"
    assert case["snapshot_horizon"]["items"], "investigate view needs time-phased evidence"

    results = run_scenario(client, PLANNER, case_id)["results"]
    assert results["baseline"]["kpis"]["unmet_units_at_end"] == 200  # one 80 h budget for both parts
    assert results["alternate"]["kpis"]["unmet_units_at_end"] == 0
    assert results["hybrid"]["kpis"]["unmet_units_at_end"] == 0
    assert all(r["status"] == "OPTIMAL" for r in results.values())
    assert results["baseline"]["resource_weeks"] and "regular_hours_available" not in results["baseline"]["resource_weeks"][0]
    run_id = client.get(f"/api/v1/cases/{case_id}/scenario-runs", headers=H(PLANNER)).json()["items"][0]["run_id"]

    alt_supplier = next(r["supplier_org_id"] for r in results["alternate"]["releases"] if r["role"] == "ALTERNATE")
    draft = client.post(f"/api/v1/cases/{case_id}/offers", headers=H(PLANNER),
                        json={"run_id": run_id, "mode": "alternate", "recipient_org_id": alt_supplier})
    assert draft.status_code == 201, draft.text
    offer = draft.json()
    assert offer["status"] == "DRAFT" and offer["lines"][0]["kind"] == "ALTERNATE_SUPPLY"
    assert offer["lines"][0]["additional_qty"] == 200

    supplier = supplier_principal(client, alt_supplier)
    assert client.get(f"/api/v1/cases/{case_id}", headers=H(supplier)).status_code == 404  # draft not visible yet

    assert client.post(f"/api/v1/offers/{offer['offer_id']}/send", headers=H(PLANNER), json={}).status_code == 403
    sent = client.post(f"/api/v1/offers/{offer['offer_id']}/send", headers=H(PROCUREMENT), json={"terms_digest": offer["terms_digest"]})
    assert sent.status_code == 200 and sent.json()["status"] == "SENT"

    sview = client.get(f"/api/v1/cases/{case_id}", headers=H(supplier))
    assert sview.status_code == 200
    soffer = sview.json()["offers"][0]
    assert soffer["terms_digest"] == offer["terms_digest"]

    bad = client.post(f"/api/v1/offers/{offer['offer_id']}/decisions", headers=H(supplier),
                      json={"decision": "ACCEPT", "offer_version": 1, "terms_digest": "sha256:wrong"})
    assert bad.status_code == 409
    acc = client.post(f"/api/v1/offers/{offer['offer_id']}/decisions", headers=H(supplier),
                      json={"decision": "ACCEPT", "offer_version": 1, "terms_digest": offer["terms_digest"]})
    assert acc.status_code == 200, acc.text
    agreement_id = acc.json()["agreement_id"]

    assert client.get(f"/api/v1/agreements/{agreement_id}/export", headers=H(PROCUREMENT)).status_code == 409
    ag = client.post(f"/api/v1/agreements/{agreement_id}/approvals", headers=H(PROCUREMENT),
                     json={"decision": "APPROVE", "terms_digest": offer["terms_digest"]})
    assert ag.status_code == 200, ag.text
    if "BUYER_FINANCE" in ag.json()["required_roles"]:
        ag = client.post(f"/api/v1/agreements/{agreement_id}/approvals", headers=H(FINANCE),
                         json={"decision": "APPROVE", "terms_digest": offer["terms_digest"]})
    assert ag.json()["status"] == "EXPORT_READY"
    export = client.get(f"/api/v1/agreements/{agreement_id}/export", headers=H(PROCUREMENT)).json()
    assert export["erp_write_back"]["enabled"] is False
    assert export["terms_digest"] == offer["terms_digest"]
    assert client.get(f"/api/v1/cases/{case_id}", headers=H(PLANNER)).json()["case"]["state"] == "EXPORT_READY"

    events = client.get(f"/api/v1/cases/{case_id}/events", headers=H(PLANNER)).json()["items"]
    actions = [e["action"] for e in events]
    for expected in ("scenario.submit", "offer.draft", "offer.send", "offer.accept", "agreement.approve"):
        assert expected in actions
    supplier_events = client.get(f"/api/v1/cases/{case_id}/events", headers=H(supplier)).json()["items"]
    assert "offer.draft" not in [e["action"] for e in supplier_events]


def test_counteroffer_forces_resimulation_and_changes_feasibility(client):
    planner, procurement = "demo.buyer002.planner", "demo.buyer002.procurement"
    case_id = "CASE-000011"  # COUNTEROFFER_FEASIBILITY, tenant 2
    first = run_scenario(client, planner, case_id, modes=["baseline", "alternate"])
    assert first["results"]["alternate"]["kpis"]["unmet_units_at_end"] == 0
    alt = next(r for r in first["results"]["alternate"]["releases"] if r["role"] == "ALTERNATE")
    offer = client.post(f"/api/v1/cases/{case_id}/offers", headers=H(planner),
                        json={"run_id": first["run_id"], "mode": "alternate", "recipient_org_id": alt["supplier_org_id"]}).json()
    client.post(f"/api/v1/offers/{offer['offer_id']}/send", headers=H(procurement), json={})
    supplier = supplier_principal(client, alt["supplier_org_id"])

    co = client.post(f"/api/v1/offers/{offer['offer_id']}/counteroffers", headers=H(supplier),
                     json={"offer_version": 1, "reason_code": "DATE_CHANGE", "constraint_acknowledgement": True,
                           "lines": [{"line_id": "L1", "countered_delivery_week": "2027-01-04"}]})
    assert co.status_code == 201, co.text
    case = client.get(f"/api/v1/cases/{case_id}", headers=H(planner)).json()["case"]
    assert case["state"] == "COUNTERED" and case["input_version"] == 2

    stale = client.post(f"/api/v1/cases/{case_id}/offers", headers=H(planner),
                        json={"run_id": first["run_id"], "mode": "alternate", "recipient_org_id": alt["supplier_org_id"]})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "STALE_SCENARIO"

    second = run_scenario(client, planner, case_id, modes=["alternate"])
    oracle = client.app.state.store.case_fixture(case_id)["counteroffer_recomputed_result"]["unmet_units"]
    assert second["results"]["alternate"]["kpis"]["unmet_units_at_end"] == oracle == 200
    retry = client.post(f"/api/v1/cases/{case_id}/offers", headers=H(planner),
                        json={"run_id": second["run_id"], "mode": "alternate", "recipient_org_id": alt["supplier_org_id"],
                              "offer_group_id": offer["offer_group_id"]})
    assert retry.status_code == 422  # the countered date makes the alternate useless; no offer is invented


def test_capacity_change_blocks_stale_approval(client):
    case_id = "CASE-000004"
    res = run_scenario(client, PLANNER, case_id, modes=["alternate"])
    alt = next(r for r in res["results"]["alternate"]["releases"] if r["role"] == "ALTERNATE")
    offer = client.post(f"/api/v1/cases/{case_id}/offers", headers=H(PLANNER),
                        json={"run_id": res["run_id"], "mode": "alternate", "recipient_org_id": alt["supplier_org_id"]}).json()
    client.post(f"/api/v1/offers/{offer['offer_id']}/send", headers=H(PROCUREMENT), json={})
    supplier = supplier_principal(client, alt["supplier_org_id"])
    acc = client.post(f"/api/v1/offers/{offer['offer_id']}/decisions", headers=H(supplier),
                      json={"decision": "ACCEPT", "offer_version": 1, "terms_digest": offer["terms_digest"]}).json()
    upd = client.post(f"/api/v1/cases/{case_id}/capacity-confirmations", headers=H(supplier),
                      json={"lane_id": alt["lane_id"], "week": alt["arrival_week"], "max_units": 50})
    assert upd.status_code == 200, upd.text
    blocked = client.post(f"/api/v1/agreements/{acc['agreement_id']}/approvals", headers=H(PROCUREMENT),
                          json={"decision": "APPROVE", "terms_digest": offer["terms_digest"]})
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "STALE_APPROVAL"


def test_infeasible_zero_shortage_is_reported_not_invented(client):
    res = run_scenario(client, PLANNER, "CASE-000009", modes=["hybrid"], constraints={"require_zero_shortage": True})
    r = res["results"]["hybrid"]
    assert r["status"] == "INFEASIBLE" and r["offer_eligible"] is False
    assert r["releases"] == [] and r["diagnostics"]


def test_idempotent_scenario_submission(client):
    body = {"modes": ["baseline"]}
    a = client.post("/api/v1/cases/CASE-000001/scenarios", json=body, headers=H(PLANNER, **{"Idempotency-Key": "k-1"}))
    b = client.post("/api/v1/cases/CASE-000001/scenarios", json=body, headers=H(PLANNER, **{"Idempotency-Key": "k-1"}))
    assert a.status_code == b.status_code == 202 and a.json()["run_id"] == b.json()["run_id"]
