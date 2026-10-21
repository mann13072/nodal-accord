import time

from fastapi.testclient import TestClient


def H(principal: str, **extra) -> dict:
    return {"X-Demo-Principal": principal, **extra}


def wait_run(client: TestClient, principal: str, run_id: str, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/v1/scenario-runs/{run_id}", headers=H(principal))
        assert r.status_code == 200, r.text
        if r.json()["state"] in ("COMPLETED", "FAILED", "CANCELLED"):
            res = client.get(f"/api/v1/scenario-runs/{run_id}/results", headers=H(principal))
            assert res.status_code == 200, res.text
            return res.json()
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} did not finish in {timeout}s")


def run_scenario(client: TestClient, principal: str, case_id: str, modes=None, **body) -> dict:
    payload = {"modes": modes or ["baseline", "overtime", "alternate", "prebuild", "hybrid"], **body}
    r = client.post(f"/api/v1/cases/{case_id}/scenarios", json=payload, headers=H(principal))
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "QUEUED"
    return wait_run(client, principal, r.json()["run_id"])
