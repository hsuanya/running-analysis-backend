from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = "sqlite+aiosqlite:///./running.db"
# postgresql+asyncpg://user:password@host/db

engine = create_async_engine(
    DATABASE_URL,
    echo=True,
)