"""Analysis service: builds LLM prompts from fight stats and parses structured coaching."""

from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..models import Report
from ..services import llm as llm_mod
from ..services.stats import FightStats, compute_fight_stats, player_summary_dicts
from ..services.store import ReportStore


SYSTEM_PROMPT = """\
You are an expert raid analyst in the style of WarcraftLogs. You receive structured combat \
statistics for a World of Warcraft raid fight and a question from either a player or a raid leader.

Rules:
- Ground every claim in the provided numbers. Quote the specific stats you rely on.
- Distinguish facts (from the data) from hypotheses (things to verify in replays/logs).
- Be direct and actionable: say what to change and why.
- If the data is insufficient to answer, say exactly what extra data is needed.
- Keep answers under ~400 words unless asked for a full report.
- Format with short markdown sections and bullet points.
"""


class CoachingReport(BaseModel):
    fight_id: int
    encounter_name: str
    outcome: str
    headline: str
    raid_focus: list[str] = Field(default_factory=list)
    player_focus: list[dict[str, Any]] = Field(default_factory=list)
    llm_raw: str = ""


class ChatAnswer(BaseModel):
    answer: str
    fight_id: int
    question: str


def _fight_context(fs: FightStats, focus_player: Optional[str] = None) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "fight": {
            "encounter": fs.encounter_name,
            "difficulty": fs.difficulty,
            "size": fs.size,
            "outcome": fs.outcome,
            "boss_pct": fs.boss_pct,
            "duration_seconds": fs.duration_seconds,
            "total_damage": fs.total_damage,
            "total_healing": fs.total_healing,
            "total_deaths": fs.total_deaths,
            "raid_dps": round(fs.raid_dps, 1),
            "raid_hps": round(fs.raid_hps, 1),
        },
        "players": player_summary_dicts(fs),
        "top_damage": fs.top_damage,
        "top_healing": fs.top_healing,
        "deaths": {name: [round(t / 1000.0, 1) for t in times] for name, times in fs.deaths_by_name.items()},
        "timeline_damage_10s_buckets": fs.timeline_damage,
        "timeline_healing_10s_buckets": fs.timeline_healing,
    }
    if focus_player:
        p = fs.player(focus_player)
        if p is not None:
            top_abilities = dict(sorted(p.ability_breakdown.items(), key=lambda kv: -kv[1])[:12])
            ctx["focus_player"] = {
                **player_summary_dicts(fs)[
                    next((i for i, row in enumerate(player_summary_dicts(fs)) if row["name"] == p.name), 0)
                ],
                "ability_breakdown": top_abilities,
                "damage_on_targets": dict(sorted(p.damage_on_targets.items(), key=lambda kv: -kv[1])[:8]),
                "death_times_seconds": [round(t / 1000.0, 1) for t in p.death_times_ms],
            }
    return ctx


def _prompt_for(question: str, ctx: dict[str, Any]) -> str:
    return (
        "Combat data (JSON):\n"
        + json.dumps(ctx, indent=2, default=str)
        + "\n\nQuestion: "
        + question.strip()
    )


def analyze_fight(
    store: ReportStore,
    report_id: str,
    fight_id: Optional[int],
    question: Optional[str] = None,
    focus_player: Optional[str] = None,
    provider: Optional[llm_mod.LLMProvider] = None,
) -> CoachingReport:
    report = store.get(report_id)
    if report is None:
        raise KeyError(f"Report '{report_id}' not found.")
    fight = report.fight(fight_id)
    if fight is None:
        raise KeyError(f"Fight {fight_id} not found in report '{report_id}'.")
    fs = compute_fight_stats(report, fight)
    ctx = _fight_context(fs, focus_player)
    q = (question or "").strip()
    if focus_player and not q:
        q = f"What can {focus_player} do better in this fight?"
    elif not q:
        q = "What can the raid do better in this fight? Cover damage output, deaths, healing, and coordination."
    prov = provider or llm_mod.get_provider()
    resp = prov.complete(
        system=SYSTEM_PROMPT,
        user=_prompt_for(q, ctx),
        model=None,
    )
    return CoachingReport(
        fight_id=fs.fight_id,
        encounter_name=fs.encounter_name,
        outcome=fs.outcome,
        headline=q,
        raid_focus=[],
        player_focus=[],
        llm_raw=resp.text,
    )


def chat_about_fight(
    store: ReportStore,
    report_id: str,
    fight_id: Optional[int],
    question: str,
    focus_player: Optional[str] = None,
    history: Optional[list[dict[str, str]]] = None,
    provider: Optional[llm_mod.LLMProvider] = None,
) -> ChatAnswer:
    report = store.get(report_id)
    if report is None:
        raise KeyError(f"Report '{report_id}' not found.")
    fight = report.fight(fight_id)
    if fight is None:
        raise KeyError(f"Fight {fight_id} not found in report '{report_id}'.")
    fs = compute_fight_stats(report, fight)
    ctx = _fight_context(fs, focus_player)
    prov = provider or llm_mod.get_provider()
    convo = ""
    if history:
        for m in history[-6:]:
            role = "Player" if m.get("role") in ("user", "player") else "Analyst"
            content = (m.get("content") or "").strip()
            if content:
                convo += f"{role}: {content}\n"
        convo += "\n"
    user_prompt = ""
    if convo:
        user_prompt += "Previous conversation:\n" + convo
    user_prompt += _prompt_for(question, ctx)
    resp = prov.complete(system=SYSTEM_PROMPT, user=user_prompt)
    return ChatAnswer(answer=resp.text, fight_id=fs.fight_id, question=question)


def generate_report(
    store: ReportStore,
    report_id: str,
    fight_id: Optional[int],
    provider: Optional[llm_mod.LLMProvider] = None,
) -> CoachingReport:
    return analyze_fight(
        store,
        report_id,
        fight_id,
        question=None,
        focus_player=None,
        provider=provider,
    )


def generate_player_report(
    store: ReportStore,
    report_id: str,
    fight_id: Optional[int],
    player_name: str,
    provider: Optional[llm_mod.LLMProvider] = None,
) -> CoachingReport:
    return analyze_fight(
        store,
        report_id,
        fight_id,
        question=f"What can {player_name} do better in this fight? Focus on rotational gaps, cooldown usage, deaths, and downtime.",
        focus_player=player_name,
        provider=provider,
    )
