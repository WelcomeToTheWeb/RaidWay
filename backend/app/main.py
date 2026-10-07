import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routers import analysis, fights, reports
from .services import llm as llm_mod

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Raid Analyst API",
    version="0.1.0",
    description="Ingest raid combat logs, compute fight stats, and get LLM-powered coaching.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reports.router)
app.include_router(fights.router)
app.include_router(analysis.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "llm": llm_mod.provider_status()}


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_CANDIDATES = [
    Path(os.environ.get("SAMPLES_DIR", "")) if os.environ.get("SAMPLES_DIR") else None,
    _REPO_ROOT / "samples",
    Path("/app/samples"),
]
_SAMPLES_DIR = next((d for d in _SAMPLE_CANDIDATES if d and d.is_dir()), None)
if _SAMPLES_DIR is not None:
    app.mount("/samples", StaticFiles(directory=str(_SAMPLES_DIR)), name="samples")

_STATIC_ENV = os.environ.get("FRONTEND_DIST_DIR", "")
_STATIC_CANDIDATES = [
    Path(_STATIC_ENV) if _STATIC_ENV else None,
    _REPO_ROOT / "frontend" / "dist",
    Path("/app/frontend_dist"),
]
_STATIC_DIR = next((d for d in _STATIC_CANDIDATES if d and d.is_dir()), None)
if _STATIC_DIR is not None:
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="ui")
