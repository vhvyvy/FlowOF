import logging
import os
from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from database import get_db
from dependencies import get_current_tenant
from models import Tenant, Transaction, Expense

logger = logging.getLogger("skynet.ai")
router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


class AnalyzeRequest(BaseModel):
    question: str
    month: int
    year: int


class AnalyzeResponse(BaseModel):
    answer: str


def _month_range(year: int, month: int):
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    body: AnalyzeRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    openai_key = tenant.openai_key or os.getenv("OPENAI_API_KEY", "")
    if not openai_key:
        raise HTTPException(status_code=400, detail="OpenAI API key not configured")

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=openai_key)

        # Build context from DB
        start, end = _month_range(body.year, body.month)

        rev_result = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                and_(
                    Transaction.tenant_id == tenant.id,
                    Transaction.date >= start,
                    Transaction.date <= end,
                )
            )
        )
        total_revenue = float(rev_result.scalar() or 0)

        exp_result = await db.execute(
            select(func.coalesce(func.sum(Expense.amount), 0)).where(
                and_(
                    Expense.tenant_id == tenant.id,
                    Expense.date >= start,
                    Expense.date <= end,
                )
            )
        )
        total_expenses = float(exp_result.scalar() or 0)

        profit = total_revenue - total_expenses
        margin = round(profit / total_revenue * 100, 1) if total_revenue > 0 else 0

        # Top chatters
        chatter_result = await db.execute(
            select(Transaction.chatter, func.sum(Transaction.amount).label("rev"))
            .where(
                and_(
                    Transaction.tenant_id == tenant.id,
                    Transaction.date >= start,
                    Transaction.date <= end,
                    Transaction.chatter.isnot(None),
                )
            )
            .group_by(Transaction.chatter)
            .order_by(func.sum(Transaction.amount).desc())
            .limit(5)
        )
        top_chatters = [f"{r.chatter}: ${float(r.rev or 0):,.0f}" for r in chatter_result.all()]

        context = f"""
Данные агентства за {body.month:02d}/{body.year}:
- Выручка: ${total_revenue:,.0f}
- Расходы: ${total_expenses:,.0f}
- Прибыль: ${profit:,.0f}
- Маржа: {margin}%
- Топ чаттеры: {', '.join(top_chatters) or 'нет данных'}
"""

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Ты AI-аналитик для OnlyFans-агентства. Отвечай кратко, по делу, на русском языке. Используй конкретные цифры из контекста.",
                },
                {"role": "user", "content": f"Контекст:\n{context}\n\nВопрос: {body.question}"},
            ],
            max_tokens=800,
            temperature=0.3,
        )

        answer = response.choices[0].message.content or "Нет ответа"
        return AnalyzeResponse(answer=answer)

    except Exception as e:
        logger.error("ai analyze error tenant=%d: %s", tenant.id, e)
        raise HTTPException(status_code=500, detail=f"Ошибка AI: {str(e)}")
