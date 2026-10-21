"""Optimization worker process: claims QUEUED scenario runs from the shared database and executes them.

Several workers may run; claiming is an atomic conditional UPDATE, so each run executes once.
Run:  python -m nodal_worker.main
"""
from __future__ import annotations

import logging
import os
import signal
import time
import uuid

from nodal_api.config import load_settings
from nodal_api.db import make_engine, make_session_factory
from nodal_api.services.scenario_exec import execute_run, pending_run_ids
from nodal_integrations.snapshot import get_store

log = logging.getLogger("nodal_worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}')
    settings = load_settings()
    store = get_store(settings.data_root)
    sessions = make_session_factory(make_engine(settings.db_url))
    worker_id = f"worker-{os.getpid()}-{uuid.uuid4().hex[:4]}"
    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    log.info("worker %s started; dataset=%s db=%s", worker_id, store.dataset_label, settings.db_url)
    last_beat = 0.0
    while not stop:
        ids = pending_run_ids(sessions)
        for run_id in ids:
            t0 = time.perf_counter()
            if execute_run(sessions, store, run_id, worker_id):
                log.info("run %s finished in %.2fs", run_id, time.perf_counter() - t0)
        if time.time() - last_beat > 30:
            log.info("heartbeat %s", worker_id)
            last_beat = time.time()
        if not ids:
            time.sleep(0.5)


if __name__ == "__main__":
    main()
