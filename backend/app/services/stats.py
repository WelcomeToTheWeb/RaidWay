"""Stats engine: computes per-player and raid-wide metrics for a fight.

All derived numbers live here so the LLM layer consumes consistent,
pre-computed facts rather than raw events.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..models import Actor, FightSummary, LogEvent, Report


def _spec_role(spec: str, class_name: str) -> str:
    s = (spec or class_name or "").lower()
    if any(k in s for k in ("heal", "resto", "restoration", "discipline", "holy", "mistweaver")):
        return "healer"
    if any(k in s for k in ("tank", "guardian", "protection", "brewmaster", "vengeance", "blood")):
        return "tank"
    if s:
        return "dps"
    return "unknown"


class PlayerStats(BaseModel):
    actor_id: int
    name: str = "Unknown"
    spec: str = ""
    class_name: str = ""
    role: str = "unknown"
    item_level: int = 0
    damage_done: int = 0
    damage_taken: int = 0
    healing_done: int = 0
    overhealing_done: int = 0
    healing_taken: int = 0
    absorbs: int = 0
    deaths: int = 0
    death_times_ms: list[int] = Field(default_factory=list)
    kills: int = 0
    damage_events: int = 0
    healing_events: int = 0
    casts: int = 0
    crits: int = 0
    ability_breakdown: dict[str, int] = Field(default_factory=dict)
    damage_on_targets: dict[str, int] = Field(default_factory=dict)
    first_event_ms: Optional[int] = None
    last_event_ms: Optional[int] = None
    activity_pct: float = 0.0

    @property
    def crit_rate(self) -> float:
        return self.crits / self.damage_events if self.damage_events else 0.0


class FightStats(BaseModel):
    fight_id: int
    encounter_name: str
    start_time_ms: int
    duration_seconds: float
    outcome: str
    kill: Optional[bool]
    boss_pct: float
    difficulty: str
    size: int
    players: list[PlayerStats] = Field(default_factory=list)
    total_damage: int = 0
    total_healing: int = 0
    total_deaths: int = 0
    top_damage: dict[str, int] = Field(default_factory=dict)
    top_healing: dict[str, int] = Field(default_factory=dict)
    deaths_by_name: dict[str, list[int]] = Field(default_factory=dict)
    timeline_damage: dict[str, dict[str, int]] = Field(default_factory=dict)
    timeline_healing: dict[str, dict[str, int]] = Field(default_factory=dict)

    @property
    def raid_dps(self) -> float:
        return self.total_damage / self.duration_seconds if self.duration_seconds > 0 else 0.0

    @property
    def raid_hps(self) -> float:
        return self.total_healing / self.duration_seconds if self.duration_seconds > 0 else 0.0

    def player(self, name: str) -> Optional[PlayerStats]:
        ln = name.lower().strip()
        for p in self.players:
            if p.name.lower() == ln:
                return p
        return None

    def player_by_id(self, actor_id: int) -> Optional[PlayerStats]:
        for p in self.players:
            if p.actor_id == actor_id:
                return p
        return None


def compute_fight_stats(report: Report, fight: FightSummary) -> FightStats:
    events = report.events_for_fight(fight)
    events.sort(key=lambda e: e.time)
    stats: dict[int, PlayerStats] = {}
    unknown_id = -1
    for aid in fight.combatants:
        actor = report.actor(aid)
        if actor is None or actor.type != "player":
            continue
        if not actor.declared:
            # Undeclared actor, likely a boss/NPC auto-created from damage events.
            # Heuristic: players receive healing or cast spells; bosses don't.
            involved = [e for e in events if e.source_id == aid or e.target_id == aid]
            is_player_like = any(e.source_id == aid and e.type in ("healing", "cast") for e in involved) or any(
                e.target_id == aid and e.type == "healing" for e in involved
            )
            if not is_player_like:
                continue
        role = actor.role or _spec_role(actor.spec, actor.class_name)
        stats[aid] = PlayerStats(
            actor_id=aid,
            name=actor.name,
            spec=actor.spec,
            class_name=actor.class_name,
            role=role,
            item_level=actor.item_level,
        )
    timeline_damage: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    timeline_healing: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in events:
        src = stats.get(e.source_id) if e.source_id is not None else None
        tgt = stats.get(e.target_id) if e.target_id is not None else None
        if src is None and e.source_id is None:
            key = unknown_id
            if key not in stats:
                stats[key] = PlayerStats(actor_id=key, name="Unknown Source")
            src = stats[key]
        if e.type == "damage":
            amt = e.hit.amount if e.hit else 0
            if src is not None:
                src.damage_events += 1
                src.damage_done += amt
                _bump(src.ability_breakdown, e.spell or "Unknown", amt)
                if e.target_name:
                    _bump(src.damage_on_targets, e.target_name, amt)
                if e.hit and e.hit.crit:
                    src.crits += 1
                if src.first_event_ms is None:
                    src.first_event_ms = e.time
                src.last_event_ms = e.time
                bucket = str(int((e.time - fight.start_time_ms) / 10000))
                timeline_damage[src.actor_id][bucket] += amt
            if tgt is not None:
                tgt.damage_taken += amt
        elif e.type == "healing":
            amt = e.heal.amount if e.heal else 0
            oh = e.heal.overheal if e.heal else 0
            if src is not None:
                src.healing_events += 1
                src.healing_done += amt
                src.overhealing_done += oh
                _bump(src.ability_breakdown, e.spell or "Unknown", amt)
                if src.first_event_ms is None:
                    src.first_event_ms = e.time
                src.last_event_ms = e.time
                bucket = str(int((e.time - fight.start_time_ms) / 10000))
                timeline_healing[src.actor_id][bucket] += amt
            if tgt is not None:
                tgt.healing_taken += amt
        elif e.type == "death":
            if tgt is not None:
                tgt.deaths += 1
                tgt.death_times_ms.append(e.time)
            elif e.target_name:
                ps = _ensure_named(stats, e.target_name)
                ps.deaths += 1
                ps.death_times_ms.append(e.time)
        elif e.type == "cast":
            if src is not None:
                src.casts += 1
                if src.first_event_ms is None:
                    src.first_event_ms = e.time
                src.last_event_ms = e.time
    duration_ms = fight.duration_ms or 1
    for ps in stats.values():
        active_ms = 0
        if ps.first_event_ms is not None and ps.last_event_ms is not None:
            active_ms = max(ps.last_event_ms - ps.first_event_ms, 0)
        ps.activity_pct = round(100.0 * active_ms / duration_ms, 1)
    players = sorted(
        (p for p in stats.values() if p.actor_id != -1),
        key=lambda p: (p.role != "tank", p.role != "healer", -max(p.damage_done, p.healing_done)),
    )
    fs = FightStats(
        fight_id=fight.fight_id,
        encounter_name=fight.name,
        start_time_ms=fight.start_time_ms,
        duration_seconds=round(fight.duration_seconds, 1),
        outcome=fight.outcome,
        kill=fight.kill,
        boss_pct=fight.boss_pct,
        difficulty=fight.difficulty,
        size=fight.size,
        players=players,
        total_damage=sum(p.damage_done for p in players),
        total_healing=sum(p.healing_done for p in players),
        total_deaths=sum(p.deaths for p in players),
    )
    fs.top_damage = {
        p.name: p.damage_done for p in sorted(players, key=lambda x: -x.damage_done)[:10] if p.damage_done > 0
    }
    fs.top_healing = {
        p.name: p.healing_done for p in sorted(players, key=lambda x: -x.healing_done)[:10] if p.healing_done > 0
    }
    fs.deaths_by_name = {p.name: p.death_times_ms for p in players if p.deaths > 0}
    fs.timeline_damage = {
        stats[aid].name: dict(buckets)
        for aid, buckets in timeline_damage.items()
        if aid in stats and buckets
    }
    fs.timeline_healing = {
        stats[aid].name: dict(buckets)
        for aid, buckets in timeline_healing.items()
        if aid in stats and buckets
    }
    return fs


def _bump(d: dict[str, int], k: str, v: int) -> None:
    d[k] = d.get(k, 0) + v


def _ensure_named(stats: dict[int, PlayerStats], name: str) -> PlayerStats:
    for p in stats.values():
        if p.name == name:
            return p
    ps = PlayerStats(actor_id=abs(hash(name)) % 10_000_000, name=name)
    stats[ps.actor_id] = ps
    return ps


def compute_report_stats(report: Report) -> list[FightStats]:
    return [compute_fight_stats(report, f) for f in report.fights]


def player_summary_dicts(fs: FightStats) -> list[dict[str, Any]]:
    rows = []
    for p in fs.players:
        rows.append(
            {
                "name": p.name,
                "spec": p.spec,
                "role": p.role,
                "damage": p.damage_done,
                "dps": round(p.damage_done / fs.duration_seconds, 1) if fs.duration_seconds else 0,
                "healing": p.healing_done,
                "hps": round(p.healing_done / fs.duration_seconds, 1) if fs.duration_seconds else 0,
                "damage_taken": p.damage_taken,
                "deaths": p.deaths,
                "activity_pct": p.activity_pct,
                "crit_rate": round(p.crit_rate, 3),
                "casts": p.casts,
            }
        )
    return rows
