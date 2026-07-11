# FlowOF — Handoff (операционный статус)

Последнее обновление: 11 июля 2026. Документ для передачи контекста между сессиями Cursor / между разработчиками.

**Деплой:** backend → Railway (`/backend`), frontend → Vercel (`/frontend`), БД → Neon PostgreSQL.

**Недавние коммиты (качественные кейсы):** `3de95bc` (п.1 схема) → `af32241` (п.2 сервис) → `cb53081` (п.3 API) → `aa23660` (п.4 admin UI) → `486fb31` (п.5 owner UI) → `b0a836b` (`hold_days=0`).

---

## KPI-модуль админов → Слой 1

- ✅ **1.1 — Схема БД:** enums, `admin_cases`, `case_stage_history`, `baseline_snapshots`, `case_ledger`, `kpi_config`, `admin_kpi_snapshot`, `admin_shift_id` в `users` (`schema_patch`).
- ✅ **1.2 — Сервисный слой:** `admin_cases.py`, `case_baseline.py`, `case_ledger.py`, `case_review_service.py`, `admin_kpi_calc.py`.
- ✅ **1.3 — API кейсов:** `/api/v1/admin-portal/*` (админ), `/api/v1/dashboard/admins-review/*` (овнер, read-only).
- ✅ **1.4 — CRON:** HOLD-проверка `check_review_due_cases` (05:00 UTC, `ENABLE_ADMIN_KPI`).
- ✅ **1.5 — Портал админа (frontend):** `/admin-portal` — обзор, чаттеры, мои кейсы, карточка кейса, история.
- ✅ **1.6 — Овнерский обзор (frontend):** `/dashboard/admins-review` — главная с KPI-таблицей, детали админа, универсальная страница кейса, редактор `kpi_config`, сайдбар. Коммиты `59f523c`…`abfe8d1`.
- ⏳ **1.7 — Инвайт-флоу для админов:** backend + UI создания инвайтов на `/dashboard/admins`, активация `/admin-join/[token]`; полировка и edge-cases — отдельно.
- ✅ **1.8 — Активности в кейсе + файловое хранилище:** Railway Volume на `/data`, таблицы `case_activities` + `case_activity_files`, enum `activity_type` (6 типов: review / training / meeting / observation / note / other). API: `POST/GET/DELETE /api/v1/admin-portal/cases/{id}/activities`, `GET /api/v1/admin-portal/activities/files/{id}`, owner-read `GET /api/v1/dashboard/admins-review/cases/{id}/activities`. UI на странице кейса: форма (только автор), фильтры, лента, lightbox, удаление в течение 24 ч.
- ✅ **1.9 — Качественные кейсы (`case_type=qualitative`):** новый тип кейса без метрик, категория свободным текстом, HOLD задаёт админ, отправка на оценку → овнер закрывает (success +5 / failed −2) или возвращает на доработку с комментарием (системная note в ленте активностей). Лимит 5 открытых на админа. Guardrail и detect:result ratio не применяются. Отдельные partial unique index'ы для quantitative и qualitative кейсов. Стадия `awaiting_review` в FSM. Минимальный овнерский UI `/dashboard/admins-review/pending` + детальная страница для оценки. Коммиты `3de95bc`…`486fb31`.
- ✅ **1.10 — Овнерский обзор `/dashboard/admins-review`:** главная с таблицей N админов, KPI-балл текущего месяца, кнопка «Пересчитать сейчас» (батч и по одному). Детали админа с секциями кейсов и ledger, переключатель периода. Универсальная страница кейса (quant + qual) в read-only; для qual `awaiting_review` — три кнопки оценки. Редактор `kpi_config`. Ночной cron `nightly_kpi_snapshot_recalc` в 04:30 UTC под флагом `ENABLE_ADMIN_KPI_NIGHTLY=1`. Коммиты `59f523c`…`abfe8d1`.

---

## Активная задача

**1.6 закрыто.** UX-полировка портала админа и овнерский обзор admins-review полностью завершены. Следующие приоритеты определит владелец.

### UX-полировка портала админа (завершена)

- ✅ **1.** Месячные KPI на `/admin-portal/chatters`, колонки и `display_name`.
- ✅ **2.** Блок метрик на `/admin-portal/cases/[id]` (baseline / вчера / неделя / месяц), `hold_days` при создании кейса.
- ✅ **3.** Строгий фильтр активности чаттеров (30d: `total_chats > 0` OR транзакция `amount > 0`).
- ✅ **4.** Исключение `[Adm]`-аккаунтов из списка чаттеров + fallback `display_name`.
- ✅ **5.** Активности в кейсе + файловое хранилище. **Хранилище решено:** Railway Volume, `/data` примонтирован, `FILE_STORAGE_ROOT=/data` в Railway Variables. Коммиты `469c3d0`…`5288ee6`.

- ✅ **Качественные кейсы** (`case_type=qualitative` — отдельный тип кейса без числового baseline). Коммиты `3de95bc`…`486fb31`, задеплоено на prod.

- ✅ **1.6 — Овнерский обзор `/dashboard/admins-review`:** главная, детали админа, универсальная страница кейса, конфиг KPI, ночной cron снапшотов. Коммиты `59f523c`…`abfe8d1`, задеплоено на prod.

---

## Хвосты (открытые вопросы по активной задаче)

*(пусто — открытых блокеров по текущей задаче нет)*

---

## Хвосты вне активной задачи

- **`hold_days=0` разрешён** (для тестов и краевых случаев). В проде разумный минимум 7–14 дней; ограничение стоит на овнере через `kpi_config` при развитии.
- **Тестовые qualitative-кейсы 39–43** на dev-БД (`qual_ui_seed_chatter_1`…`4`) — почистить перед демо, если нужно.
- **CardinalityViolationError** в `schema_patch` на `INSERT INTO chatter_mmr` при переходе сезонов (Весна 2026 → Лето 2026): в логах видно WARNING, миграция не падает целиком, но патч скипается. Разобраться отдельно.

---

## Стек / env-переменные (ключевые)

| Переменная | Назначение |
|---|---|
| `DATABASE_URL` | Neon PostgreSQL (`postgresql+asyncpg://…`) |
| `SECRET_KEY` | JWT |
| `FRONTEND_URL` | CORS (Vercel URL) |
| `ENABLE_SCHEDULER` | APScheduler (notion sync, MMR, KPI daily, …) |
| `ENABLE_KPI_DAILY` | Сбор `chatter_kpi_daily` (04:00 UTC) |
| `ENABLE_ADMIN_KPI` | HOLD-review cron + роутеры admin KPI (05:00 UTC) |
| `ENABLE_ADMIN_KPI_NIGHTLY` | Ночной пересчёт `admin_kpi_snapshot` (04:30 UTC) |
| `FILE_STORAGE_ROOT` | **`/data`** на Railway (Volume mount); локально `./local_storage` |
| `ANTHROPIC_API_KEY` | AI-аналитик / watcher |

---

## Ссылки на спеки

- Базовые правила и стек: `.cursorrules`
- KPI-модуль (полная спека): `.cursorrules` § «FlowOF Admin Cabinet + KPI-модуль»
- FlowOF Intelligence: `.cursorrules` § «второй мозг агентства»
