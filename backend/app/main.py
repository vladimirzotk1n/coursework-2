from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.db import apply_schema, close_pool
from app.features.auth.router import router as auth_router
from app.features.experiments.router import router as experiments_router
from app.features.files.router import router as files_router
from app.features.reports.router import router as reports_router
from app.features.runs.router import router as runs_router
from app.features.series.router import router as series_router
from app.features.users.router import router as users_router
from app.storage.s3 import ensure_bucket


@asynccontextmanager
async def lifespan(app: FastAPI):
    await apply_schema()
    await ensure_bucket()
    yield
    await close_pool()


app = FastAPI(title="Experiments API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(users_router)
app.include_router(experiments_router)
app.include_router(runs_router)
app.include_router(series_router)
app.include_router(files_router)
app.include_router(reports_router)
