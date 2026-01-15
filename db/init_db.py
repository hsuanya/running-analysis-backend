from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import SQLModel
from db.engine import engine  # 你的 async engine
from db_models import *       # 確保所有 model 被 import

async def init_db():
    # 建立所有表格
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
