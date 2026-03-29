"""
Async SQLAlchemy session and engine for TheCouncil.

Environment variable:
  DATABASE_URL — asyncpg connection string (e.g. postgresql+asyncpg://...)

Falls back gracefully so tests (which mock the DB layer) can import without
a real Postgres instance.
"""

from __future__ import annotations

import os
from typing import AsyncGenerator

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "")


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def _make_engine_and_session(url: str):  # type: ignore[return]
    if not url:
        return None, None
    engine = create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        echo=os.getenv("SQLALCHEMY_ECHO", "").lower() in ("1", "true"),
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory


_engine, _session_factory = _make_engine_and_session(DATABASE_URL)


def get_engine():
    """Return the global async engine (None when DATABASE_URL is unset)."""
    return _engine


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session."""
    if _session_factory is None:
        raise RuntimeError(
            "DATABASE_URL is not configured. "
            "Set it in .env or the environment before starting the server."
        )
    async with _session_factory() as session:
        yield session
