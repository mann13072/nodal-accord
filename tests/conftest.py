import os
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent
DEFAULT_DATA_ROOT = REPO.parent / "Nodal_Accord_5000_Supplier_Data" / "data" / "synthetic" / "generated" / "tiny"
sys.path.insert(0, str(TESTS))  # for api_helpers


def data_root() -> Path:
    return Path(os.environ.get("NODAL_DATA_ROOT", str(DEFAULT_DATA_ROOT)))


@pytest.fixture(scope="session")
def store():
    from nodal_integrations.snapshot import SnapshotNotFound, get_store

    try:
        return get_store(data_root())
    except SnapshotNotFound as exc:
        pytest.skip(f"generated dataset unavailable: {exc}")


@pytest.fixture()
def client(tmp_path, store):
    from fastapi.testclient import TestClient

    from nodal_api.config import Settings
    from nodal_api.main import create_app

    settings = Settings(env="test", demo_mode=True, data_root=data_root().resolve(),
                        db_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}", inline_worker=True)
    with TestClient(create_app(settings)) as c:
        yield c
