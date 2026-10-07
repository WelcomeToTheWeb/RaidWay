"""Log normalization.

Ingest is intentionally liberal: we accept combat logs in several shapes and
normalize them into an internal :class:`Report` model. Supported inputs:

1. WCL events-v2 style arrays of typed event objects with a ``type`` field
   (``damage`, ``heal``, ``death``, ``combatantinfo``, ``encounter`` ...).
2. Flat-column JSON logs (``logs.csv``-style) where each row is a dict of
   ``time,source,source_id,target,type,spell,amount`` style columns. Missing
   columns are tolerated via fuzzy key matching.
3. Row arrays (``[time, source, target, type, spell, amount]``).

Unknown event types are preserved as-is for stats to ignore safely, so
partial logs still produce useful reports.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Mapping, MutableMapping, Optional

from ..models import (
    Actor,
    DeathEvent,
    Encounter,
    FightSummary,
    HealEvent,
    Hit,
    LogEvent,
    Report,
)

log = logging.getLogger(__name__)

_AMOUNT_KEYS = ("amount", "total", "raw_amount")
_ENCOUNTER_KEYS = ("encounter", "encounter_name", "boss", "boss_name")
_FIGHT_ID_KEYS = ("fight", "fight_id", "fightid")
_TIME_KEYS = ("timestamp", "time", "t", "ts")
_TYPE_KEYS = ("type", "event_type", "event")
_SOURCE_KEYS = ("source", "source_name", "sourceID", "source_id", "actor", "player", "name")
_SOURCE_ID_KEYS = ("source_id", "sourceID", "sourceID", "player_id", "actor_id")
_TARGET_KEYS = ("target", "target_name", "targetID", "target_id")
_TARGET_ID_KEYS = ("target_id", "targetID", "targetID")
_SPELL_KEYS = ("spell", "spell_name", "ability", "ability_name", "name")
_SPELL_ID_KEYS = ("spell_id", "spellID", "abilityID", "ability_id")
_X_KEYS = ("x", "pos_x")
_Y_KEYS = ("y", "pos_y")

_FIGHT_ID_ALIASES = ("fight", "fight_id", "fightID", "fightid")
_ENCOUNTER_ALIASES = ("encounter", "encounter_name", "boss", "boss_name", "name")
_START_ALIASES = ("start_time", "start", "startTime", "begin")
_END_ALIASES = ("end_time", "end", "endTime", "finish")
_ZONE_ALIASES = ("zone", "zone_name", "zoneName", "instance")
_DIFFICULTY_ALIASES = ("difficulty", "diff", "mode")
_SIZE_ALIASES = ("size", "map_size", "players")
_KILL_ALIASES = ("kill", "is_kill", "result", "outcome", "success")

_ROW_TYPE_ALIASES = {
    "damage": "damage",
    "dmg": "damage",
    "hit": "damage",
    "heal": "healing",
    "healing": "healing",
    "heals": "healing",
    "hots": "healing",
    "death": "death",
    "deaths": "death",
    "kill": "death",
    "slain": "death",
    "cast": "cast",
    "caststart": "cast",
    "begincast": "cast",
    "applybuff": "buff",
    "applydebuff": "buff",
    "refreshbuff": "buff",
    "removebuff": "buff",
    "removedebuff": "buff",
    "applybuffstack": "buff",
    "combatantinfo": "combatantinfo",
    "combatant_info": "combatantinfo",
    "encounter": "encounter",
    "encounterstart": "encounter",
    "fight": "encounter",
    "encounterend": "encounter",
    "encounter_kill": "encounter",
    "buff": "buff",
    "aura": "buff",
}


def _first(d: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _norm_type(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    t = raw.strip().lower().replace(" ", "").replace("-", "")
    return _ROW_TYPE_ALIASES.get(t, t)


def _id_of(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _ms_of(v: Any) -> int:
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return 0
        try:
            return int(float(s))
        except ValueError:
            return 0
    return 0


def _lookup_alias(d: Mapping[str, Any], aliases: tuple[str, ...]) -> Any:
    for a in aliases:
        if a in d and d[a] is not None:
            return d[a]
        a2 = a.replace("_", "")
        if a2 in d and d[a2] is not None:
            return d[a2]
    return None


def parse_report(data: Any, source_name: str = "upload") -> Report:
    """Normalize arbitrary log-shaped JSON into a Report."""
    reports = _split_reports(data)
    if not reports:
        raise ValueError("No parseable log content found in input.")
    combined = _combine_reports(reports)
    combined.source_name = source_name
    return combined


def _split_reports(data: Any) -> list[Report]:
    if isinstance(data, list) and data and all(isinstance(x, dict) for x in data):
        # Ambiguous: a bare event list, or a list of report dicts.
        if all(("events" in x or "fights" in x or "report" in x or "log" in x) for x in data):
            out = []
            for x in data:
                out.extend(_split_reports(x))
            return out
        return [_parse_events_only(data)]
    if isinstance(data, Mapping):
        if "events" in data and isinstance(data["events"], (list, Mapping)):
            fights = data.get("fights")
            if isinstance(fights, list) and fights:
                out = []
                for f in fights:
                    if not isinstance(f, Mapping):
                        continue
                    payload = dict(data)
                    payload["events"] = data["events"]
                    out.append(_parse_events(payload, default_fight=f))
                return out
            return [_parse_events(data)]
        if "fights" in data and isinstance(data["fights"], list):
            return _parse_fights(data)
        if "log" in data and isinstance(data["log"], (list, str, Mapping)):
            return [_parse_events({"events": data["log"]})]
        if "report" in data and isinstance(data["report"], (Mapping, list)):
            return _split_reports(data["report"])
        if "players" in data or "actors" in data or "combatants" in data:
            players = data.get("players") or data.get("actors") or data.get("combatants")
            if isinstance(players, list) and data.get("fights") is None:
                return [_parse_standalone_players(data, players)]
        evs = _events_from_mapping(data)
        if evs:
            return [_parse_events_only(evs)]
        return []
    if isinstance(data, str):
        try:
            return _split_reports(json.loads(data))
        except json.JSONDecodeError:
            return _split_reports(_parse_lines(data))
    return []


def _events_from_mapping(d: Mapping[str, Any]) -> list[Any]:
    # A single dict that isn't report-shaped: maybe it's one event.
    if _lookup_alias(d, _TYPE_KEYS) is not None or _lookup_alias(d, _TIME_KEYS) is not None:
        return [d]
    return []


def _parse_lines(text: str) -> list[dict[str, Any]]:
    events = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Optional leading sequence number like "12/17 22:01:01.123  Foo, ..."
        line = re.sub(r"^\s*\d+\s*/\s*\d+\s+[\d:.\s]+", "", line)
        if line[0] in "[{":
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, Mapping):
                events.append(dict(obj))
            continue
        # CSV-ish: time,source,target,type,spell,amount
        if "," in line:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                row = {
                    "timestamp": parts[0],
                    "source": parts[1],
                    "target": parts[2],
                    "type": parts[3],
                }
                if len(parts) > 4:
                    row["spell"] = parts[4]
                if len(parts) > 5:
                    row["amount"] = parts[5]
                events.append(row)
            continue
        # space-separated: "time source target type spell amount"
        parts = line.split()
        if len(parts) >= 4:
            row = {
                "timestamp": parts[0],
                "source": parts[1],
                "target": parts[2],
                "type": parts[3],
            }
            if len(parts) > 4:
                row["spell"] = parts[4]
            if len(parts) > 5:
                row["amount"] = parts[5]
            events.append(row)
    return events


def _combine_reports(reports: list[Report]) -> Report:
    if len(reports) == 1:
        return reports[0]
    combined = Report(source_name=reports[0].source_name)
    fight_ids = set()
    for r in reports:
        for f in r.fights:
            if f.fight_id in fight_ids:
                continue
            fight_ids.add(f.fight_id)
            combined.fights.append(f)
        for a_id, a in r.actors.items():
            if a_id not in combined.actors:
                combined.actors[a_id] = a
        for ev in r.events:
            combined.events.append(ev)
    combined._recompute_fight_actors()
    return combined


def _parse_fights(data: Mapping[str, Any]) -> list[Report]:
    raw_fights = data.get("fights", [])
    raw_players = data.get("players") or data.get("actors") or data.get("combatants") or []
    reports = []
    for f in raw_fights:
        if not isinstance(f, Mapping):
            continue
        if "events" in f:
            reports.append(_parse_events(f, default_fight=f))
        else:
            reports.append(_parse_fight_only(f, raw_players))
    if not reports and raw_players:
        reports = [_parse_standalone_players(data, raw_players)]
    if not reports:
        reports = [_parse_events_only(_events_from_mapping(data))]
    return reports


def _parse_fight_only(f: Mapping[str, Any], raw_players: list[Any]) -> Report:
    rep = Report()
    enc = _encounter_from(f)
    fs = FightSummary(
        fight_id=_id_of(_lookup_alias(f, _FIGHT_ID_ALIASES)) or enc.fight_id,
        encounter=enc,
        start_time_ms=_ms_of(_lookup_alias(f, _START_ALIASES)),
        end_time_ms=_ms_of(_lookup_alias(f, _END_ALIASES)),
        zone=str(_lookup_alias(f, _ZONE_ALIASES) or ""),
        difficulty=str(_lookup_alias(f, _DIFFICULTY_ALIASES) or ""),
        size=_id_of(_lookup_alias(f, _SIZE_ALIASES)) or 20,
        kill=_kill_of(f),
        boss_pct=_first(f, "boss_pct", "boss_percentage", "bossPercent", default=0.0),
        report_title=str(_first(f, "title", "name", default="") or ""),
    )
    if fs.encounter.fight_id is None:
        fs.encounter.fight_id = fs.fight_id
    rep.fights.append(fs)
    _attach_players(rep, fs, raw_players)
    for p in raw_players:
        if not isinstance(p, Mapping):
            continue
        actor = _actor_from(p, fs)
        if actor.id is not None:
            rep.actors.setdefault(actor.id, actor)
    rep._recompute_fight_actors()
    return rep


def _kill_of(f: Mapping[str, Any]) -> Optional[bool]:
    v = _lookup_alias(f, _KILL_ALIASES)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("kill", "killed", "win", "won", "success", "true", "1"):
            return True
        if s in ("wipe", "loss", "fail", "false", "0"):
            return False
        m = re.match(r"kill(?:d)?(?:at)?\s*([\d.]+)%?", s)
        if m:
            return True
        m = re.match(r"wipe[d]?\s*(?:at)?\s*([\d.]+)%?", s)
        if m:
            return False
    return None


def _parse_events(data: Mapping[str, Any], default_fight: Optional[Mapping[str, Any]] = None) -> Report:
    rep = Report()
    events = data["events"]
    if isinstance(events, Mapping):
        events = _flatten_events_table(events)
    if default_fight is not None:
        fs = _fight_from_mapping(default_fight)
    else:
        enc_data = _lookup_alias(data, _ENCOUNTER_KEYS)
        fight_id = _id_of(_lookup_alias(data, _FIGHT_ID_KEYS))
        enc = _encounter_from(enc_data) if isinstance(enc_data, Mapping) else None
        if enc is None:
            enc = Encounter(name=str(enc_data or "Parsed Log Fight"), fight_id=fight_id)
        fs = FightSummary(
            fight_id=fight_id or enc.fight_id or 1,
            encounter=enc,
            start_time_ms=_ms_of(_lookup_alias(data, _START_ALIASES)),
            end_time_ms=_ms_of(_lookup_alias(data, _END_ALIASES)),
            zone=str(_lookup_alias(data, _ZONE_ALIASES) or ""),
            difficulty=str(_lookup_alias(data, _DIFFICULTY_ALIASES) or ""),
            size=_id_of(_lookup_alias(data, _SIZE_ALIASES)) or 20,
            kill=_kill_of(data),
            boss_pct=_first(data, "boss_pct", "boss_percentage", default=0.0),
            report_title=str(_first(data, "title", "name", default="") or ""),
        )
    rep.fights.append(fs)
    seen_actors: MutableMapping[tuple[int, str], Actor] = {}
    for raw in events:
        if isinstance(raw, Mapping):
            _add_event(rep, fs, dict(raw), seen_actors)
        elif isinstance(raw, list):
            row = _event_from_row(raw)
            if row is not None:
                _add_event(rep, fs, row, seen_actors)
        elif isinstance(raw, str):
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, Mapping):
                _add_event(rep, fs, dict(obj), seen_actors)
    if fs.end_time_ms <= fs.start_time_ms:
        last = max((e.time for e in rep.events), default=fs.start_time_ms)
        fs.end_time_ms = max(last, fs.start_time_ms + 1)
    rep.events = [e for e in rep.events if fs.start_time_ms <= e.time <= fs.end_time_ms]
    rep._recompute_fight_actors()
    return rep


def _event_from_row(raw: list[Any]) -> Optional[dict[str, Any]]:
    if not raw:
        return None
    if len(raw) < 4:
        return None
    return {
        "timestamp": raw[0],
        "source": raw[1] if len(raw) > 1 else None,
        "target": raw[2] if len(raw) > 2 else None,
        "type": raw[3],
        "spell": raw[4] if len(raw) > 4 else None,
        "amount": raw[5] if len(raw) > 5 else None,
    }


def _parse_events_only(events: list[Any]) -> Report:
    return _parse_events({"events": events})


def _flatten_events_table(events: Mapping[str, Any]) -> list[dict[str, Any]]:
    # WCL table API: {"data": [...], "total...": n}
    data = events.get("data")
    if isinstance(data, list):
        return [dict(x) if isinstance(x, Mapping) else x for x in data]
    return [dict(x) for x in events.values() if isinstance(x, Mapping)]


def _fight_from_mapping(f: Mapping[str, Any]) -> FightSummary:
    enc = _encounter_from(f)
    fs = FightSummary(
        fight_id=_id_of(_lookup_alias(f, _FIGHT_ID_ALIASES)) or 1,
        encounter=enc,
        start_time_ms=_ms_of(_lookup_alias(f, _START_ALIASES)),
        end_time_ms=_ms_of(_lookup_alias(f, _END_ALIASES)),
        zone=str(_lookup_alias(f, _ZONE_ALIASES) or ""),
        difficulty=str(_lookup_alias(f, _DIFFICULTY_ALIASES) or ""),
        size=_id_of(_lookup_alias(f, _SIZE_ALIASES)) or 20,
        kill=_kill_of(f),
        boss_pct=_first(f, "boss_pct", "boss_percentage", default=0.0),
        report_title=str(_first(f, "title", "name", default="") or ""),
    )
    if fs.encounter.fight_id is None:
        fs.encounter.fight_id = fs.fight_id
    return fs


def _parse_standalone_players(data: Mapping[str, Any], players: list[Any]) -> Report:
    rep = Report()
    enc_name = _lookup_alias(data, _ENCOUNTER_KEYS) or "Parsed Log Fight"
    fight_id = _id_of(_lookup_alias(data, _FIGHT_ID_KEYS)) or 1
    enc = _encounter_from(enc_name) if isinstance(enc_name, Mapping) else None
    if enc is None:
        enc = Encounter(name=str(enc_name), fight_id=fight_id)
    fs = FightSummary(
        fight_id=fight_id,
        encounter=enc,
        start_time_ms=_ms_of(_lookup_alias(data, _START_ALIASES)),
        end_time_ms=_ms_of(_lookup_alias(data, _END_ALIASES)),
        zone=str(_lookup_alias(data, _ZONE_ALIASES) or ""),
        difficulty=str(_lookup_alias(data, _DIFFICULTY_ALIASES) or ""),
        size=_id_of(_lookup_alias(data, _SIZE_ALIASES)) or len(players) or 20,
        kill=_kill_of(data),
        boss_pct=_first(data, "boss_pct", "boss_percentage", default=0.0),
        report_title=str(_first(data, "title", "name", default="") or ""),
    )
    rep.fights.append(fs)
    for p in players:
        if not isinstance(p, Mapping):
            continue
        actor = _actor_from(p, fs)
        if actor.id is not None:
            rep.actors.setdefault(actor.id, actor)
            fs.combatants.append(actor.id)
    if fs.end_time_ms <= fs.start_time_ms:
        fs.end_time_ms = fs.start_time_ms + 1
    rep._recompute_fight_actors()
    return rep


def _attach_players(rep: Report, fs: FightSummary, raw_players: list[Any]) -> None:
    for p in raw_players:
        if not isinstance(p, Mapping):
            continue
        actor = _actor_from(p, fs)
        if actor.id is not None:
            rep.actors.setdefault(actor.id, actor)


def _encounter_from(f: Mapping[str, Any]) -> Encounter:
    name = _lookup_alias(f, _ENCOUNTER_ALIASES)
    if not isinstance(name, str):
        name = "Unknown Encounter"
    eid = _id_of(_lookup_alias(f, ("encounter_id", "encounterID", "boss_id", "npc_id")))
    fid = _id_of(_lookup_alias(f, _FIGHT_ID_ALIASES))
    return Encounter(name=name, encounter_id=eid or None, fight_id=fid)


def _encounter_from_bare(name: Any) -> Encounter:
    if isinstance(name, str):
        return Encounter(name=name, fight_id=1)
    return Encounter(name="Unknown Encounter", fight_id=1)


def _actor_from(p: Mapping[str, Any], fs: FightSummary) -> Actor:
    name = str(_lookup_alias(p, ("name", "player", "source", "actor")) or "Unknown")
    aid = _id_of(_lookup_alias(p, ("id", "actor_id", "player_id", "guid", "source_id")))
    if aid is None:
        aid = abs(hash((name,))) % 10_000_000
    spec_raw = _lookup_alias(p, ("spec", "spec_name", "specialization", "specID"))
    spec = str(spec_raw) if spec_raw is not None else ""
    cls = str(_lookup_alias(p, ("class", "class_name", "type")) or "")
    role_raw = _lookup_alias(p, ("role", "assigned_role"))
    role = str(role_raw) if role_raw is not None else ""
    item_level_raw = _lookup_alias(p, ("item_level", "gear_level", "ilvl"))
    item_level = _id_of(item_level_raw) or 0
    return Actor(
        id=aid,
        name=name,
        type="player",
        spec=spec,
        class_name=cls,
        role=role,
        item_level=item_level,
        declared=True,
    )


def _add_event(
    rep: Report,
    fs: FightSummary,
    ev: dict[str, Any],
    seen_actors: MutableMapping[tuple[int, str], Actor],
) -> None:
    typ = _norm_type(_lookup_alias(ev, _TYPE_KEYS))
    if not typ and isinstance(_lookup_alias(ev, _TIME_KEYS), (int, float, str)):
        typ = _guess_type(ev)
    if not typ:
        return
    t = _ms_of(_lookup_alias(ev, _TIME_KEYS))
    src_name, src_id = _actor_id_and_name(ev, is_source=True)
    tgt_name, tgt_id = _actor_id_and_name(ev, is_source=False)
    spell = str(_lookup_alias(ev, _SPELL_KEYS) or "")
    spell_id = _id_of(_lookup_alias(ev, _SPELL_ID_KEYS))
    if not spell:
        spell = "Unknown Ability"
    if typ == "damage":
        amount = _num(_lookup_alias(ev, _AMOUNT_KEYS)) or 0
        unmitigated = _num(_first(ev, "unmitigated_amount", "raw_amount", default=0))
        hit = Hit(
            amount=amount,
            unmitigated=unmitigated or amount,
            mitigated=_num(_first(ev, "mitigated", default=0)),
            absorbed=_num(_first(ev, "absorbed", default=0)),
            crit=_truthy(_first(ev, "crit", "critical", default=False)),
            hit_type=str(_first(ev, "hit_type", "hitType", default="") or ""),
            overkill=_num(_first(ev, "overkill", default=0)),
        )
        actor = _ensure_actor(rep, fs, seen_actors, src_id, src_name, ev, is_source=True)
        target = _ensure_actor(rep, fs, seen_actors, tgt_id, tgt_name, ev, is_source=False) if tgt_id in rep.actors or (tgt_name and any(a.name == tgt_name for a in rep.actors.values())) else None
        e = LogEvent(
            type="damage",
            time=t,
            source_id=actor.id if actor else None,
            source_name=src_name or (actor.name if actor else None),
            target_id=target.id if target else None,
            target_name=tgt_name or (target.name if target else None),
            spell=spell,
            spell_id=spell_id,
            hit=hit,
            raw=ev,
        )
        rep.events.append(e)
        if src_name and actor is None:
            pass
        return
    if typ in ("healing", "heal"):
        amount = _num(_lookup_alias(ev, _AMOUNT_KEYS)) or 0
        overheal = _num(_first(ev, "overheal", "overheal_amount", default=0))
        actor = _ensure_actor(rep, fs, seen_actors, src_id, src_name, ev, is_source=True)
        target = _ensure_actor(rep, fs, seen_actors, tgt_id, tgt_name, ev, is_source=False)
        e = LogEvent(
            type="healing",
            time=t,
            source_id=actor.id if actor else None,
            source_name=src_name or (actor.name if actor else None),
            target_id=target.id if target else None,
            target_name=tgt_name or (target.name if target else None),
            spell=spell,
            spell_id=spell_id,
            heal=HealEvent(amount=amount, overheal=overheal),
            raw=ev,
        )
        rep.events.append(e)
        return
    if typ == "death":
        actor = _ensure_actor(rep, fs, seen_actors, tgt_id, tgt_name, ev, is_source=False)
        killer = _ensure_actor(rep, fs, seen_actors, src_id, src_name, ev, is_source=True) if src_id in rep.actors or (src_name and any(a.name == src_name for a in rep.actors.values())) else None
        e = LogEvent(
            type="death",
            time=t,
            source_id=killer.id if killer else None,
            source_name=src_name or (killer.name if killer else None),
            target_id=actor.id if actor else None,
            target_name=tgt_name or (actor.name if actor else None),
            spell=spell if spell and spell != "Unknown Ability" else "",
            spell_id=spell_id,
            death=DeathEvent(killer_id=killer.id if killer else None),
            raw=ev,
        )
        rep.events.append(e)
        return
    if typ == "cast":
        actor = _ensure_actor(rep, fs, seen_actors, src_id, src_name, ev, is_source=True)
        e = LogEvent(
            type="cast",
            time=t,
            source_id=actor.id if actor else None,
            source_name=src_name or (actor.name if actor else None),
            target_id=tgt_id,
            target_name=tgt_name,
            spell=spell,
            spell_id=spell_id,
            cast_success=True,
            raw=ev,
        )
        rep.events.append(e)
        return
    if typ == "buff":
        actor = _ensure_actor(rep, fs, seen_actors, src_id, src_name, ev, is_source=True)
        target = _ensure_actor(rep, fs, seen_actors, tgt_id, tgt_name, ev, is_source=False)
        e = LogEvent(
            type="buff",
            time=t,
            source_id=actor.id if actor else None,
            source_name=src_name or (actor.name if actor else None),
            target_id=target.id if target else None,
            target_name=tgt_name or (target.name if target else None),
            spell=spell,
            spell_id=spell_id,
            buff_uptime=_num(_first(ev, "duration", "uptime", default=0)),
            raw=ev,
        )
        rep.events.append(e)
        return
    if typ in ("encounter", "combatantinfo"):
        # These enrich fights/actors; ignore as generic events.
        if typ == "encounter":
            name = str(_lookup_alias(ev, _ENCOUNTER_KEYS) or "")
            ev_fight_id = _id_of(_lookup_alias(ev, _FIGHT_ID_ALIASES))
            if name and (fs.encounter.name in ("", "Parsed Log Fight", "Unknown Encounter") or ev_fight_id == fs.fight_id):
                fs.encounter.name = name
        if typ == "combatantinfo":
            aid = _id_of(_lookup_alias(ev, ("source_id", "sourceID", "player_id")))
            if aid is not None:
                actor = _actor_from(ev, fs)
                actor.id = aid
                actor.declared = True
                rep.actors.setdefault(aid, actor)
                if aid not in fs.combatants:
                    fs.combatants.append(aid)
        return
    # Unknown type: keep as generic event for transparency
    actor = _ensure_actor(rep, fs, seen_actors, src_id, src_name, ev, is_source=True)
    e = LogEvent(
        type=typ,
        time=t,
        source_id=actor.id if actor else src_id,
        source_name=src_name or (actor.name if actor else None),
        target_id=tgt_id,
        target_name=tgt_name,
        spell=spell,
        spell_id=spell_id,
        raw=ev,
    )
    rep.events.append(e)


def _guess_type(ev: dict[str, Any]) -> str:
    if _lookup_alias(ev, _AMOUNT_KEYS) is None:
        return ""
    if isinstance(_lookup_alias(ev, ("heal", "healing", "amount_healed")), (int, float)):
        return "healing"
    return "damage"


def _actor_id_and_name(ev: dict[str, Any], is_source: bool) -> tuple[Optional[str], Optional[int]]:
    if is_source:
        name = _lookup_alias(ev, _SOURCE_KEYS)
        aid = _id_of(_lookup_alias(ev, _SOURCE_ID_KEYS))
    else:
        name = _lookup_alias(ev, _TARGET_KEYS)
        aid = _id_of(_lookup_alias(ev, _TARGET_ID_KEYS))
    if isinstance(name, (int, float)) and aid is None:
        aid = _id_of(name)
        name = None
    if name is not None and not isinstance(name, str):
        name = str(name)
    return name, aid


def _ensure_actor(
    rep: Report,
    fs: FightSummary,
    seen: MutableMapping[tuple[int, str], Actor],
    aid: Optional[int],
    name: Optional[str],
    ev: dict[str, Any],
    is_source: bool,
) -> Optional[Actor]:
    if aid is None and not name:
        return None
    if aid is not None and aid in rep.actors:
        a = rep.actors[aid]
        if name and a.name == "Unknown":
            a.name = name
        return a
    key = (aid if aid is not None else -1, name or "")
    if key in seen:
        return seen[key]
    actor = Actor(id=aid if aid is not None else abs(hash((name or "unknown",))) % 10_000_000, name=name or "Unknown", type="player")
    rep.actors[actor.id] = actor
    seen[key] = actor
    fs.combatants.append(actor.id)
    return actor


def _num(v: Any) -> int:
    if v is None:
        return 0
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if not s:
            return 0
        try:
            return int(float(s))
        except ValueError:
            return 0
    return 0


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "crit")
    return False
