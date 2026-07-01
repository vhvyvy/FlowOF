import logging

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


class AnalyzeResponse(BaseModel):
    answer: str


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    body: AnalyzeRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    try:
        from services.analytics_context import build_agency_snapshot, snapshot_to_text
        from services.llm_analyst import LLMAnalyst

        snapshot      = await build_agency_snapshot(db, tenant.id, body.year, body.month)
        snapshot_text = snapshot_to_text(snapshot)
        analyst       = LLMAnalyst()
        answer        = await analyst.answer_question(snapshot_text, body.question)
        return AnalyzeResponse(answer=answer)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("ai analyze error tenant=%d: %s", tenant.id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка AI: {str(e)}")
