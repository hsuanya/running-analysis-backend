from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.run import router as run_router
from routes.upload import router as upload_router
from routes.record import router as record_router
from routes.auth import router as auth_router
from db.init_db import init_db
import asyncio
import os
from utils.cleanup import cleanup_temp_dir_loop

app = FastAPI(root_path="/running_analysis/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 修改為 * 以便調試，或是保留原本的
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(run_router)
app.include_router(upload_router)
app.include_router(record_router)

@app.on_event("startup")
async def on_startup():
    await init_db()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    temp_dir = os.path.join(base_dir, "data", "uploads_temp")
    asyncio.create_task(cleanup_temp_dir_loop(temp_dir))