"""
Async SQLAlchemy session and engine for TheCouncil.

Environment variable:
  DATABASE_URL — database connection string
    - PostgreSQL: postgresql+asyncpg://user:password@host:port/database
    - SQLite: sqlite+aiosqlite:///path/to/database.db

Default: SQLite database at ./council.db

Falls back gracefully so tests (which mock the DB layer) can import without
a real database instance.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

# Default to SQLite; can be overridden with DATABASE_URL environment variable
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./council.db")


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def _make_engine_and_session(url: str):  # type: ignore[return]
    if not url:
        return None, None
    
    # SQLite-specific configuration
    is_sqlite = "sqlite" in url
    
    if is_sqlite:
        # SQLite doesn't support the same pool features as PostgreSQL
        engine = create_async_engine(
            url,
            echo=os.getenv("SQLALCHEMY_ECHO", "").lower() in ("1", "true"),
            connect_args={"timeout": 15},  # Connection timeout
        )
    else:
        # PostgreSQL and other databases with connection pooling
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


async def get_session_dep() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session."""
    if _session_factory is None:
        raise RuntimeError(
            "Database not configured. "
            "Set DATABASE_URL in the environment or ensure the default SQLite database can be created."
        )
    async with _session_factory() as session:
        yield session


# Keep the old name as an alias for backward compatibility with existing Depends() usages.
get_session = get_session_dep


@asynccontextmanager
async def get_session_ctx():
    """Async context manager for a database session (for use outside FastAPI dependency injection)."""
    if _session_factory is None:
        raise RuntimeError(
            "Database not configured. "
            "Set DATABASE_URL in the environment or ensure the default SQLite database can be created."
        )
    async with _session_factory() as session:
        yield session
