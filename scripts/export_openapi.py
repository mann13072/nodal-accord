"""Writes the committed OpenAPI contract (contracts/openapi/nodal-accord-v1.json) from the FastAPI app."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("packages/domain/src", "packages/planning_engine/src", "packages/optimization_engine/src", "packages/finance_engine/src",
            "packages/integrations/src", "apps/api/src"):
    sys.path.insert(0, str(ROOT / sub))

from nodal_api.config import Settings  # noqa: E402
from nodal_api.main import create_app  # noqa: E402

app = create_app(Settings(env="contract", demo_mode=True, data_root=ROOT, db_url="sqlite://", inline_worker=False))
out = ROOT / "contracts" / "openapi" / "nodal-accord-v1.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
print(f"wrote {out.relative_to(ROOT)} ({len(app.openapi()['paths'])} paths)")
