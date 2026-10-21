"""FastAPI application: modular monolith for ingestion, policy, cases, offers and approvals.

Optimization runs in a separate worker process (apps/worker). For single-process local demos and tests,
NODAL_INLINE_WORKER=true starts an in-process worker thread instead; the API path is identical (202 + poll).
"""
from __future__ import annotations

import logging
import threading
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nodal_agent_tools.providers import provider_from_env
from nodal_integrations.snapshot import get_store

from .config import Settings, load_settings
from .db import make_engine, make_session_factory
from .routers import agent, cases, offers, system
from .services.agent import execute_agent_run, pending_agent_ids
from .services.cases import seed_cases
from .services.scenario_exec import execute_run, pending_run_ids

log = logging.getLogger("nodal_api")


class InlineWorker:
    def __init__(self, sessions, store, settings, provider_factory):
        self.sessions, self.store, self.settings, self.provider_factory = sessions, store, settings, provider_factory
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="nodal-inline-worker", daemon=True)
        self.worker_id = f"inline-{uuid.uuid4().hex[:6]}"

    def _loop(self) -> None:
        while not self.stop.is_set():
            for run_id in pending_run_ids(self.sessions):
                execute_run(self.sessions, self.store, run_id, self.worker_id)
            for agent_id in pending_agent_ids(self.sessions):
                execute_agent_run(self.sessions, self.store, self.settings, self.provider_factory(), agent_id,
                                  self.worker_id, self.wake.set)
            self.wake.wait(1.0)
            self.wake.clear()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.store = get_store(settings.data_root)
        engine = make_engine(settings.db_url)
        app.state.sessions = make_session_factory(engine)
        with app.state.sessions() as s:
            seeded = seed_cases(s, app.state.store)
        if seeded:
            log.info("seeded %s cases from %s", seeded, app.state.store.dataset_label)
        if not hasattr(app.state, "agent_provider_factory"):
            app.state.agent_provider_factory = provider_from_env  # None => AI disabled; tests may override
        worker = None
        if settings.inline_worker:
            worker = InlineWorker(app.state.sessions, app.state.store, settings, lambda: app.state.agent_provider_factory())
            worker.thread.start()
            app.state.wake_worker = worker.wake.set
        else:
            app.state.wake_worker = lambda: None
        yield
        if worker:
            worker.stop.set()
            worker.wake.set()
        engine.dispose()

    app = FastAPI(title="Nodal Accord API", version="1.0.0", lifespan=lifespan,
                  description="Collaborative supply resolution engine. Synthetic-data prototype; no real ERP or vendor integration.")
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"],
                       allow_headers=["*"], expose_headers=["X-Correlation-ID"])

    @app.middleware("http")
    async def correlation(request: Request, call_next):
        cid = request.headers.get("X-Correlation-ID") or uuid.uuid4().hex
        if int(request.headers.get("content-length") or 0) > 1_000_000:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        response.headers["X-Environment"] = settings.environment_label
        return response

    app.include_router(system.router)
    app.include_router(cases.router)
    app.include_router(offers.router)
    app.include_router(agent.router)
    return app


app = None


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
