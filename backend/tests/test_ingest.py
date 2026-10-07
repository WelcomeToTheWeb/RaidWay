import json

import pytest

from app.ingest import parse_report
from app.models import Report


def test_parses_wcl_style_events():
    data = {
        "title": "T",
        "fights": [{"fight": 1, "encounter": "Test Boss", "start_time": 0, "end_time": 10000, "kill": True}],
        "events": [
            {"timestamp": 100, "type": "damage", "source_id": 1, "source": "A", "target_id": 2, "target": "Boss", "spell": "Hit", "amount": 500},
            {"timestamp": 200, "type": "heal", "source_id": 3, "source": "H", "target_id": 1, "target": "A", "spell": "Heal", "amount": 200, "overheal": 50},
            {"timestamp": 300, "type": "death", "source_id": 2, "source": "Boss", "target_id": 1, "target": "A"},
        ],
    }
    rep = parse_report(data)
    assert isinstance(rep, Report)
    assert len(rep.fights) == 1
    assert rep.fights[0].name == "Test Boss"
    assert rep.fights[0].kill is True
    assert len(rep.events) == 3
    types = {e.type for e in rep.events}
    assert types == {"damage", "healing", "death"}
    assert rep.actors[1].name == "A"


def test_parses_flat_column_rows():
    rows = [
        {"time": 0, "source": "A", "target": "Boss", "type": "damage", "spell": "Hit", "amount": "100"},
        {"time": 500, "source": "H", "target": "A", "type": "heal", "spell": "Heal", "amount": "50"},
    ]
    rep = parse_report(rows)
    assert len(rep.events) == 2
    assert rep.events[0].hit.amount == 100
    assert rep.events[1].heal.amount == 50


def test_parses_csv_text():
    text = "0,A,Boss,damage,Hit,250\n500,H,A,heal,Heal,80\n"
    rep = parse_report(text)
    assert len(rep.events) == 2


def test_tolerates_unknown_types():
    data = {"events": [{"timestamp": 0, "type": "summon", "source": "A", "target": "Boss", "spell": "Pet"}]}
    rep = parse_report(data)
    assert len(rep.events) == 1
    assert rep.events[0].type == "summon"


def test_rejects_garbage():
    with pytest.raises(ValueError):
        parse_report({"nothing": "here"})


def test_multi_fight_report_split():
    data = {
        "fights": [
            {"fight": 1, "encounter": "B1", "start_time": 0, "end_time": 1000, "kill": False},
            {"fight": 2, "encounter": "B2", "start_time": 2000, "end_time": 3000, "kill": True},
        ]
    }
    rep = parse_report(data)
    assert len(rep.fights) == 2
    assert [f.name for f in rep.fights] == ["B1", "B2"]
