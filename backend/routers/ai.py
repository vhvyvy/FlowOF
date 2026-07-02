import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_tenant
from models import Tenant

logger = logging.getLogger("flowof.ai")
router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


class AnalyzeRequest(BaseModel):
    question: str
    month: int
    year: int


class ProposedEvent(BaseModel):
    title:                str
    description:          str | None = None
    entity_type:          str | None = None
    entity_ref:           str | None = None
    trigger_metric:       str | None = None
    trigger_value_before: float | None = None
    suggested_review_days: int | None = None
    priority:             str = "normal"


class AnalyzeResponse(BaseModel):
    answer:          str
    proposed_events: list[ProposedEvent] = []


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    body: AnalyzeRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Agentic AI analyst: Claude calls read tools, investigates data, answers in Russian.

    tenant.id is always injected from JWT — the model never receives or requests it.
    month/year from the request are passed as a context hint so the model knows the
    currently selected period, but it is free to query other periods via tools.
    """
    try:
        from services.llm_analyst import LLMAnalyst

        context_hint = (
            f"Владелец сейчас смотрит на период {body.month:02d}/{body.year}. "
            "При ответе на вопросы без явного периода используй этот месяц как дефолтный."
        )
        analyst = LLMAnalyst()
        result  = await analyst.answer_question_agentic(
            db=db,
            tenant_id=tenant.id,
            question=body.question,
            context_hint=context_hint,
        )
        # Coerce proposed_events — tolerate extra fields from LLM
        proposed = []
        for ev in result.get("proposed_events") or []:
            try:
                proposed.append(ProposedEvent(**{
                    k: v for k, v in ev.items()
                    if k in ProposedEvent.model_fields
                }))
            except Exception:
                pass
        return AnalyzeResponse(answer=result.get("answer", ""), proposed_events=proposed)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("ai analyze error tenant=%d: %s", tenant.id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка AI: {str(e)}")
