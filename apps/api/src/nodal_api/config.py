from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATA_ROOT = REPO_ROOT.parent / "Nodal_Accord_5000_Supplier_Data" / "data" / "synthetic" / "generated" / "tiny"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    env: str
    demo_mode: bool
    data_root: Path
    db_url: str
    inline_worker: bool
    max_graph_nodes: int = 100
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    max_solver_seconds: float = 600.0  # hard cap on any requested solver time limit

    @property
    def environment_label(self) -> str:
        return "DEMO" if self.demo_mode else self.env.upper()


def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    env = os.environ.get("NODAL_ENV", "local").strip().lower()
    demo = _flag("DEMO_MODE", "true")
    if env == "production" and demo:
        # Blueprint §19.3: demo identities must never be accepted in a production configuration.
        raise ConfigError("DEMO_MODE cannot be enabled when NODAL_ENV=production")
    data_root = Path(os.environ.get("NODAL_DATA_ROOT", str(DEFAULT_DATA_ROOT))).resolve()
    db_url = os.environ.get("NODAL_DB_URL")
    if not db_url:
        var = REPO_ROOT / "var"
        var.mkdir(exist_ok=True)
        db_url = f"sqlite:///{(var / f'nodal_{data_root.name}.db').as_posix()}"
    extra_origins = tuple(o.strip() for o in os.environ.get("NODAL_CORS_ORIGINS", "").split(",") if o.strip())
    return Settings(env, demo, data_root, db_url, _flag("NODAL_INLINE_WORKER", "false"),
                    cors_origins=Settings.cors_origins + extra_origins,
                    max_solver_seconds=float(os.environ.get("NODAL_MAX_SOLVER_SECONDS", "600")))
