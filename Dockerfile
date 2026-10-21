# Single-container demo deployment (e.g. Render free web service): API + in-process solver worker.
# Ships the synthetic 500-supplier dataset from deploy/data/. Sized for ~512 MB RAM hosts:
# 12-week scopes are capped at 20 items and solver time at 30 s per mode.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd -m -u 1000 app
WORKDIR /app

COPY pyproject.toml ./
RUN pip install "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic>=2.7" "sqlalchemy>=2.0" "pyarrow>=16" \
                "pandas>=2.2" "pyomo>=6.8" "highspy>=1.7" "pyyaml>=6" "httpx>=0.27"

COPY --chown=app:app packages ./packages
COPY --chown=app:app apps/api ./apps/api
COPY --chown=app:app apps/worker ./apps/worker
COPY --chown=app:app deploy/data ./data

ENV PYTHONPATH=/app/packages/domain/src:/app/packages/planning_engine/src:/app/packages/optimization_engine/src:/app/packages/finance_engine/src:/app/packages/integrations/src:/app/packages/agent_tools/src:/app/apps/api/src:/app/apps/worker/src \
    NODAL_ENV=demo \
    DEMO_MODE=true \
    NODAL_DATA_ROOT=/app/data/medium_500 \
    NODAL_DB_URL=sqlite:////tmp/nodal_demo.db \
    NODAL_INLINE_WORKER=true \
    NODAL_MAX_SOLVER_SECONDS=30 \
    NODAL_MAX_SCOPE_ITEMS=20 \
    PORT=10000

USER app
EXPOSE 10000
CMD ["sh", "-c", "uvicorn nodal_api.main:get_app --factory --host 0.0.0.0 --port ${PORT}"]
