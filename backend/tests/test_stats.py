from app.ingest import parse_report
from app.services.stats import compute_fight_stats, player_summary_dicts


def _report():
    data = {
        "fights": [{"fight": 1, "encounter": "Test Boss", "start_time": 0, "end_time": 10000, "kill": False}],
        "events": [
            {"timestamp": 100, "type": "damage", "source_id": 1, "source": "DPS1", "target_id": 2, "target": "Boss", "spell": "Hit", "amount": 1000},
            {"timestamp": 200, "type": "damage", "source_id": 1, "source": "DPS1", "target_id": 2, "target": "Boss", "spell": "Hit", "amount": 2000, "crit": True},
            {"timestamp": 300, "type": "heal", "source_id": 3, "source": "HEAL", "target_id": 1, "target": "DPS1", "spell": "Heal", "amount": 500, "overheal": 100},
            {"timestamp": 400, "type": "damage", "source_id": 2, "source": "Boss", "target_id": 1, "target": "DPS1", "spell": "Smash", "amount": 3000},
            {"timestamp": 500, "type": "death", "source_id": 2, "source": "Boss", "target_id": 1, "target": "DPS1"},
            {"timestamp": 600, "type": "cast", "source_id": 3, "source": "HEAL", "spell": "Revive"},
        ],
    }
    return parse_report(data)


def test_fight_stats_totals():
    rep = _report()
    fs = compute_fight_stats(rep, rep.fights[0])
    assert fs.fight_id == 1
    assert fs.encounter_name == "Test Boss"
    assert fs.outcome == "Wipe"
    assert fs.total_damage == 3000
    assert fs.total_healing == 500
    assert fs.total_deaths == 1
    assert fs.duration_seconds == 10.0


def test_player_stats():
    rep = _report()
    fs = compute_fight_stats(rep, rep.fights[0])
    dps1 = fs.player("DPS1")
    assert dps1 is not None
    assert dps1.damage_done == 3000
    assert dps1.damage_taken == 3000
    assert dps1.deaths == 1
    assert dps1.crits == 1
    assert dps1.damage_events == 2
    assert dps1.crit_rate == 0.5
    heal = fs.player("HEAL")
    assert heal.healing_done == 500
    assert heal.overhealing_done == 100
    assert heal.healing_taken == 0
    assert heal.casts == 1


def test_ability_breakdown_and_targets():
    rep = _report()
    fs = compute_fight_stats(rep, rep.fights[0])
    dps1 = fs.player("DPS1")
    assert dps1.ability_breakdown.get("Hit") == 3000
    assert dps1.damage_on_targets.get("Boss") == 3000


def test_player_summary_dicts():
    rep = _report()
    fs = compute_fight_stats(rep, rep.fights[0])
    rows = player_summary_dicts(fs)
    by_name = {r["name"]: r for r in rows}
    assert by_name["DPS1"]["dps"] == 300.0
    assert by_name["DPS1"]["deaths"] == 1
    assert by_name["HEAL"]["hps"] == 50.0
