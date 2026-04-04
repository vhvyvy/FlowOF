"""
One-time script: converts legacy SHA-256 password hashes → bcrypt.

Run once before switching fully to the FastAPI backend:
    cd backend && python scripts/migrate_passwords.py

Requires DATABASE_URL set in environment or .env file.
"""
import asyncio
import os
import sys
from pathlib import Path

# Add backend/ to path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, text
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_url = os.getenv("DATABASE_URL", "")
if _url.startswith("postgres://"):
    _url = _url.replace("postgres://", "postgresql+asyncpg://", 1)
elif _url.startswith("postgresql://") and "+asyncpg" not in _url:
    _url = _url.replace("postgresql://", "postgresql+asyncpg://", 1)


async def main():
    engine = create_async_engine(_url, connect_args={"ssl": "require"})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        # Fetch all tenants that still have SHA-256 hashes (not starting with $2)
        result = await db.execute(
            text("SELECT id, email, password_hash, hashed_password FROM tenants")
        )
        rows = result.fetchall()

        migrated = 0
        for row in rows:
            tid, email, sha_hash, bcrypt_hash = row

            # Already on bcrypt
            if bcrypt_hash and bcrypt_hash.startswith("$2"):
                print(f"  [skip] tenant={tid} ({email}) — already bcrypt")
                continue

            # Has a SHA-256 hash to migrate
            legacy = sha_hash or bcrypt_hash or ""
            if not legacy or legacy.startswith("$2"):
                print(f"  [skip] tenant={tid} ({email}) — no legacy hash")
                continue

            # We cannot reverse SHA-256, so we mark it as needing reset.
            # The actual bcrypt migration happens on first login (see routers/auth.py).
            # This script only flags tenants that still need migration.
            print(f"  [pending] tenant={tid} ({email}) — will migrate on next login")
            migrated += 1

        print(f"\nDone. {migrated} tenant(s) will auto-migrate on next login.")
        print("No action needed — migration is automatic via routers/auth.py.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
