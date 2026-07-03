import logging
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_tenant
from models import Tenant

logger = logging.getLogger("flowof.ai")
router = APIRouter(prefix="/api/v1/ai", tags=["ai"])

# How many past turns to feed back to the model (user+assistant = 2 rows per exchange).
# 20 rows = 10 exchanges — keeps context manageable while covering most sessions.
_HISTORY_LIMIT = 20


# ── Schemas ────────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    question:   str
    month:      int
    year:       int
    session_id: str | None = None   # omit → new session created server-side


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
    session_id:      str                 # always returned so the client can persist it


class ChatMessage(BaseModel):
    role:       str
    content:    str
    created_at: str | None = None


class HistoryResponse(BaseModel):
    session_id: str
    messages:   list[ChatMessage]


# ── DB helpers ─────────────────────────────────────────────────────────────────

async def _load_history(
    db: AsyncSession,
    tenant_id: int,
    session_id: str,
    limit: int = _HISTORY_LIMIT,
) -> list[dict[str, str]]:
    """Return the last `limit` messages for a session, oldest-first.

    Returns simple dicts {"role": "...", "content": "..."} ready for Anthropic API.
    """
    rows = (await db.execute(
        text(
            """
            SELECT role, content FROM (
                SELECT id, role, content
                FROM ai_chat_messages
                WHERE tenant_id  = :tid
                  AND session_id = :sid
                ORDER BY id DESC
                LIMIT :lim
            ) sub
            ORDER BY id ASC
            """
        ),
        {"tid": tenant_id, "sid": session_id, "lim": limit},
    )).fetchall()
    return [{"role": r[0], "content": r[1]} for r in rows]


async def _save_exchange(
    db: AsyncSession,
    tenant_id: int,
    session_id: str,
    user_content: str,
    assistant_content: str,
) -> None:
    """Persist a user→assistant exchange (two rows) atomically."""
    await db.execute(
        text(
            """
            INSERT INTO ai_chat_messages (tenant_id, session_id, role, content)
            VALUES
              (:tid, :sid, 'user',      :user_msg),
              (:tid, :sid, 'assistant', :asst_msg)
            """
        ),
        {
            "tid":      tenant_id,
            "sid":      session_id,
            "user_msg": user_content[:8000],    # guard against oversized saves
            "asst_msg": assistant_content[:8000],
        },
    )
    await db.commit()


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    body: AnalyzeRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Agentic AI analyst: Claude calls read tools, investigates data, answers in Russian.

    Supports multi-turn sessions: pass session_id from the previous response to
    continue a conversation.  Omit or pass null to start a fresh session.
    """
    # Resolve / generate session
    session_id = (body.session_id or "").strip() or str(uuid.uuid4())
    tid = tenant.id   # capture before any DB operations expire the ORM object

    try:
        from services.llm_analyst import LLMAnalyst

        context_hint = (
            f"Владелец сейчас смотрит на период {body.month:02d}/{body.year}. "
            "При ответе на вопросы без явного периода используй этот месяц как дефолтный."
        )

        # Load prior conversation turns for this session
        try:
            chat_history = await _load_history(db, tid, session_id)
        except Exception as exc:
            logger.warning("ai: could not load chat history session=%s: %s", session_id, exc)
            try:
                await db.rollback()
            except Exception:
                pass
            chat_history = []

        analyst = LLMAnalyst()
        result  = await analyst.answer_question_agentic(
            db=db,
            tenant_id=tid,
            question=body.question,
            context_hint=context_hint,
            chat_history=chat_history,
        )

        answer = result.get("answer", "")

        # Persist this exchange (best-effort — don't fail the response if it errors)
        if answer:
            try:
                await _save_exchange(db, tid, session_id, body.question, answer)
            except Exception as exc:
                logger.warning("ai: could not save chat history session=%s: %s", session_id, exc)
                try:
                    await db.rollback()
                except Exception:
                    pass

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

        return AnalyzeResponse(
            answer=answer,
            proposed_events=proposed,
            session_id=session_id,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("ai analyze error tenant=%d: %s", tid, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка AI: {str(e)}")


@router.get("/history", response_model=HistoryResponse)
async def get_chat_history(
    session_id: str = Query(..., description="Session UUID"),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Return all messages for a given chat session (for page-reload restore)."""
    tid = tenant.id
    try:
        rows = (await db.execute(
            text(
                """
                SELECT role, content, TO_CHAR(created_at, 'YYYY-MM-DD"T"HH24:MI:SS') AS ts
                FROM ai_chat_messages
                WHERE tenant_id  = :tid
                  AND session_id = :sid
                ORDER BY id ASC
                """
            ),
            {"tid": tid, "sid": session_id},
        )).fetchall()
        messages = [ChatMessage(role=r[0], content=r[1], created_at=r[2]) for r in rows]
        return HistoryResponse(session_id=session_id, messages=messages)
    except Exception as exc:
        logger.error("ai history error tenant=%d: %s", tid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка загрузки истории")
