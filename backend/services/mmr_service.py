"""
MMR-сервис: расчёт рейтинга чаттеров по дням.

Этап 1 — финансовая часть.
KPI-часть (Onlymonster) подключается в Этапе 2.
"""
from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("flowof.mmr")

# ── Лиги ─────────────────────────────────────────────────────────────────────

LEAGUE_THRESHOLDS: list[tuple[str, int]] = [
    ("bronze_iii",    0),
    ("bronze_ii",   100),
    ("bronze_i",    200),
    ("silver_iii",  300),
    ("silver_ii",   450),
    ("silver_i",    600),
    ("gold_iii",    800),
    ("gold_ii",    1000),
    ("gold_i",     1250),
    ("platinum_iii", 1500),
    ("platinum_ii",  1800),
    ("platinum_i",   2100),
    ("diamond_iii",  2500),
    ("diamond_ii",   3000),
    ("diamond_i",    3500),
    ("master",       4500),
    ("grandmaster",  6000),
]


def mmr_to_league(mmr: int) -> str:
    """Определить лигу по числу MMR."""
    league = LEAGUE_THRESHOLDS[0][0]
    for name, threshold in LEAGUE_THRESHOLDS:
        if mmr >= threshold:
            league = name
        else:
            break
    return league


# ── Вспомогательный класс-обёртка для словаря ────────────────────────────────

class _Row:
    """Позволяет обращаться к словарю через атрибуты: row.field."""
    def __init__(self, data: dict[str, Any]) -> None:
        self.__dict__.update(data)

    def __getattr__(self, item: str) -> Any:  # fallback
        return None


# ── Главный сервис ────────────────────────────────────────────────────────────

