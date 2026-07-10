from typing import AsyncGenerator
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.core.config import settings
from app.core.logging import db_logger

# 1. Async Database Engine and Session Factory (For FastAPI Operations)
async_engine = create_async_engine(
    settings.ASYNC_DATABASE_URL,
    echo=False,  # Set to True for verbose SQLAlchemy queries logging in debugging
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=10
)

async_session_factory = async_sessionmaker(
    bind=async_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False
)

# 2. Sync Database Engine (Specifically for Alembic migrations compatibility)
sync_engine = create_engine(
    settings.SYNC_DATABASE_URL,
    pool_pre_ping=True
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency yielding async session instances. Automatically rolls back on failure."""
    db_logger.debug("Creating new async database session.")
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
            db_logger.debug("Database session transaction committed.")
        except Exception as e:
            await session.rollback()
            db_logger.error(f"Database session transaction rolled back due to: {str(e)}")
            raise e
        finally:
            await session.close()
            db_logger.debug("Database session closed.")
