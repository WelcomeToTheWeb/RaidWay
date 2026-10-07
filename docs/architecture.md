# Architecture

```
upload ──▶ FastAPI /api/reports ──▶ ingest/normalize.py ──▶ Report model
                                                             │
                                            services/stats.py│ (per fight)
                                                             ▼
                                            FightStats + PlayerStats
                                                             │
                             analysis/service.py (prompt builder)│
                                                             ▼
                             services/llm.py (provider adapter) ──▶ Mistral/Anthropic/OpenAI/Mock
                                                             │
                     ┌───────────────────────────────────────┘
                     ▼
        /analysis/report  /analysis/player-report  /analysis/chat
                     ▲
React UI (upload, fight browser, player table, coach panel, chat)
```

## Layers

- **Ingest** (`backend/app/ingest/`): tolerant normalization of many log shapes into `Report` (fights, actors, flat events). Unknown event types are preserved and ignored downstream.
- **Stats** (`backend/app/services/stats.py`): single source of truth for derived numbers. Player classification heuristic: declared actors (combatantinfo/players list) are players; undeclared ones are players only if they heal or cast.
- **Analysis** (`backend/app/analysis/`): serializes stats into a compact JSON context, builds the system/user prompt, and wraps provider responses into `CoachingReport` / `ChatAnswer`.
- **LLM** (`backend/app/services/llm.py`): `LLMProvider` protocol with Mistral, Anthropic, OpenAI(-compatible), and offline Mock implementations selected via env vars.
- **API** (`backend/app/routers/`): reports, fights/stats, analysis endpoints.
- **UI** (`frontend/src/`): React SPA talking to the API via Vite dev proxy.

## Key decisions

- Stats are computed server-side and handed to the LLM as pre-computed JSON rather than raw events, keeping prompts small and grounded.
- The LLM layer is provider-agnostic; the app is fully functional offline via the deterministic mock provider (used in tests and demos).
- Ingest deliberately accepts lossy input (missing ids, unknown types, text logs) so real-world exports work on a best-effort basis.
