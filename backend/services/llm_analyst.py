"""Claude-based LLM analyst for agency data questions."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("flowof.llm_analyst")

SYSTEM_PROMPT = (
    "Ты AI-аналитик для OnlyFans-агентства. "
    "Отвечай кратко, по делу, на русском, с конкретными цифрами из предоставленных данных.\n\n"
    "Данные структурированы в четыре уровня:\n"
    "1. «ЗА ВСЁ ВРЕМЯ» — агрегаты за всю историю (общая выручка, топ чаттеры, модели, расходы по категориям).\n"
    "2. «ПОМЕСЯЧНАЯ ДИНАМИКА» — помесячный ряд тоталов (выручка / расходы / прибыль) за всю историю.\n"
    "3. «ДЕТАЛИЗАЦИЯ ПО МЕСЯЦАМ» — разбивка по чаттерам, моделям и сменам за каждый из последних ≤18 месяцев. "
    "Используй этот раздел для сравнения конкретных чаттеров или моделей между любыми двумя месяцами, "
    "для поиска лучшего/худшего месяца у конкретного чаттера, для анализа динамики смен и т.п.\n"
    "4. «ФОКУСНЫЙ МЕСЯЦ» — детальный срез выбранного месяца с планом по моделям, сменам, чаттерами и расходами, "
    "плюс сравнение с предыдущим месяцем.\n\n"
    "Правила выбора раздела под вопрос:\n"
    "— тренды, лучший/худший месяц, общая динамика → «ПОМЕСЯЧНАЯ ДИНАМИКА» + «ЗА ВСЁ ВРЕМЯ»;\n"
    "— сравнение конкретного чаттера/модели/смены между месяцами → «ДЕТАЛИЗАЦИЯ ПО МЕСЯЦАМ»;\n"
    "— план, смены, расходы текущего месяца → «ФОКУСНЫЙ МЕСЯЦ»;\n"
    "— суммарные результаты агентства → «ЗА ВСЁ ВРЕМЯ».\n\n"
    "КРИТИЧНО: используй ТОЛЬКО те цифры, что есть в данных. "
    "Если для ответа не хватает данных — прямо скажи «таких данных нет» и НЕ придумывай числа. "
    "Где уместно — сравнивай с прошлым месяцем и давай короткий практический вывод."
)


class LLMAnalyst:
    def __init__(self) -> None:
        self.api_key       = os.getenv("ANTHROPIC_API_KEY", "")
        self.analyst_model = os.getenv("AI_ANALYST_MODEL", "claude-sonnet-4-6")

    async def generate_report_insights(self, snapshot_text: str, kpi_text: str) -> dict:
        """Generate structured management report insights via Claude.
        Returns dict with keys: summary, diagnosis, priorities, chatter_notes.
        Falls back to empty placeholders on parse errors.
        """
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured")

        from anthropic import AsyncAnthropic

        report_model = os.getenv("AI_REPORT_MODEL", "claude-opus-4-8")
        system = (
            "Ты Head of Sales OnlyFans-агентства. По предоставленным данным составь управленческий отчёт. "
            "Верни СТРОГО валидный JSON без markdown-обёртки (без ```json) с ключами:\n"
            "  summary — главный вывод за период, 2–3 предложения;\n"
            "  diagnosis — диагноз текущей ситуации, 2–4 предложения;\n"
            "  priorities — массив из 3–5 строк: что исправить или развить в первую очередь;\n"
            "  chatter_notes — массив объектов {\"chatter\": \"...\", \"note\": \"...\"} "
            "по топ-5 чаттерам (короткий управленческий вывод по каждому).\n"
            "КРИТИЧНО: используй ТОЛЬКО цифры из данных. Не выдумывай числа."
        )
        user_content = (
            f"Финансовые данные:\n{snapshot_text}\n\n"
            f"KPI данные:\n{kpi_text}"
        )

        client = AsyncAnthropic(api_key=self.api_key)
        resp = await client.messages.create(
            model=report_model,
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = resp.content[0].text.strip()

        # Strip optional markdown code fence if model added it
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("report_insights: failed to parse JSON, using raw text as summary")
            data = {
                "summary":       raw[:500],
                "diagnosis":     "Не удалось разобрать структурированный ответ.",
                "priorities":    [],
                "chatter_notes": [],
            }

        return {
            "summary":       data.get("summary", ""),
            "diagnosis":     data.get("diagnosis", ""),
            "priorities":    data.get("priorities", []),
            "chatter_notes": data.get("chatter_notes", []),
        }

    # ── Agentic tool-use loop ─────────────────────────────────────────────────

    async def answer_question_agentic(
        self,
        db: AsyncSession,
        tenant_id: int,
        question: str,
        max_iterations: int = 8,
        context_hint: str = "",
    ) -> dict[str, Any]:
        """Run an agentic tool-use loop: Claude calls read/write tools, answers.

        Returns dict with keys:
          answer          (str)   — final text response
          proposed_events (list)  — structured event suggestions (NOT auto-created)

        Invariants:
          - tenant_id injected by server for every tool call; model never sees it.
          - Loop capped at max_iterations.
          - Failed tool → db.rollback() + error as tool_result (no crash, no poison).
        """
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured")

        from anthropic import AsyncAnthropic
        from services.analyst_tools import TOOL_DESCRIPTIONS, TOOL_REGISTRY, get_open_events
        from services.agency_profile import build_profile_context

        # ── Load agency passport (semantic context) ────────────────────────────
        profile_context = ""
        try:
            profile_context = await build_profile_context(db, tenant_id)
        except Exception as e:
            logger.debug("agentic: could not load agency profile: %s", e)
            try:
                await db.rollback()
            except Exception:
                pass

        # ── Load open events for memory context ───────────────────────────────
        open_events_context = ""
        try:
            open_events = await get_open_events(db, tenant_id)
            if open_events:
                lines = ["ОТКРЫТЫЕ СОБЫТИЯ (память агента):"]
                for ev in open_events[:10]:
                    ref = f" [{ev['entity_ref']}]" if ev.get("entity_ref") else ""
                    lines.append(
                        f"  #{ev['id']} [{ev['priority']}] {ev['title']}{ref} "
                        f"— статус: {ev['status']}"
                        + (f", проверить: {ev['review_date']}" if ev.get("review_date") else "")
                    )
                open_events_context = "\n".join(lines)
        except Exception as e:
            logger.debug("agentic: could not load open events: %s", e)
            try:
                await db.rollback()
            except Exception:
                pass

        # ── System prompt (spec 1.2 + 2.4 + 4.x extensions) ──────────────────
        system = (
            "Ты AI-аналитик OnlyFans-агентства — второй мозг владельца. "
            "У тебя есть инструменты для доступа к реальным данным и слой памяти (события).\n\n"
            "ПРАВИЛА АНАЛИЗА:\n"
            "1. Не отвечай наугад — вызывай инструменты и получай реальные цифры.\n"
            "2. Веди расследование: увидел аномалию → копай глубже "
            "(сравни периоды, посмотри разбивку, проверь KPI).\n"
            "3. Делай выводы: объясняй ПОЧЕМУ, находи корень проблемы, "
            "давай практические рекомендации.\n"
            "4. Только реальные цифры из инструментов. "
            "Нет данных → скажи прямо «таких данных нет», не выдумывай.\n"
            "5. Отвечай на русском, конкретно.\n"
            "6. tenant_id ты не знаешь и не запрашиваешь — сервер сам передаёт его в инструменты.\n\n"
            "ПРАВИЛА ПАСПОРТА АГЕНТСТВА:\n"
            "Тебе дан ПАСПОРТ АГЕНТСТВА с порогами нормы и приоритетами владельца. "
            "Используй эти пороги при оценке метрик (напр. RPC ниже rpc_critical — тревога, "
            "выше rpc_strong — отлично), а не абстрактные значения. "
            "Учитывай приоритеты владельца в рекомендациях. "
            "Пороги — это мнение владельца о своём агентстве, не стандартные нормативы.\n\n"
            "ПРАВИЛА ПАМЯТИ (события):\n"
            "7. Перед ответом сверяйся с открытыми событиями: если вопрос касается сущности "
            "с открытым событием — отвечай с учётом его истории и статуса.\n"
            "8. Жёсткую объективную аномалию (данные из инструментов, чёткий порог) → "
            "можешь зафиксировать событием сам через create_event(source='watcher').\n"
            "9. Субъективный вывод, интерпретацию — НЕ создавай без спроса. "
            "Предлагай владельцу через proposed_events в ответе (не вызывай create_event).\n"
            "10. Не создавай дубли: проверь get_open_events по entity_ref перед create_event."
        )
        if profile_context:
            system += f"\n\n{profile_context}"
        if context_hint:
            system += f"\n\nКонтекст сессии: {context_hint}"
        if open_events_context:
            system += f"\n\n{open_events_context}"

        client = AsyncAnthropic(api_key=self.api_key)
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        iterations = 0
        final_text = ""

        while iterations < max_iterations:
            iterations += 1

            resp = await client.messages.create(
                model=self.analyst_model,
                max_tokens=2000,
                system=system,
                tools=TOOL_DESCRIPTIONS,  # type: ignore[arg-type]
                messages=messages,
            )

            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                for block in resp.content:
                    if hasattr(block, "text"):
                        final_text = block.text
                        break
                break

            # ── Handle tool calls ─────────────────────────────────────────────
            tool_results: list[dict[str, Any]] = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue

                tool_name = block.name
                tool_args = block.input or {}
                logger.info(
                    "agentic tool_use tenant=%s iter=%s tool=%s args=%s",
                    tenant_id, iterations, tool_name, tool_args,
                )

                fn = TOOL_REGISTRY.get(tool_name)
                if fn is None:
                    result_content = json.dumps(
                        {"error": f"Инструмент '{tool_name}' не найден"}, ensure_ascii=False
                    )
                    is_error = True
                else:
                    try:
                        result = await fn(db, tenant_id, **tool_args)
                        result_content = json.dumps(result, ensure_ascii=False, default=str)
                        is_error = False
                    except Exception as exc:
                        logger.warning("agentic tool error tool=%s: %s", tool_name, exc)
                        try:
                            await db.rollback()
                        except Exception:
                            pass
                        result_content = json.dumps(
                            {"error": f"Ошибка при выполнении {tool_name}: {exc}"},
                            ensure_ascii=False,
                        )
                        is_error = True

                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     result_content,
                    **({"is_error": True} if is_error else {}),
                })

            messages.append({"role": "user", "content": tool_results})

        else:
            # max_iterations exhausted
            logger.warning("agentic: max_iterations=%s reached tenant=%s", max_iterations, tenant_id)
            try:
                resp = await client.messages.create(
                    model=self.analyst_model,
                    max_tokens=800,
                    system=system,
                    messages=messages + [{
                        "role": "user",
                        "content": "Лимит итераций. Дай финальный ответ по собранным данным."
                    }],
                )
                for block in resp.content:
                    if hasattr(block, "text"):
                        final_text = block.text
                        break
            except Exception:
                final_text = "Превышен лимит итераций анализа."

        # ── Extract proposed_events (lightweight structured call) ─────────────
        proposed_events: list[dict[str, Any]] = []
        if final_text:
            try:
                ext_resp = await client.messages.create(
                    model=self.analyst_model,
                    max_tokens=800,
                    system=(
                        "Проанализируй ответ аналитика и извлеки список РЕКОМЕНДУЕМЫХ ДЕЙСТВИЙ "
                        "которые владелец мог бы превратить в задачи для отслеживания. "
                        "Верни СТРОГО JSON-массив (без markdown), каждый элемент:\n"
                        '{"title":"...","description":"...","entity_type":"chatter|model|shift|agency|null",'
                        '"entity_ref":"имя или null","trigger_metric":"метрика или null",'
                        '"trigger_value_before":число_или_null,"suggested_review_days":число_или_null,'
                        '"priority":"high|normal|low"}\n'
                        "Только реальные рекомендации из ответа. Если рекомендаций нет — верни []."
                    ),
                    messages=[{
                        "role": "user",
                        "content": f"Ответ аналитика:\n{final_text}"
                    }],
                )
                raw = ext_resp.content[0].text.strip() if ext_resp.content else "[]"
                # Strip markdown fence if present
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                    raw = raw.strip()
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    proposed_events = parsed
            except Exception as e:
                logger.debug("agentic: proposed_events extraction failed: %s", e)

        return {"answer": final_text, "proposed_events": proposed_events}

    async def answer_question(self, snapshot_text: str, question: str) -> str:
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured")

        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=self.api_key)
        resp = await client.messages.create(
            model=self.analyst_model,
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Данные агентства:\n{snapshot_text}\n\nВопрос: {question}"
                    ),
                }
            ],
        )
        return resp.content[0].text
