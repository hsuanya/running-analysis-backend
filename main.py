from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.run import router as run_router
from routes.upload import router as upload_router
from db.init_db import init_db

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://catslab.ee.ncku.edu.tw:9131"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(run_router, prefix="/api")
app.include_router(upload_router, prefix="/api")

@app.on_event("startup")
async def on_startup():
    await init_db()