"""
Database migration bootstrap for TheCouncil.

Run directly: python -m council.db.migrations

Creates all tables defined in `council.db.models` using SQLAlchemy's
`create_all` (synchronous DDL over the async engine). Safe to call on every
startup — SQLAlchemy only creates missing tables.
"""

from __future__ import annotations

import asyncio
import logging

from council.db.session import Base, get_engine

log = logging.getLogger(__name__)


async def _run_migrations() -> None:
    engine = get_engine()
    if engine is None:
        log.warning("DATABASE_URL not set — skipping schema creation.")
        return

    # Import models so their metadata is registered on Base
    import council.db.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("Database schema up to date.")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run_migrations())


if __name__ == "__main__":
    main()
