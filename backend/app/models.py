"""Core data models for normalized combat reports.

A *report* is a collection of fights; each fight has actors, and a flat event
stream. Stats are computed per (fight, actor) from the event stream.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Encounter(BaseModel):
    name: str = "Unknown Encounter"
    encounter_id: Optional[int] = None
    fight_id: Optional[int] = None


class Actor(BaseModel):
    id: int
    name: str
    type: str = "player"
    spec: str = ""
    class_name: str = ""
    role: str = ""
    item_level: int = 0
    declared: bool = False


class Hit(BaseModel):
    amount: int = 0
    unmitigated: int = 0
    mitigated: int = 0
    absorbed: int = 0
    crit: bool = False
    hit_type: str = ""
    overkill: int = 0


class HealEvent(BaseModel):
    amount: int = 0
    overheal: int = 0


class DeathEvent(BaseModel):
    killer_id: Optional[int] = None


class LogEvent(BaseModel):
    type: str
    time: int = 0
    source_id: Optional[int] = None
    source_name: Optional[str] = None
    target_id: Optional[int] = None
    target_name: Optional[str] = None
    spell: str = ""
    spell_id: Optional[int] = None
    hit: Optional[Hit] = None
    heal: Optional[HealEvent] = None
    death: Optional[DeathEvent] = None
    cast_success: bool = False
    buff_uptime: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def amount(self) -> int:
        if self.hit is not None:
            return self.hit.amount
        if self.heal is not None:
            return self.heal.amount
        return 0


class FightSummary(BaseModel):
    fight_id: int
    encounter: Encounter = Field(default_factory=Encounter)
    start_time_ms: int = 0
    end_time_ms: int = 0
    zone: str = ""
    difficulty: str = ""
    size: int = 20
    kill: Optional[bool] = None
    boss_pct: float = 0.0
    report_title: str = ""
    combatants: list[int] = Field(default_factory=list)

    @property
    def name(self) -> str:
        return self.encounter.name

    @property
    def duration_ms(self) -> int:
        return max(self.end_time_ms - self.start_time_ms, 0)

    @property
    def duration_seconds(self) -> float:
        return self.duration_ms / 1000.0

    @property
    def outcome(self) -> str:
        if self.kill is True:
            return "Kill"
        if self.kill is False:
            return "Wipe"
        return "Unknown"


class Report(BaseModel):
    source_name: str = "upload"
    fights: list[FightSummary] = Field(default_factory=list)
    actors: dict[int, Actor] = Field(default_factory=dict)
    events: list[LogEvent] = Field(default_factory=list)

    def _recompute_fight_actors(self) -> None:
        for f in self.fights:
            ids = set(f.combatants)
            for e in self.events:
                if e.time >= f.start_time_ms or not self.fights:
                    if e.source_id is not None:
                        ids.add(e.source_id)
                    if e.target_id is not None:
                        ids.add(e.target_id)
            f.combatants = sorted(ids)

    def fight(self, fight_id: Optional[int] = None) -> Optional["FightSummary"]:
        if fight_id is None:
            return self.fights[0] if self.fights else None
        for f in self.fights:
            if f.fight_id == fight_id:
                return f
        return None

    def actor(self, actor_id: int) -> Optional[Actor]:
        return self.actors.get(actor_id)

    def events_for_fight(self, fight: FightSummary) -> list[LogEvent]:
        out = []
        for e in self.events:
            if e.time >= fight.start_time_ms and e.time <= fight.end_time_ms:
                out.append(e)
        return out
