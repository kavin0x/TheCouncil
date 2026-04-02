"""
SQLAlchemy ORM models for TheCouncil.

Tables:
  users          — registered user accounts (email, tier, ToS acceptance)
  deliberations  — council debate sessions (top-level entity)
  personas       — saved agent personas per user
  artifacts      — synthesized output artifacts from a deliberation
  usage_events   — per-run usage accounting for billing
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Float,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from council.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# User account
# ---------------------------------------------------------------------------


class User(Base):
    """A registered user account."""

    __tablename__ = "users"

    id: str = Column(String(36), primary_key=True, default=_uuid)
    email: str = Column(String(255), nullable=False, unique=True, index=True)
    tier: str = Column(String(32), nullable=False, default="basic")
    created_at: float = Column(Float, nullable=False, default=_now)

    # Terms-of-service acceptance — null means not yet accepted.
    # Stored as a Unix timestamp (float); tos_version records the version string
    # (e.g. "2026-04-01") accepted at that moment.
    tos_accepted_at: float | None = Column(Float, nullable=True)
    tos_version: str | None = Column(String(32), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.id,
            "email": self.email,
            "tier": self.tier,
            "created_at": self.created_at,
            "tos_accepted_at": self.tos_accepted_at,
            "tos_version": self.tos_version,
        }


# ---------------------------------------------------------------------------
# Deliberation (= a council run)
# ---------------------------------------------------------------------------


class Deliberation(Base):
    """A single multi-agent council deliberation run."""

    __tablename__ = "deliberations"

    id: str = Column(String(36), primary_key=True, default=_uuid)
    owner_id: str = Column(String(255), nullable=False, index=True)
    question: str = Column(Text, nullable=False)
    status: str = Column(String(32), nullable=False, default="pending", index=True)
    config: dict[str, Any] = Column(JSONB, nullable=False, default=dict)
    result: dict[str, Any] | None = Column(JSONB, nullable=True)
    error: str | None = Column(Text, nullable=True)
    created_at: float = Column(Float, nullable=False, default=_now)
    started_at: float | None = Column(Float, nullable=True)
    finished_at: float | None = Column(Float, nullable=True)

    # relationships
    artifact: "Artifact | None" = relationship(
        "Artifact", back_populates="deliberation", uselist=False, cascade="all, delete-orphan"
    )
    usage_events: list["UsageEvent"] = relationship(
        "UsageEvent", back_populates="deliberation", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.id,
            "owner_id": self.owner_id,
            "question": self.question,
            "status": self.status,
            "config": self.config,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------


class Persona(Base):
    """A saved agent persona owned by a user."""

    __tablename__ = "personas"

    id: str = Column(String(36), primary_key=True, default=_uuid)
    owner_id: str = Column(String(255), nullable=False, index=True)
    name: str = Column(String(100), nullable=False)
    mode: str = Column(String(32), nullable=False, default="custom")
    system_prompt: str = Column(Text, nullable=False)
    description: str | None = Column(Text, nullable=True)
    mbti: str | None = Column(String(4), nullable=True)
    job_role: str | None = Column(String(64), nullable=True)
    created_at: float = Column(Float, nullable=False, default=_now)
    updated_at: float = Column(Float, nullable=False, default=_now, onupdate=_now)
    is_active: bool = Column(Boolean, nullable=False, default=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "persona_id": self.id,
            "owner_id": self.owner_id,
            "name": self.name,
            "mode": self.mode,
            "system_prompt": self.system_prompt,
            "description": self.description,
            "mbti": self.mbti,
            "job_role": self.job_role,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------


class Artifact(Base):
    """Structured deliberation artifact synthesised from a completed run."""

    __tablename__ = "artifacts"

    id: str = Column(String(36), primary_key=True, default=_uuid)
    deliberation_id: str = Column(
        String(36), ForeignKey("deliberations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    owner_id: str = Column(String(255), nullable=False, index=True)
    question: str = Column(Text, nullable=False)

    # Structured content
    decision_rationale: str = Column(Text, nullable=False, default="")
    recommended_action: str = Column(Text, nullable=False, default="")
    dissenting_opinions: list[dict[str, Any]] = Column(JSONB, nullable=False, default=list)
    consensus_resolution: str = Column(Text, nullable=False, default="")
    agent_votes: dict[str, Any] = Column(JSONB, nullable=False, default=dict)
    top3_resolutions: list[dict[str, Any]] = Column(JSONB, nullable=False, default=list)
    full_result: dict[str, Any] = Column(JSONB, nullable=False, default=dict)

    format: str = Column(String(32), nullable=False, default="json")  # json | markdown | pdf
    created_at: float = Column(Float, nullable=False, default=_now)

    # relationship
    deliberation: "Deliberation" = relationship("Deliberation", back_populates="artifact")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.id,
            "deliberation_id": self.deliberation_id,
            "owner_id": self.owner_id,
            "question": self.question,
            "decision_rationale": self.decision_rationale,
            "recommended_action": self.recommended_action,
            "dissenting_opinions": self.dissenting_opinions,
            "consensus_resolution": self.consensus_resolution,
            "agent_votes": self.agent_votes,
            "top3_resolutions": self.top3_resolutions,
            "format": self.format,
            "created_at": self.created_at,
        }

    def to_markdown(self) -> str:
        """Render artifact as a formatted Markdown document."""
        lines = [
            "# TheCouncil Deliberation Artifact",
            "",
            f"**Question:** {self.question}",
            "",
            "---",
            "",
            "## Decision Rationale",
            "",
            self.decision_rationale,
            "",
            "## Recommended Action",
            "",
            self.recommended_action,
            "",
        ]

        if self.dissenting_opinions:
            lines += ["## Dissenting Opinions", ""]
            for opinion in self.dissenting_opinions:
                agent = opinion.get("agent", "Unknown")
                view = opinion.get("opinion", "")
                lines += [f"**{agent}:** {view}", ""]

        if self.top3_resolutions:
            lines += ["## Top Resolutions", ""]
            for res in self.top3_resolutions:
                rank = res.get("rank", "?")
                agent = res.get("agent", "Unknown")
                resolution = res.get("resolution", "")
                summary = res.get("summary", "")
                lines += [
                    f"### Resolution #{rank} — {agent}",
                    "",
                    resolution,
                    "",
                    f"*{summary}*",
                    "",
                ]

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Usage event
# ---------------------------------------------------------------------------


class UsageEvent(Base):
    """Records a single billable usage event for audit and billing."""

    __tablename__ = "usage_events"

    id: int = Column(BigInteger, primary_key=True, autoincrement=True)
    deliberation_id: str = Column(
        String(36), ForeignKey("deliberations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    owner_id: str = Column(String(255), nullable=False, index=True)
    event_type: str = Column(String(64), nullable=False)  # run_started | run_completed | run_failed
    tier: str = Column(String(32), nullable=False, default="basic")
    metadata: dict[str, Any] = Column(JSONB, nullable=False, default=dict)
    recorded_at: float = Column(Float, nullable=False, default=_now)

    # relationship
    deliberation: "Deliberation | None" = relationship(
        "Deliberation", back_populates="usage_events"
    )