class MMRService:
    """
    Расчёт MMR-событий за день для всех чаттеров tenant.
    Запускается ежедневно через APScheduler (Этап 4) или вручную через API.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Публичный метод ───────────────────────────────────────────────────────

    async def process_day(self, tenant_id: int, target_date: date) -> dict:
        """
        Обработать один день для tenant.
        Возвращает словарь со статистикой обработки.
        """
        settings = await self._get_settings(tenant_id)
        season = await self._get_or_create_active_season(tenant_id, target_date)

        events_created = await self._process_finance(tenant_id, season, settings, target_date)

        # KPI-часть подключается в Этапе 2:
        # if settings.kpi_enabled:
        #     await self._process_kpi(tenant_id, season, settings, target_date)

        await self._recalculate_mmr_state(tenant_id, season)
        await self.db.commit()

        logger.info(
            "MMR обработан: tenant=%s date=%s events=%s season=%s",
            tenant_id, target_date, events_created, season.id,
        )
        return {
            "tenant_id": tenant_id,
            "date": str(target_date),
            "season_id": season.id,
            "season_name": season.name,
            "events_created": events_created,
        }

    # ── Финансовая часть ──────────────────────────────────────────────────────

    async def _process_finance(
        self,
        tenant_id: int,
        season: _Row,
        settings: _Row,
        target_date: date,
    ) -> int:
        """
        Для каждой группы (chatter × shift × model) за день:
        сравниваем выручку с дневным планом и записываем MMR-событие.

        Работает с обоими типами транзакций:
        - chatter_id (FK) проставлен → прямой lookup
        - chatter_id NULL, но есть текстовый chatter → матчинг через JOIN на chatters
        """
        # Удалить уже существующие finance-события за этот день (идемпотентность)
        await self.db.execute(
            text(
                """DELETE FROM mmr_events
                   WHERE tenant_id = :tid
                     AND season_id = :sid
                     AND event_date = :dt
                     AND event_type = 'finance'"""
            ),
            {"tid": tenant_id, "sid": season.id, "dt": target_date},
        )

        # Транзакции за день с разрешением chatter_id через FK или текстовый JOIN.
        # COALESCE(t.chatter_id, c.id) покрывает оба случая:
        #   1) chatter_id заполнен (backfill прошёл)
        #   2) chatter_id NULL, но t.chatter (текст) матчится с chatters.name
        txn_result = await self.db.execute(
            text(
                """SELECT
                       COALESCE(t.chatter_id, c_text.id)                       AS chatter_id,
                       t.shift_catalog_id                                        AS shift_id,
                       t.model_id,
                       COALESCE(mo.name, t.model, '')                           AS model_name,
                       SUM(t.amount)                                             AS revenue
                   FROM transactions t
                   -- resolved chatter via FK
                   LEFT JOIN chatters c_fk
                          ON c_fk.id = t.chatter_id
                         AND c_fk.tenant_id = :tid
                   -- fallback: resolve chatter via text name
                   LEFT JOIN chatters c_text
                          ON c_text.tenant_id = :tid
                         AND t.chatter_id IS NULL
                         AND LOWER(TRIM(c_text.name)) = LOWER(TRIM(t.chatter))
                   -- model name from catalog
                   LEFT JOIN models mo
                          ON mo.id = t.model_id
                   WHERE t.tenant_id = :tid
                     AND t.date = CAST(:dt AS date)
                     AND COALESCE(t.chatter_id, c_text.id) IS NOT NULL
                   GROUP BY
                       COALESCE(t.chatter_id, c_text.id),
                       t.shift_catalog_id,
                       t.model_id,
                       COALESCE(mo.name, t.model, '')"""
            ),
            {"tid": tenant_id, "dt": str(target_date)},
        )
        day_groups = list(txn_result.mappings())

        logger.debug(
            "_process_finance: tenant=%s date=%s day_groups=%s",
            tenant_id, target_date, len(day_groups),
        )

        if not day_groups:
            logger.info(
                "MMR finance: 0 транзакций с chatter для tenant=%s date=%s",
                tenant_id, target_date,
            )
            return 0

        # Количество активных смен в агентстве (минимум 1)
        shifts_count_result = await self.db.execute(
            text("SELECT COUNT(*) FROM shifts_catalog WHERE tenant_id = :tid AND active = TRUE"),
            {"tid": tenant_id},
        )
        shifts_count = int(shifts_count_result.scalar() or 1)

        days_in_month = self._days_in_month(target_date)
        events_created = 0
        skipped_no_plan = 0

        for row in day_groups:
            # Имя модели: из FK на models → иначе текстовое поле t.model
            model_name: str = (row["model_name"] or "").strip()
            if not model_name:
                logger.debug("MMR: пропуск — нет имени модели для chatter=%s", row["chatter_id"])
                continue

            revenue = float(row["revenue"] or 0)

            # Ищем план по имени модели.
            # plans.model — текстовый столбец с именем анкеты.
            # model_name получен через: COALESCE(models.name, t.model)
            # то есть: если есть FK model_id → берём имя из catalog; иначе текст из транзакции.
            plan_result = await self.db.execute(
                text(
                    """SELECT plan_amount FROM plans
                       WHERE tenant_id = :tid
                         AND month     = :m
                         AND year      = :y
                         AND LOWER(TRIM(model)) = LOWER(TRIM(:mname))
                       LIMIT 1"""
                ),
                {
                    "tid": tenant_id,
                    "m": target_date.month,
                    "y": target_date.year,
                    "mname": model_name,
                },
            )
            plan_row = plan_result.mappings().first()

            if not plan_row or not plan_row["plan_amount"]:
                skipped_no_plan += 1
                logger.debug(
                    "MMR: нет плана для модели '%s' tenant=%s %s/%s",
                    model_name, tenant_id, target_date.month, target_date.year,
                )
                continue

            monthly_plan = float(plan_row["plan_amount"])
            daily_plan = monthly_plan / shifts_count / days_in_month
            performance = revenue / daily_plan if daily_plan > 0 else 0.0

            fin_over = float(settings.fin_overperform_threshold or 1.10)
            fin_under = float(settings.fin_underperform_threshold or 0.90)

            if performance >= fin_over:
                category = "overperform"
                points = int(settings.fin_overperform_points or 25)
            elif performance >= fin_under:
                category = "perform"
                points = int(settings.fin_perform_points or 15)
            else:
                category = "underperform"
                points = int(settings.fin_underperform_points or -15)

            description = (
                f"План ${daily_plan:.0f}, выручка ${revenue:.0f} ({performance * 100:.0f}%)"
            )

            await self._create_event(
                tenant_id=tenant_id,
                chatter_id=row["chatter_id"],
                season_id=season.id,
                event_date=target_date,
                event_type="finance",
                category=category,
                points=points,
                description=description,
                shift_id=row["shift_id"],
                model_id=row["model_id"],
            )
            events_created += 1

        logger.info(
            "MMR finance: tenant=%s date=%s created=%s skipped_no_plan=%s",
            tenant_id, target_date, events_created, skipped_no_plan,
        )
        return events_created

    # ── Пересчёт состояния ────────────────────────────────────────────────────

    async def _recalculate_mmr_state(self, tenant_id: int, season: _Row) -> None:
        """Пересчитать current_mmr, лигу и дни активности для всех чаттеров сезона."""
        result = await self.db.execute(
            text(
                """SELECT chatter_id,
                          COALESCE(SUM(points), 0) AS total_mmr,
                          COUNT(DISTINCT event_date)  AS active_days
                   FROM mmr_events
                   WHERE tenant_id = :tid AND season_id = :sid
                   GROUP BY chatter_id"""
            ),
            {"tid": tenant_id, "sid": season.id},
        )

        settings = await self._get_settings(tenant_id)
        calib_days = int(settings.calibration_days or 14)

        for row in result.mappings():
            total = max(0, int(row["total_mmr"]))
            active_days = int(row["active_days"])
            calibrated = active_days >= calib_days
            league = mmr_to_league(total) if calibrated else None

            await self.db.execute(
                text(
                    """INSERT INTO chatter_mmr
                       (tenant_id, chatter_id, season_id, current_mmr, peak_mmr,
                        current_league, calibration_complete, days_active)
                       VALUES (:tid, :cid, :sid, :mmr, :mmr, :league, :calib, :days)
                       ON CONFLICT (tenant_id, chatter_id, season_id) DO UPDATE
                       SET current_mmr          = :mmr,
                           peak_mmr             = GREATEST(chatter_mmr.peak_mmr, :mmr),
                           current_league       = :league,
                           calibration_complete = :calib,
                           days_active          = :days"""
                ),
                {
                    "tid": tenant_id,
                    "cid": row["chatter_id"],
                    "sid": season.id,
                    "mmr": total,
                    "league": league,
                    "calib": calibrated,
                    "days": active_days,
                },
            )

    # ── Настройки ─────────────────────────────────────────────────────────────

    async def _get_settings(self, tenant_id: int) -> _Row:
        """Вернуть настройки MMR, создав дефолтные если их нет."""
        result = await self.db.execute(
            text("SELECT * FROM mmr_settings WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        row = result.mappings().first()
        if row:
            return _Row(dict(row))

        await self.db.execute(
            text("INSERT INTO mmr_settings (tenant_id) VALUES (:tid) ON CONFLICT DO NOTHING"),
            {"tid": tenant_id},
        )
        await self.db.flush()
        result = await self.db.execute(
            text("SELECT * FROM mmr_settings WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        return _Row(dict(result.mappings().first()))

    # ── Сезон ─────────────────────────────────────────────────────────────────

    async def _get_or_create_active_season(self, tenant_id: int, target_date: date) -> _Row:
        """Найти активный сезон охватывающий target_date или создать новый квартал."""
        result = await self.db.execute(
            text(
                """SELECT * FROM mmr_seasons
                   WHERE tenant_id = :tid
                     AND is_active = TRUE
                     AND :dt BETWEEN start_date AND end_date
                   LIMIT 1"""
            ),
            {"tid": tenant_id, "dt": target_date},
        )
        row = result.mappings().first()
        if row:
            return _Row(dict(row))

        quarter_start, quarter_end, name = self._quarter_bounds(target_date)
        ins = await self.db.execute(
            text(
                """INSERT INTO mmr_seasons (tenant_id, name, start_date, end_date)
                   VALUES (:tid, :name, :start, :end)
                   RETURNING *"""
            ),
            {"tid": tenant_id, "name": name, "start": quarter_start, "end": quarter_end},
        )
        await self.db.flush()
        return _Row(dict(ins.mappings().first()))

    # ── Служебные методы ──────────────────────────────────────────────────────

    async def _create_event(
        self,
        tenant_id: int,
        chatter_id: int,
        season_id: int,
        event_date: date,
        event_type: str,
        category: str,
        points: int,
        description: str | None = None,
        shift_id: int | None = None,
        model_id: int | None = None,
    ) -> None:
        await self.db.execute(
            text(
                """INSERT INTO mmr_events
                   (tenant_id, chatter_id, season_id, event_date, event_type,
                    category, points, description, shift_id, model_id)
                   VALUES (:tid, :cid, :sid, :dt, :etype,
                           :cat, :pts, :desc, :shift_id, :model_id)"""
            ),
            {
                "tid": tenant_id,
                "cid": chatter_id,
                "sid": season_id,
                "dt": event_date,
                "etype": event_type,
                "cat": category,
                "pts": points,
                "desc": description,
                "shift_id": shift_id,
                "model_id": model_id,
            },
        )

    def _quarter_bounds(self, d: date) -> tuple[date, date, str]:
        """Вернуть (start, end, name) квартала для даты."""
        q = (d.month - 1) // 3 + 1
        start_month = (q - 1) * 3 + 1
        end_month = start_month + 2
        start = date(d.year, start_month, 1)
        end = date(d.year, end_month, monthrange(d.year, end_month)[1])
        names = {1: "Зима", 2: "Весна", 3: "Лето", 4: "Осень"}
        return start, end, f"{names[q]} {d.year}"

    def _days_in_month(self, d: date) -> int:
        return monthrange(d.year, d.month)[1]
