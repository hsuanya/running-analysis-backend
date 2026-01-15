from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from db.engine import engine

async_session = async_sessionmaker(
    engine,
    expire_on_commit=False,
)

async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
