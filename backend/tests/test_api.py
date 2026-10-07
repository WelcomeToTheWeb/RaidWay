import io
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app

SAMPLE = {
    "title": "Test Report",
    "fights": [{"fight": 1, "encounter": "Test Boss", "start_time": 0, "end_time": 10000, "kill": False}],
    "events": [
        {"timestamp": 100, "type": "damage", "source_id": 1, "source": "DPS1", "target_id": 2, "target": "Boss", "spell": "Hit", "amount": 1000},
        {"timestamp": 200, "type": "damage", "source_id": 1, "source": "DPS1", "target_id": 2, "target": "Boss", "spell": "Hit", "amount": 2000, "crit": True},
        {"timestamp": 300, "type": "heal", "source_id": 3, "source": "HEAL", "target_id": 1, "target": "DPS1", "spell": "Heal", "amount": 500},
        {"timestamp": 400, "type": "death", "source_id": 2, "source": "Boss", "target_id": 1, "target": "DPS1"},
    ],
}


@pytest.fixture
def client():
    return TestClient(app)


def _upload(client):
    buf = io.BytesIO(json.dumps(SAMPLE).encode())
    buf.seek(0)
    r = client.post("/api/reports", files={"file": ("sample.json", buf, "application/json")})
    assert r.status_code == 200, r.text
    return r.json()["report_id"]


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_upload_and_list(client):
    rid = _upload(client)
    r = client.get("/api/reports")
    assert r.status_code == 200
    assert any(x["report_id"] == rid for x in r.json())


def test_get_report_and_fights(client):
    rid = _upload(client)
    r = client.get(f"/api/reports/{rid}")
    assert r.status_code == 200
    assert r.json()["fights"][0]["name"] == "Test Boss"
    r2 = client.get(f"/api/reports/{rid}/fights")
    assert r2.status_code == 200
    assert r2.json()[0]["outcome"] == "Wipe"


def test_fight_stats_endpoint(client):
    rid = _upload(client)
    r = client.get(f"/api/reports/{rid}/fights/1/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total_damage"] == 3000
    assert body["total_healing"] == 500
    assert body["total_deaths"] == 1
    names = {p["name"] for p in body["players"]}
    assert names == {"DPS1", "HEAL"}


def test_analysis_report_endpoint(client):
    rid = _upload(client)
    r = client.post(f"/api/reports/{rid}/analysis/report", json={"fight_id": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fight_id"] == 1
    assert "llm_raw" in body
    assert len(body["llm_raw"]) > 20


def test_player_report_endpoint(client):
    rid = _upload(client)
    r = client.post(f"/api/reports/{rid}/analysis/player-report", json={"fight_id": 1, "focus_player": "DPS1"})
    assert r.status_code == 200, r.text
    assert "DPS1" in r.json()["llm_raw"] or r.json()["llm_raw"]


def test_chat_endpoint(client):
    rid = _upload(client)
    r = client.post(
        f"/api/reports/{rid}/analysis/chat",
        json={"fight_id": 1, "question": "What can the raid do better?", "history": []},
    )
    assert r.status_code == 200, r.text
    assert r.json()["answer"]


def test_chat_with_history(client):
    rid = _upload(client)
    r = client.post(
        f"/api/reports/{rid}/analysis/chat",
        json={
            "fight_id": 1,
            "question": "Follow-up?",
            "history": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        },
    )
    assert r.status_code == 200


def test_404s(client):
    r = client.get("/api/reports/does-not-exist")
    assert r.status_code == 404
    rid = _upload(client)
    r = client.get(f"/api/reports/{rid}/fights/999/stats")
    assert r.status_code == 404


def test_delete(client):
    rid = _upload(client)
    r = client.delete(f"/api/reports/{rid}")
    assert r.status_code == 200
    r = client.get(f"/api/reports/{rid}")
    assert r.status_code == 404
