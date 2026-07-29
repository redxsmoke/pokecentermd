import asyncpg
import os

pool = None


async def init_db():
    """
    Initialize the asyncpg connection pool with proper error handling.
    Prevents silent failures that break modal followups and broadcasts.
    """
    global pool

    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        print("❌ DATABASE_URL is missing from environment variables")
        pool = None
        return

    try:
        pool = await asyncpg.create_pool(database_url)
        print("✅ Database connected")
    except Exception as e:
        print("❌ Database connection failed:", e)
        pool = None


def get_pool():
    """
    Return the active pool or raise a clear error if not initialized.
    Prevents silent NoneType crashes inside modals.
    """
    if pool is None:
        raise RuntimeError("❌ Database pool is not initialized — init_db() failed")
    return pool
