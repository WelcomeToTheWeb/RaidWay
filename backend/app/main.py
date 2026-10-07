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


_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
if _SAMPLES_DIR.is_dir():
    app.mount("/samples", StaticFiles(directory=str(_SAMPLES_DIR)), name="samples")

_STATIC_DIR = Path(os.environ.get("FRONTEND_DIST_DIR", "")) if os.environ.get("FRONTEND_DIST_DIR") else Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="ui")
