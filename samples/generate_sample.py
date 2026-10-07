#!/usr/bin/env python3
"""Generate a realistic sample raid log (WCL events-style) for demo and tests.

Usage: python samples/generate_sample.py [output.json]
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

random.seed(42)

PLAYERS = [
    # name, class, spec, role, ilvl, skill (0-1), activity
    ("Thalyra", "Mage", "Fire", "dps", 486, 0.95, 0.93),
    ("Grimshot", "Hunter", "Beast Mastery", "dps", 483, 0.88, 0.9),
    ("Utheric", "Paladin", "Retribution", "dps", 480, 0.7, 0.78),
    ("Vexis", "Rogue", "Assassination", "dps", 481, 0.62, 0.65),
    ("Moonpetal", "Druid", "Balance", "dps", 485, 0.85, 0.88),
    ("Kaelbrand", "Warrior", "Arms", "dps", 479, 0.75, 0.82),
    ("Emberlyn", "Evoker", "Devastation", "dps", 484, 0.8, 0.85),
    ("Frostbane", "Death Knight", "Frost", "dps", 478, 0.58, 0.6),
    ("Stormcaller", "Shaman", "Elemental", "dps", 482, 0.83, 0.86),
    ("Shadowveil", "Priest", "Shadow", "dps", 480, 0.77, 0.8),
    ("Ironclad", "Warrior", "Protection", "tank", 487, 0.9, 0.98),
    ("Stoneheart", "Paladin", "Protection", "tank", 485, 0.86, 0.97),
    ("Lightweaver", "Priest", "Holy", "healer", 484, 0.9, 0.95),
    ("Rivermist", "Shaman", "Restoration", "healer", 482, 0.85, 0.92),
    ("Verdantleaf", "Druid", "Restoration", "healer", 483, 0.7, 0.88),
    ("Chiwind", "Monk", "Mistweaver", "healer", 481, 0.65, 0.85),
]

DPS_ROTATIONS = {
    "Mage": ["Pyroblast", "Fireball", "Fire Blast", "Phoenix Flames", "Scorch"],
    "Hunter": ["Kill Command", "Barbed Shot", "Cobra Shot", "Kill Shot", "Multi-Shot"],
    "Paladin": ["Templar's Verdict", "Wake of Ashes", "Blade of Justice", "Judgment"],
    "Rogue": ["Mutilate", "Envenom", "Rupture", "Garrote", "Vanishing Powder"],
    "Druid": ["Starsurge", "Starfall", "Wrath", "Sunfire", "Moonfire"],
    "Warrior": ["Mortal Strike", "Execute", "Slam", "Whirlwind", "Colossus Smash"],
    "Evoker": ["Disintegrate", "Fire Breath", "Eternity Surge", "Living Flame", "Pyre"],
    "Death Knight": ["Frost Strike", "Obliterate", "Howling Blast", "Frostscythe"],
    "Shaman": ["Lava Burst", "Lightning Bolt", "Chain Lightning", "Elemental Blast"],
    "Priest": ["Mind Blast", "Void Bolt", "Shadow Word: Death", "Mind Flay"],
}
TANK_ROTATIONS = {"Warrior": ["Shield Slam", "Revenge", "Thunder Clap", "Devastate"], "Paladin": ["Shield of the Righteous", "Judgment", "Avenger's Shield", "Consecration"]}
HEALER_SPELLS = {
    "Priest": ["Holy Word: Serenity", "Flash Heal", "Renew", "Prayer of Healing", "Heal"],
    "Shaman": ["Healing Wave", "Riptide", "Chain Heal", "Healing Rain"],
    "Druid": ["Regrowth", "Rejuvenation", "Wild Growth", "Efflorescence"],
    "Monk": ["Vivify", "Renewing Mist", "Enveloping Mist", "Restoral"],
}
BOSS_ABILITIES = ["Fell Arcane Burst", "Shadowflame Cleave", "Ruin Brand", "Raid Wide Decay", "Fel Torment"]


def gen_fight(fight_id, boss_name, duration_s, kill, boss_pct, start_ms, difficulty="Mythic", zone="Amirdrassil, the Dream's Hope"):
    events = []
    boss_id = 999000 + fight_id
    end_ms = start_ms + duration_s * 1000
    events.append({"timestamp": start_ms, "type": "encounter", "encounter": boss_name, "fight": fight_id})
    for p in PLAYERS:
        pid = 100 + PLAYERS.index(p)
        events.append({"timestamp": start_ms, "type": "combatantinfo", "source_id": pid, "name": p[0], "class": p[1], "spec": p[2], "role": p[3], "item_level": p[4]})
    skill = {p[0]: p[5] for p in PLAYERS}
    activity = {p[0]: p[6] for p in PLAYERS}
    deaths = {}
    if not kill:
        doomed = random.sample([p[0] for p in PLAYERS if p[3] != "tank"], random.randint(2, 5))
        for name in doomed:
            deaths[name] = random.uniform(0.35, 0.95) * duration_s
    death_times = {}
    for name, t in deaths.items():
        death_times[name] = t
    n_ticks = int(duration_s * 2.5)
    for i in range(n_ticks):
        t = start_ms + int((i / n_ticks) * duration_s * 1000)
        frac = (t - start_ms) / (duration_s * 1000)
        for p in PLAYERS:
            name, cls, spec, role, ilvl, sk, act = p
            pid = 100 + PLAYERS.index(p)
            if name in death_times and frac > death_times[name] / duration_s:
                continue
            if random.random() > act * 0.9:
                continue
            if role == "dps":
                spells = DPS_ROTATIONS[cls]
                base = 150000 * sk * (1 + ilvl / 500)
                amt = int(base * random.uniform(0.4, 1.6))
                events.append({
                    "timestamp": t, "type": "damage", "source_id": pid, "source": name,
                    "target_id": boss_id, "target": boss_name,
                    "spell": random.choice(spells), "spell_id": 100000 + len(spells),
                    "amount": amt, "crit": random.random() < 0.3 + sk * 0.1,
                })
            elif role == "tank":
                spells = TANK_ROTATIONS[cls]
                amt = int(90000 * sk * random.uniform(0.5, 1.3))
                events.append({
                    "timestamp": t, "type": "damage", "source_id": pid, "source": name,
                    "target_id": boss_id, "target": boss_name,
                    "spell": random.choice(spells), "amount": amt, "crit": random.random() < 0.2,
                })
            elif role == "healer":
                spells = HEALER_SPELLS[cls]
                targets = [q[0] for q in PLAYERS if q[3] != "healer" and (q[0] not in death_times or frac < death_times[q[0]] / duration_s)]
                tgt = random.choice(targets) if targets else name
                tid = 100 + PLAYERS.index([q for q in PLAYERS if q[0] == tgt][0])
                base = 70000 * sk
                amt = int(base * random.uniform(0.4, 1.4))
                oh = int(amt * random.uniform(0.0, 0.35 if sk < 0.8 else 0.1))
                events.append({
                    "timestamp": t, "type": "heal", "source_id": pid, "source": name,
                    "target_id": tid, "target": tgt, "spell": random.choice(spells),
                    "amount": amt, "overheal": oh,
                })
        # boss damage to raid
        if random.random() < 0.3:
            victims = [q for q in PLAYERS if q[0] not in death_times or frac < death_times[q[0]] / duration_s]
            if victims:
                v = random.choice(victims)
                vid = 100 + PLAYERS.index(v)
                dmg_taken = int(220000 * random.uniform(0.3, 1.2) * (1.4 if v[3] == "tank" else 1.0))
                events.append({
                    "timestamp": t, "type": "damage", "source_id": boss_id, "source": boss_name,
                    "target_id": vid, "target": v[0], "spell": random.choice(BOSS_ABILITIES),
                    "amount": dmg_taken, "crit": False,
                })
    for name, t in death_times.items():
        pid = 100 + PLAYERS.index([q for q in PLAYERS if q[0] == name][0])
        events.append({
            "timestamp": start_ms + int(t * 1000), "type": "death",
            "source_id": boss_id, "source": boss_name, "target_id": pid, "target": name,
        })
    events.sort(key=lambda e: e["timestamp"])
    return {
        "title": f"Sample Report - {zone}",
        "zone": zone,
        "difficulty": difficulty,
        "fights": [{
            "fight": fight_id,
            "encounter": boss_name,
            "start_time": start_ms,
            "end_time": end_ms,
            "kill": kill,
            "boss_pct": boss_pct,
            "size": 16,
        }],
        "events": events,
    }


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "sample_raid_log.json")
    fights = [
        gen_fight(1, "Gnarlroot", 312, False, 62.0, 0),
        gen_fight(2, "Igira the Cruel", 348, True, 0.0, 400000),
        gen_fight(3, "Volcoross", 289, False, 8.0, 900000),
    ]
    combined = {
        "title": "Sample Mythic Raid Night",
        "zone": "Amirdrassil, the Dream's Hope",
        "fights": [],
        "events": [],
    }
    for f in fights:
        combined["fights"].extend(f["fights"])
        combined["events"].extend(f["events"])
    combined["events"].sort(key=lambda e: e["timestamp"])
    out.write_text(json.dumps(combined, indent=1))
    print(f"Wrote {out} ({out.stat().st_size // 1024} KiB, {len(combined['events'])} events, {len(combined['fights'])} fights)")


if __name__ == "__main__":
    main()
