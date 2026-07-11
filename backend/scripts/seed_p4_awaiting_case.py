"""Seed temporary qualitative case in awaiting_review for P.4 screenshot (tenant=1)."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://neondb_owner:npg_yDrCmcTs50xv@"
    "ep-broad-forest-alh2ugau-pooler.c-3.eu-central-1.aws.neon.tech/neondb?sslmode=require",
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-local")

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from database import _asyncpg_connect_args
from models import User, AdminCase, CaseLedger, CaseStageHistory, CaseActivity
from services import admin_cases as svc

SEED_CHATTER = "p4_screenshot_awaiting"
SEED_CATEGORY = "p4_screenshot_eval"

_db_url = os.environ["DATABASE_URL"]
if "?sslmode=" in _db_url:
    _db_url = _db_url.split("?sslmode=")[0]
_engine = create_async_engine(
    _db_url, connect_args={**_asyncpg_connect_args(_db_url), "timeout": 120}
)
Session = async_sessionmaker(bind=_engine, class_=AsyncSession, expire_on_commit=False)


async def seed() -> int:
    async with Session() as db:
        admin = (
            await db.execute(
                select(User).where(
                    User.tenant_id == 1,
                    User.is_admin == True,  # noqa: E712
                    User.active == True,  # noqa: E712
                ).limit(1)
            )
        ).scalar_one()

        existing = (
            await db.execute(
                select(AdminCase).where(
                    AdminCase.tenant_id == 1,
                    AdminCase.om_user_id == SEED_CHATTER,
                    AdminCase.case_type == "qualitative",
                )
            )
        ).scalar_one_or_none()
        if existing:
            if existing.stage != "awaiting_review":
                await svc.transition_stage(db, existing.id, "in_progress", user=admin)
                await db.commit()
                await svc.transition_stage(db, existing.id, "hold", user=admin)
                await db.commit()
                await svc.transition_stage(db, existing.id, "awaiting_review", user=admin)
                await db.commit()
            print(existing.id)
            return existing.id

        case = await svc.create_case(
            db,
            tenant_id=1,
            admin_id=admin.id,
            om_user_id=SEED_CHATTER,
            chatter_display_name="@p4_screenshot",
            diagnosis_text="Диагноз для скриншота P.4: качественный кейс на оценке владельца.",
            action_plan="План: проверить UI блока оценки с тремя кнопками success/failed/return.",
            hold_days=7,
            case_type="qualitative",
            category=SEED_CATEGORY,
        )
        case_id = case.id
        row = await db.get(AdminCase, case_id)
        row.review_date = date.today() - timedelta(days=1)
        await db.commit()
        await svc.transition_stage(db, case_id, "in_progress", user=admin)
        await db.commit()
        await svc.transition_stage(db, case_id, "hold", user=admin)
        await db.commit()
        await svc.transition_stage(db, case_id, "awaiting_review", user=admin)
        await db.commit()
        print(case_id)
        return case_id


async def cleanup() -> None:
    async with Session() as db:
        case = (
            await db.execute(
                select(AdminCase).where(
                    AdminCase.tenant_id == 1,
                    AdminCase.om_user_id == SEED_CHATTER,
                )
            )
        ).scalar_one_or_none()
        if not case:
            print("no seed case")
            return
        cid = case.id
        await db.execute(delete(CaseActivity).where(CaseActivity.case_id == cid))
        await db.execute(delete(CaseLedger).where(CaseLedger.case_id == cid))
        await db.execute(delete(CaseStageHistory).where(CaseStageHistory.case_id == cid))
        await db.execute(delete(AdminCase).where(AdminCase.id == cid))
        await db.commit()
        print(f"deleted case {cid}")


async def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "cleanup":
        await cleanup()
    else:
        await seed()
    await _engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
