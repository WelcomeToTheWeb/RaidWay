from fastapi import APIRouter, HTTPException
from typing import Optional

from pydantic import BaseModel, Field

from ..analysis import service as analysis
from ..services import llm as llm_mod
from ..services.store import store

router = APIRouter(prefix="/api/reports/{report_id}/analysis", tags=["analysis"])


class AnalyzeRequest(BaseModel):
    fight_id: Optional[int] = None
    question: Optional[str] = None
    focus_player: Optional[str] = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    fight_id: Optional[int] = None
    question: str
    focus_player: Optional[str] = None
    history: list[ChatMessage] = Field(default_factory=list)


@router.get("/status")
async def analysis_status():
    return llm_mod.provider_status()


@router.post("/report")
async def generate_report(report_id: str, req: AnalyzeRequest):
    if store.get(report_id) is None:
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        report = analysis.generate_report(store, report_id, req.fight_id)
    except KeyError as ex:
        raise HTTPException(status_code=404, detail=str(ex).strip("'"))
    except llm_mod.LLMError as ex:
        raise HTTPException(status_code=503, detail=str(ex))
    return report.model_dump()


@router.post("/player-report")
async def generate_player_report(report_id: str, req: AnalyzeRequest):
    if not req.focus_player:
        raise HTTPException(status_code=422, detail="focus_player is required")
    if store.get(report_id) is None:
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        report = analysis.generate_player_report(store, report_id, req.fight_id, req.focus_player)
    except KeyError as ex:
        raise HTTPException(status_code=404, detail=str(ex).strip("'"))
    except llm_mod.LLMError as ex:
        raise HTTPException(status_code=503, detail=str(ex))
    return report.model_dump()


@router.post("/chat")
async def chat(report_id: str, req: ChatRequest):
    if store.get(report_id) is None:
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        answer = analysis.chat_about_fight(
            store,
            report_id,
            req.fight_id,
            req.question,
            focus_player=req.focus_player,
            history=[m.model_dump() for m in req.history],
        )
    except KeyError as ex:
        raise HTTPException(status_code=404, detail=str(ex).strip("'"))
    except llm_mod.LLMError as ex:
        raise HTTPException(status_code=503, detail=str(ex))
    return answer.model_dump()
