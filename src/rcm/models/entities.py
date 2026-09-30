"""SQLAlchemy models — the Postgres data model (spec §6).

All PHI columns use :class:`EncryptedString` (encrypted at rest). The moat table
``appeal_outcome`` and the compliance tables ``audit_log`` / ``guardrail_block``
are here. ``denial.appeal_deadline`` and ``denial.priority`` are indexed for the
deadline-risk and work-prioritization queries.

Array/JSON/Vector columns are Postgres-native; these models are exercised against
a live Postgres (the ``postgres``-marked tests), not SQLite.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rcm.core.config import get_settings
from rcm.models.base import Base, TimestampMixin
from rcm.models.types import EncryptedString

_EMBED_DIM = get_settings().embedding_dim


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class Practice(Base, TimestampMixin):
    __tablename__ = "practice"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(256))
    npi_group: Mapped[str | None] = mapped_column(String(10))
    ehr_system: Mapped[str | None] = mapped_column(String(64))
    tax_id: Mapped[str | None] = mapped_column(String(16))


class Provider(Base, TimestampMixin):
    __tablename__ = "provider"
    id: Mapped[uuid.UUID] = _pk()
    practice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("practice.id"))
    npi: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(256))
    specialty: Mapped[str | None] = mapped_column(String(64))
    taxonomy_code: Mapped[str | None] = mapped_column(String(16))


class Patient(Base, TimestampMixin):
    __tablename__ = "patient"
    id: Mapped[uuid.UUID] = _pk()
    practice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("practice.id"))
    external_mrn: Mapped[str | None] = mapped_column(String(64))
    # --- PHI, encrypted at rest ---
    dob_enc: Mapped[str | None] = mapped_column(EncryptedString)
    name_enc: Mapped[str | None] = mapped_column(EncryptedString)


class Payer(Base, TimestampMixin):
    __tablename__ = "payer"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(256))
    payer_id_code: Mapped[str] = mapped_column(String(32), index=True)
    clearinghouse_id: Mapped[str | None] = mapped_column(String(32))
    is_medicare: Mapped[bool] = mapped_column(Boolean, default=False)


class Encounter(Base, TimestampMixin):
    __tablename__ = "encounter"
    id: Mapped[uuid.UUID] = _pk()
    practice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("practice.id"))
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"))
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("provider.id"))
    dos: Mapped[date] = mapped_column(Date)
    chart_ref: Mapped[str | None] = mapped_column(String(128))
    # --- PHI, encrypted at rest ---
    chart_text_enc: Mapped[str | None] = mapped_column(EncryptedString)
    place_of_service: Mapped[str | None] = mapped_column(String(4))


class Claim(Base, TimestampMixin):
    __tablename__ = "claim"
    id: Mapped[uuid.UUID] = _pk()
    practice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("practice.id"))
    encounter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("encounter.id"))
    payer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payer.id"))
    claim_control_number: Mapped[str] = mapped_column(String(64), index=True)
    total_charge: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    status: Mapped[str] = mapped_column(String(32), default="ingested")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filing_deadline: Mapped[date | None] = mapped_column(Date)
    appeal_deadline: Mapped[date | None] = mapped_column(Date)
    original_837_blob: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list[ClaimLine]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )


class ClaimLine(Base):
    __tablename__ = "claim_line"
    id: Mapped[uuid.UUID] = _pk()
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claim.id"))
    line_number: Mapped[int] = mapped_column(Integer)
    cpt_code: Mapped[str] = mapped_column(String(5))
    modifiers: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    icd_codes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    units: Mapped[int] = mapped_column(Integer, default=1)
    charge_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    allowed_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    paid_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    claim: Mapped[Claim] = relationship(back_populates="lines")


class Denial(Base, TimestampMixin):
    __tablename__ = "denial"
    id: Mapped[uuid.UUID] = _pk()
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claim.id"))
    claim_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("claim_line.id"))
    carc_code: Mapped[str] = mapped_column(String(8), index=True)
    rarc_codes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    group_code: Mapped[str | None] = mapped_column(String(2))
    denied_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    denial_date: Mapped[date | None] = mapped_column(Date)
    # Computed, INDEXED — a missed deadline is our liability (spec risk table).
    appeal_deadline: Mapped[date | None] = mapped_column(Date, index=True)
    triage_class: Mapped[str | None] = mapped_column(String(32))
    recoverability_score: Mapped[float | None] = mapped_column()  # 0-1, model output
    priority: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # $ × p(win)

    __table_args__ = (
        # Work queue: highest-value recoverable denials first.
        Index("ix_denial_priority", priority.desc()),
    )


class Appeal(Base, TimestampMixin):
    __tablename__ = "appeal"
    id: Mapped[uuid.UUID] = _pk()
    denial_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("denial.id"))
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    strategy: Mapped[str | None] = mapped_column(String(32))
    # Letters may contain de-identified chart context -> encrypt at rest.
    letter_text: Mapped[str | None] = mapped_column(EncryptedString)
    cited_policies: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    attachments: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(16), default="pending")
    recovered_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    outcome_date: Mapped[date | None] = mapped_column(Date)


class AuthRequest(Base, TimestampMixin):
    __tablename__ = "auth_request"
    id: Mapped[uuid.UUID] = _pk()
    encounter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("encounter.id"))
    payer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payer.id"))
    cpt_codes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    icd_codes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    submission_channel: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision: Mapped[str | None] = mapped_column(String(32))
    decision_date: Mapped[date | None] = mapped_column(Date)


class PolicyDoc(Base, TimestampMixin):
    __tablename__ = "policy_doc"
    id: Mapped[uuid.UUID] = _pk()
    payer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payer.id"))
    doc_type: Mapped[str] = mapped_column(String(32))  # LCD | NCD | commercial_policy
    cpt_codes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    title: Mapped[str] = mapped_column(String(512))
    url: Mapped[str | None] = mapped_column(Text)
    effective_date: Mapped[date | None] = mapped_column(Date)
    text: Mapped[str] = mapped_column(Text)  # public policy text — NOT PHI
    embedding: Mapped[list[float] | None] = mapped_column(Vector(_EMBED_DIM))


class AppealOutcomeStat(Base):
    """★ THE MOAT TABLE ★ — win rates nobody else has (spec §4 learning loop)."""

    __tablename__ = "appeal_outcome"
    id: Mapped[uuid.UUID] = _pk()
    payer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payer.id"))
    carc_code: Mapped[str] = mapped_column(String(8))
    specialty: Mapped[str] = mapped_column(String(64))
    strategy: Mapped[str] = mapped_column(String(32))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float | None] = mapped_column()
    avg_recovered: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    avg_days_to_resolution: Mapped[float | None] = mapped_column()
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "payer_id", "carc_code", "specialty", "strategy",
            name="uq_appeal_outcome_key",
        ),
    )


class AuditLog(Base):
    """★ COMPLIANCE ★ APPEND ONLY. No updates, no deletes (enforced by trigger)."""

    __tablename__ = "audit_log"
    id: Mapped[uuid.UUID] = _pk()
    actor: Mapped[str] = mapped_column(String(128))  # agent_name | user_id
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    # before/after may contain de-identified chart context -> encrypt at rest.
    before_json: Mapped[str | None] = mapped_column(EncryptedString)
    after_json: Mapped[str | None] = mapped_column(EncryptedString)
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))  # hash, never body
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class GuardrailBlock(Base):
    """★ COMPLIANCE ★ Every guardrail BLOCK, with the change it refused."""

    __tablename__ = "guardrail_block"
    id: Mapped[uuid.UUID] = _pk()
    claim_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("claim.id"))
    agent: Mapped[str] = mapped_column(String(128))
    attempted_change_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    rule_violated: Mapped[str] = mapped_column(String(64))
    resolved_by_user_id: Mapped[str | None] = mapped_column(String(64))
    resolution: Mapped[str | None] = mapped_column(String(256))
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
