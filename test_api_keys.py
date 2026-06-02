#!/usr/bin/env python3
"""
Quick integration test for API key functionality
"""
import asyncio
import os
import sys
import traceback

# Unset DATABASE_URL to use the .env file
if 'DATABASE_URL' in os.environ:
    del os.environ['DATABASE_URL']

from dotenv import load_dotenv
load_dotenv()

from council.db.session import get_engine
from council.db.models import ApiKey, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def main():
    engine = get_engine()
    if not engine:
        print("❌ Database not configured")
        return False
    
    # Get a session and check the api_keys table
    async with AsyncSession(engine) as session:
        # Query API keys
        result = await session.execute(select(ApiKey))
        keys = result.scalars().all()
        
        print(f"✅ Database connection: OK")
        print(f"✅ API Keys table: Found {len(keys)} keys in database")
        
        for key in keys:
            print(f"- id: {key.id} name: {key.name} created_by: {key.created_by} active: {key.is_active}")
        
        return True


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
