from fastapi import APIRouter, HTTPException
from typing import Any, Optional

from pydantic import BaseModel

from ..models import Report
from ..services.stats import compute_fight_stats, player_summary_dicts
from ..services.store import store

router = APIRouter(prefix="/api/reports/{report_id}/fights", tags=["fights"])


class FightStatsOut(BaseModel):
    fight_id: int
    encounter_name: str
    outcome: str
    duration_seconds: float
    difficulty: str
    size: int
    boss_pct: float
    total_damage: int
    total_healing: int
    total_deaths: int
    raid_dps: float
    raid_hps: float
    players: list[dict[str, Any]]
    top_damage: dict[str, int]
    top_healing: dict[str, int]
    deaths: dict[str, list[float]]
    timeline_damage: dict[str, dict[str, int]]
    timeline_healing: dict[str, dict[str, int]]


@router.get("", response_model=list[dict[str, Any]])
async def list_fights(report_id: str):
    r = store.get(report_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return [
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


@router.get("/{fight_id}/stats", response_model=FightStatsOut)
async def fight_stats(report_id: str, fight_id: int):
    r = store.get(report_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Report not found")
    fight = r.fight(fight_id)
    if fight is None:
        raise HTTPException(status_code=404, detail="Fight not found")
    fs = compute_fight_stats(r, fight)
    return FightStatsOut(
        fight_id=fs.fight_id,
        encounter_name=fs.encounter_name,
        outcome=fs.outcome,
        duration_seconds=fs.duration_seconds,
        difficulty=fs.difficulty,
        size=fs.size,
        boss_pct=fs.boss_pct,
        total_damage=fs.total_damage,
        total_healing=fs.total_healing,
        total_deaths=fs.total_deaths,
        raid_dps=round(fs.raid_dps, 1),
        raid_hps=round(fs.raid_hps, 1),
        players=player_summary_dicts(fs),
        top_damage=fs.top_damage,
        top_healing=fs.top_healing,
        deaths={k: [round(t / 1000.0, 1) for t in v] for k, v in fs.deaths_by_name.items()},
        timeline_damage=fs.timeline_damage,
        timeline_healing=fs.timeline_healing,
    )
