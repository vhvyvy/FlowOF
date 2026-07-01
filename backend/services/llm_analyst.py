"""Claude-based LLM analyst for agency data questions."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("flowof.llm_analyst")

SYSTEM_PROMPT = (
    "Ты AI-аналитик для OnlyFans-агентства. "
    "Отвечай кратко, по делу, на русском, с конкретными цифрами из предоставленных данных. "
    "КРИТИЧНО: используй ТОЛЬКО те цифры, что есть в данных. "
    "Если для ответа не хватает данных — прямо скажи, что таких данных нет, и НЕ придумывай числа. "
    "Где уместно — сравнивай с прошлым месяцем и давай короткий практический вывод."
)


class LLMAnalyst:
    def __init__(self) -> None:
        self.api_key       = os.getenv("ANTHROPIC_API_KEY", "")
        self.analyst_model = os.getenv("AI_ANALYST_MODEL", "claude-sonnet-4-6")

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
