"""
SeasonService: закрытие сезона, фиксация результатов, перенос MMR.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("flowof.season")


class SeasonService:
    """Закрытие сезона: фиксация результатов, топ-3 призы, перенос MMR."""

    async def close_season(self, season_id: int, db: AsyncSession) -> dict:
        """
        1. Записать season_results для всех откалиброванных чаттеров.
        2. Назначить призы топ-3.
        3. Пометить сезон закрытым.
        4. Перенос MMR в следующий сезон — происходит автоматически
           при первом вызове MMRService.process_day через start-событие.
        """
        # Все откалиброванные чаттеры сезона по убыванию MMR
        result = await db.execute(
            text(
                """SELECT cm.chatter_id, cm.current_mmr, cm.current_league, cm.tenant_id
                   FROM chatter_mmr cm
                   WHERE cm.season_id = :sid
                     AND cm.calibration_complete = TRUE
                   ORDER BY cm.current_mmr DESC"""
            ),
            {"sid": season_id},
        )
        chatters = list(result.mappings())

        if not chatters:
            logger.warning("close_season: сезон %s — нет откалиброванных чаттеров", season_id)
            await db.execute(
                text("UPDATE mmr_seasons SET is_active = FALSE, closed_at = NOW() WHERE id = :sid"),
                {"sid": season_id},
            )
            await db.commit()
            return {"season_id": season_id, "closed": True, "chatters_finalized": 0}

        tenant_id = chatters[0]["tenant_id"]

        settings_result = await db.execute(
            text(
                """SELECT prize_1st, prize_2nd, prize_3rd, season_carry_over
                   FROM mmr_settings WHERE tenant_id = :tid"""
            ),
            {"tid": tenant_id},
        )
        settings = settings_result.mappings().first()
        prizes = {
            1: float(settings["prize_1st"] or 200) if settings else 200,
            2: float(settings["prize_2nd"] or 150) if settings else 150,
            3: float(settings["prize_3rd"] or 100) if settings else 100,
        }

        # Удалить старые результаты этого сезона (идемпотентность)
        await db.execute(
            text("DELETE FROM season_results WHERE season_id = :sid"),
            {"sid": season_id},
        )

        for rank, ch in enumerate(chatters, start=1):
            prize = prizes.get(rank, 0)
            await db.execute(
                text(
                    """INSERT INTO season_results
                       (tenant_id, season_id, chatter_id, final_mmr, final_league, rank, prize_amount)
                       VALUES (:tid, :sid, :cid, :mmr, :league, :rank, :prize)"""
                ),
                {
                    "tid": tenant_id,
                    "sid": season_id,
                    "cid": ch["chatter_id"],
                    "mmr": ch["current_mmr"],
                    "league": ch["current_league"],
                    "rank": rank,
                    "prize": prize,
                },
            )

        # Закрыть сезон
        await db.execute(
            text("UPDATE mmr_seasons SET is_active = FALSE, closed_at = NOW() WHERE id = :sid"),
            {"sid": season_id},
        )

        # Перенос MMR: создать стартовые carry-события в новом сезоне
        # Это произойдёт при первом вызове MMRService.process_day автоматически
        # через _get_or_create_active_season, но carry-очки нужно записать явно.
        carry_over = float(settings["season_carry_over"] or 0.5) if settings else 0.5

        if carry_over > 0:
            from services.mmr_service import MMRService
            svc = MMRService(db)
            # Определим дату нового сезона — день после end_date текущего
            season_row = await db.execute(
                text("SELECT end_date FROM mmr_seasons WHERE id = :sid"),
                {"sid": season_id},
            )
            season_data = season_row.mappings().first()
            if season_data:
                import datetime as _dt
                new_date = season_data["end_date"] + _dt.timedelta(days=1)
                new_season = await svc._get_or_create_active_season(tenant_id, new_date)
                for ch in chatters:
                    carry_mmr = int(ch["current_mmr"] * carry_over)
                    if carry_mmr > 0:
                        await svc._create_event(
                            tenant_id=tenant_id,
                            chatter_id=ch["chatter_id"],
                            season_id=new_season.id,
                            event_date=new_date,
                            event_type="carry",
                            category="season_carry",
                            points=carry_mmr,
                            description=f"Перенос {carry_over*100:.0f}% MMR из сезона {season_id}",
                        )
                await svc._recalculate_mmr_state(tenant_id, new_season)

        await db.commit()
        logger.info("Сезон %s закрыт, чаттеров финализировано: %s", season_id, len(chatters))
        return {
            "season_id": season_id,
            "closed": True,
            "chatters_finalized": len(chatters),
            "top_3": [
                {
                    "rank": i + 1,
                    "chatter_id": chatters[i]["chatter_id"],
                    "mmr": chatters[i]["current_mmr"],
                    "prize": prizes.get(i + 1, 0),
                }
                for i in range(min(3, len(chatters)))
            ],
        }
