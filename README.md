# Raid Analyst

A WarcraftLogs-style raid analysis tool with an LLM analyst on top. Upload a combat log, browse fights and per-player stats, then ask an AI analyst "what can this player / this raid do better?"

## Features

- **Log ingest** — tolerant parser for WCL events-style JSON, flat-column logs, and CSV/line-based logs (see `backend/app/ingest/normalize.py`)
- **Stats engine** — per-fight and per-player damage/healing, DPS/HPS, deaths with timestamps, crit rate, activity %, ability breakdown, damage-by-target, and 10s-bucket timelines
- **LLM analyst** — provider-agnostic adapter (Mistral, Anthropic, OpenAI, or any OpenAI-compatible endpoint; offline mock by default) powering raid coaching reports, per-player coaching reports, and free-form Q&A chat with conversation history
- **Web UI** — upload logs, browse fights, inspect the player table, click a player to focus the analysis, and chat with the analyst
- **Sample data** — a 3-boss, 16-player Mythic-style sample raid night is included

## Project layout

```
backend/    FastAPI app (ingest, stats, LLM analysis, API)
frontend/   Vite + React UI
samples/    Sample raid log + generator script
docs/       Additional documentation
```

## Quickstart

### Docker (single container, UI + API)

```bash
docker compose up --build
# or: docker build -t raid-analyst . && docker run -p 8000:8000 raid-analyst
```

Open http://localhost:8000 — the React UI, API, and sample data are all served from one container. LLM provider env vars pass through from your shell (defaults to the offline mock if unset).

The image is a two-stage build: Node 22 builds the React app, and FastAPI serves the resulting `dist/` statically — no separate frontend process.

### Local development

#### 1. Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

#### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and click **Load sample raid** to explore immediately.

### 3. Configure an LLM (optional)

By default the app runs with a deterministic offline **mock** analyst so everything works without keys. To use a real LLM, set environment variables before starting the backend:

```bash
# Mistral (default model: mistral-large-latest)
LLM_PROVIDER=mistral
MISTRAL_API_KEY=...          # or LLM_API_KEY

# Anthropic
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=...

# OpenAI / any OpenAI-compatible endpoint
LLM_PROVIDER=openai          # or openai_compatible
OPENAI_API_KEY=...
LLM_BASE_URL=https://your-endpoint/v1   # optional, openai_compatible

# Optional overrides
LLM_MODEL=your-model-name
```

The matching provider SDK (`mistralai`, `anthropic`, or `openai`) must be installed, e.g. `uv pip install mistralai`.

> For development, either add the SDK to `backend/pyproject.toml` dependencies or install it ad hoc. Keep real API keys out of any committed files.

## API overview

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/reports` | Upload a log file (multipart) |
| `GET` | `/api/reports` | List uploaded reports |
| `GET` | `/api/reports/{id}` | Report metadata + fights |
| `DELETE` | `/api/reports/{id}` | Delete a report |
| `GET` | `/api/reports/{id}/fights` | List fights |
| `GET` | `/api/reports/{id}/fights/{fid}/stats` | Full fight stats (players, timelines, deaths) |
| `POST` | `/api/reports/{id}/analysis/report` | Raid coaching report (`{"fight_id": 1}`) |
| `POST` | `/api/reports/{id}/analysis/player-report` | Player coaching report (`{"fight_id": 1, "focus_player": "Name"}`) |
| `POST` | `/api/reports/{id}/analysis/chat` | Ask the analyst (supports `history`) |
| `GET` | `/api/health` | Health + LLM provider status |

## Log format

The parser is liberal, but the richest supported shape is:

```json
{
  "fights": [
    {"fight": 1, "encounter": "Boss Name", "start_time": 0, "end_time": 312000, "kill": false, "boss_pct": 62.0}
  ],
  "events": [
    {"timestamp": 100, "type": "damage", "source_id": 100, "source": "Thalyra", "target_id": 999001, "target": "Boss", "spell": "Pyroblast", "amount": 154000, "crit": true},
    {"timestamp": 150, "type": "heal", "source_id": 112, "source": "Lightweaver", "target_id": 100, "target": "Thalyra", "spell": "Flash Heal", "amount": 84000, "overheal": 12000},
    {"timestamp": 900, "type": "death", "source_id": 999001, "source": "Boss", "target_id": 107, "target": "Frostbane"},
    {"timestamp": 0, "type": "combatantinfo", "source_id": 100, "name": "Thalyra", "class": "Mage", "spec": "Fire", "role": "dps", "item_level": 486}
  ]
}
```

Combatantinfo events (or a `players` list) make player recognition reliable; without them, the engine uses heuristics (players heal and cast; bosses don't) to classify actors.

Regenerate the sample with `python samples/generate_sample.py`.

## Tests

```bash
cd backend
uv run pytest
```

Covers ingest normalization, stats computation, LLM provider config, and all API endpoints (26 tests).

## Extending

- **WarcraftLogs API ingest**: add a fetcher in `backend/app/ingest/` that pulls WCL events-v2 pages and feeds them to `parse_report`; the normalized model already matches WCL event shapes.
- **New metrics**: add fields in `backend/app/services/stats.py`; they flow automatically into prompts and the API.
- **New LLM provider**: implement the `LLMProvider` protocol in `backend/app/services/llm.py` and register it in `get_provider()`.
