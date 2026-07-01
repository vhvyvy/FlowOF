"""Claude-based LLM analyst for agency data questions."""
from __future__ import annotations

import json
import logging
import os

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
