"""Workflow persistence (cases, runs, offers, approvals, agreements, audit, outbox, imports).

Local runtime uses SQLite (WAL) because PostgreSQL is not available in this environment. The canonical
planning snapshot stays in the generator's Parquet files and is read through SnapshotStore.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


class Base(DeclarativeBase):
    pass


class Case(Base):
    __tablename__ = "cases"
    case_id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    buyer_org_id: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    impact_score: Mapped[int] = mapped_column(Integer, default=0)
    disruption_id: Mapped[str | None] = mapped_column(String, nullable=True)
    snapshot_id: Mapped[str] = mapped_column(String)
    fixture_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    supplier_org_ids: Mapped[list] = mapped_column(JSON, default=list)
    tenant_scope_ids: Mapped[list] = mapped_column(JSON, default=list)
    state: Mapped[str] = mapped_column(String, index=True)
    seeded_script_status: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_principal_id: Mapped[str | None] = mapped_column(String, nullable=True)
    input_version: Mapped[int] = mapped_column(Integer, default=1)
    input_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScenarioRun(Base):
    __tablename__ = "scenario_runs"
    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    requested_by: Mapped[str] = mapped_column(String)
    request: Mapped[dict] = mapped_column(JSON)
    input_version: Mapped[int] = mapped_column(Integer)
    input_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    model_version: Mapped[str] = mapped_column(String, default="milp-v1")
    state: Mapped[str] = mapped_column(String, index=True)
    overall_status: Mapped[str] = mapped_column(String, default="NOT_RUN")
    results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    wall_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Offer(Base):
    __tablename__ = "offers"
    offer_id: Mapped[str] = mapped_column(String, primary_key=True)
    offer_group_id: Mapped[str] = mapped_column(String, index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    sender_org_id: Mapped[str] = mapped_column(String)
    recipient_org_id: Mapped[str] = mapped_column(String, index=True)
    offer_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)
    source_run_id: Mapped[str] = mapped_column(String)
    source_mode: Mapped[str] = mapped_column(String)
    input_version: Mapped[int] = mapped_column(Integer)
    lines: Mapped[list] = mapped_column(JSON)
    terms_digest: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Counteroffer(Base):
    __tablename__ = "counteroffers"
    counteroffer_id: Mapped[str] = mapped_column(String, primary_key=True)
    parent_offer_id: Mapped[str] = mapped_column(ForeignKey("offers.offer_id"), index=True)
    case_id: Mapped[str] = mapped_column(String, index=True)
    supplier_org_id: Mapped[str] = mapped_column(String)
    parent_version: Mapped[int] = mapped_column(Integer)
    lines: Mapped[list] = mapped_column(JSON)
    reason_code: Mapped[str] = mapped_column(String)
    constraint_acknowledgement: Mapped[bool] = mapped_column(Boolean)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Agreement(Base):
    __tablename__ = "agreements"
    agreement_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    offer_id: Mapped[str] = mapped_column(ForeignKey("offers.offer_id"))
    supplier_org_id: Mapped[str] = mapped_column(String)
    offer_version: Mapped[int] = mapped_column(Integer)
    terms_digest: Mapped[str] = mapped_column(String)
    input_version: Mapped[int] = mapped_column(Integer)
    required_roles: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String)  # PENDING_APPROVAL | APPROVED | REJECTED | EXPORT_READY
    premium_total_eur: Mapped[str] = mapped_column(String)
    export_status: Mapped[str] = mapped_column(String, default="NOT_EXPORTED_WRITE_BACK_DISABLED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Approval(Base):
    __tablename__ = "approvals"
    approval_id: Mapped[str] = mapped_column(String, primary_key=True)
    agreement_id: Mapped[str] = mapped_column(ForeignKey("agreements.agreement_id"), index=True)
    approver_principal_id: Mapped[str] = mapped_column(String)
    approver_org_id: Mapped[str] = mapped_column(String)
    approval_role: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(String)
    terms_digest: Mapped[str] = mapped_column(String)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_type: Mapped[str] = mapped_column(String)
    actor_id: Mapped[str] = mapped_column(String)
    actor_org: Mapped[str] = mapped_column(String)
    tenant_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    case_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    resource_type: Mapped[str] = mapped_column(String)
    resource_id: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    authorization_decision: Mapped[str] = mapped_column(String)
    before_version: Mapped[str | None] = mapped_column(String, nullable=True)
    after_version: Mapped[str | None] = mapped_column(String, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload_digest: Mapped[str | None] = mapped_column(String, nullable=True)
    visible_to_org: Mapped[str | None] = mapped_column(String, nullable=True)  # counterparty allowed to see it
    summary: Mapped[str] = mapped_column(Text, default="")


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(String)
    event_version: Mapped[int] = mapped_column(Integer, default=1)
    tenant_scope: Mapped[str] = mapped_column(String)
    aggregate_id: Mapped[str] = mapped_column(String)
    aggregate_version: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    delivery_state: Mapped[str] = mapped_column(String, default="DISABLED_OUTBOUND")


class ImportRun(Base):
    __tablename__ = "integration_runs"
    import_id: Mapped[str] = mapped_column(String, primary_key=True)
    connector: Mapped[str] = mapped_column(String)
    connector_version: Mapped[str] = mapped_column(String)
    payload_checksum: Mapped[str] = mapped_column(String, index=True)
    requested_by: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(String, primary_key=True)  # principal|route|Idempotency-Key
    response: Mapped[dict] = mapped_column(JSON)
    status_code: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def make_engine(url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _pragmas(conn, _):
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    Base.metadata.create_all(engine)
    return engine


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
