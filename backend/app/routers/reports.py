from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from typing import Optional, Any

from ..ingest import parse_report
from ..models import Report
from ..services.store import store

router = APIRouter(prefix="/api/reports", tags=["reports"])


class ReportListEntry(BaseModel):
    report_id: str
    source_name: str
    fight_count: int
    fight_names: list[str]


class ReportMeta(BaseModel):
    report_id: str
    source_name: str
    fights: list[dict[str, Any]]


@router.post("", response_model=ReportMeta)
async def upload_report(file: UploadFile = File(...)):
    raw_bytes = await file.read()
    try:
        import json as _json

        text = raw_bytes.decode("utf-8", errors="replace")
        data: Any
        try:
            data = _json.loads(text)
        except _json.JSONDecodeError:
            data = text
        report = parse_report(data, source_name=file.filename or "upload")
    except ValueError as ex:
        raise HTTPException(status_code=422, detail=f"Could not parse log: {ex}")
    rid = store.add(report)
    return _meta(rid, report)


@router.get("", response_model=list[ReportListEntry])
async def list_reports():
    out = []
    for rid in store.list_ids():
        r = store.get(rid)
        if r is None:
            continue
        out.append(
            ReportListEntry(
                report_id=rid,
                source_name=r.source_name,
                fight_count=len(r.fights),
                fight_names=[f.name for f in r.fights][:10],
            )
        )
    return out


@router.get("/{report_id}", response_model=ReportMeta)
async def get_report(report_id: str):
    r = store.get(report_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return _meta(report_id, r)


@router.delete("/{report_id}")
async def delete_report(report_id: str):
    if not store.delete(report_id):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"deleted": True}


def _meta(rid: str, r: Report) -> ReportMeta:
    fights = [
        {
            "fight_id": f.fight_id,
            "name": f.name,
            "outcome": f.outcome,
            "difficulty": f.difficulty,
            "size": f.size,
            "duration_seconds": round(f.duration_seconds, 1),
            "kill": f.kill,
            "boss_pct": f.boss_pct,
        }
        for f in r.fights
    ]
    return ReportMeta(report_id=rid, source_name=r.source_name, fights=fights)
