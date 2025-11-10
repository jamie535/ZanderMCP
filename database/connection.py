"""Database connection management with async support."""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.pool import NullPool
from dotenv import load_dotenv

from .models import Base

load_dotenv()


class DatabaseManager:
    """Manages database connection pool and sessions."""

    def __init__(
        self,
        database_url: str | None = None,
        pool_size: int = 20,
        max_overflow: int = 10,
        pool_timeout: float = 30.0,
    ):
        """Initialize database manager.

        Args:
            database_url: PostgreSQL connection URL (from .env if not provided)
            pool_size: Connection pool size
            max_overflow: Max connections beyond pool_size
            pool_timeout: Timeout for getting connection from pool
        """
        self.database_url = database_url or os.getenv("POSTGRES_URL")
        if not self.database_url:
            raise ValueError("POSTGRES_URL environment variable not set")

        # Convert postgres:// to postgresql+asyncpg://
        if self.database_url.startswith("postgres://"):
            self.database_url = self.database_url.replace(
                "postgres://", "postgresql+asyncpg://", 1
            )
        elif not self.database_url.startswith("postgresql+asyncpg://"):
            self.database_url = f"postgresql+asyncpg://{self.database_url}"

        self.engine: AsyncEngine = create_async_engine(
            self.database_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            echo=False,  # Set to True for SQL debugging
        )

        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def initialize(self):
        """Initialize database schema and TimescaleDB hypertables."""
        async with self.engine.begin() as conn:
            # Create all tables
            await conn.run_sync(Base.metadata.create_all)

            # Enable TimescaleDB extension (if not already enabled)
            await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")

            # Create hypertables for time-series optimization
            # Check if already a hypertable before creating
            await conn.execute("""
                SELECT create_hypertable(
                    'predictions',
                    'timestamp',
                    if_not_exists => TRUE,
                    migrate_data => TRUE
                );
            """)

            await conn.execute("""
                SELECT create_hypertable(
                    'stream_samples',
                    'timestamp',
                    if_not_exists => TRUE,
                    migrate_data => TRUE
                );
            """)

            # Create indexes for common queries
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_predictions_session_time
                ON predictions (session_id, timestamp DESC);
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_predictions_user_time
                ON predictions (user_id, timestamp DESC);
            """)

            print("Database schema initialized successfully")

    async def close(self):
        """Close database connection pool."""
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get a database session.

        Usage:
            async with db_manager.session() as session:
                result = await session.execute(query)
        """
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def get_session(self) -> AsyncSession:
        """Get a new database session (caller responsible for closing)."""
        return self.session_factory()


# Global database manager instance
_db_manager: DatabaseManager | None = None


def get_db_manager(
    database_url: str | None = None,
    pool_size: int = 20,
    max_overflow: int = 10,
) -> DatabaseManager:
    """Get or create the global database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager(
            database_url=database_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )
    return _db_manager


async def init_database():
    """Initialize database schema and hypertables."""
    db = get_db_manager()
    await db.initialize()


async def close_database():
    """Close database connections."""
    global _db_manager
    if _db_manager:
        await _db_manager.close()
        _db_manager = None
