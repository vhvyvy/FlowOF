"""
Тот же импорт транзакций, что POST /api/v1/sync/notion-transactions — для cron / GitHub Actions.

Переменные окружения:
  DATABASE_URL          — Neon (как у Railway)
  NOTION_SYNC_TENANT_ID — id строки в tenants (по умолчанию 1)
  NOTION_TOKEN          — опционально: переопределить токен из БД (секрет в Actions)
  NOTION_SYNC_SHIFT_TYPE — relation | select (по умолчанию relation)

Запуск из каталога backend:
  python scripts/run_notion_sync.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from database import AsyncSessionLocal
from notion_sync_service import sync_notion_transactions_for_tenant
from sqlalchemy import select

from models import Tenant


async def main() -> None:
    tenant_id = int(os.getenv("NOTION_SYNC_TENANT_ID", "1"))
    token_override = (os.getenv("NOTION_TOKEN") or os.getenv("NOTION_API_KEY") or "").strip()
    st = (os.getenv("NOTION_SYNC_SHIFT_TYPE") or "relation").strip().lower()
    if st not in ("relation", "select"):
        st = "relation"

    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = r.scalar_one_or_none()
        if not tenant:
            print(f"Tenant id={tenant_id} не найден")
            sys.exit(1)
        token = token_override or (tenant.notion_token or "").strip()
        if not token:
            print("Нет NOTION_TOKEN / NOTION_API_KEY и у tenant пустой notion_token")
            sys.exit(1)
        stats = await sync_notion_transactions_for_tenant(
            db, tenant_id, token, shift_type=st
        )
        print(
            "OK:",
            f"inserted={stats['inserted']} updated={stats['updated']} skipped={stats['skipped']} "
            f"skipped_no_model={stats.get('skipped_no_model', 0)} databases={stats['databases']}",
        )


if __name__ == "__main__":
    asyncio.run(main())
