"""
AI-импорт CSV/таблиц произвольной структуры в схему FlowOF.

Принимает CSV-контент (строка), отдаёт нормализованные транзакции:
    [{"date": "YYYY-MM-DD", "model": str|None, "chatter": str|None, "amount": float|None, "shift_id": str|None}, ...]

Под капотом — GPT-4o (полная нормализация) + GPT-4o-mini (детект маппинга колонок).
Большие таблицы дробятся на батчи, чтобы не упереться в контекст.

Принципы:
- temperature=0 — детерминизм;
- response_format json_object — гарантированный JSON;
- любой нечисловой мусор в amount чистится (символы валют, разделители);
- даты приводятся к ISO YYYY-MM-DD;
- строки-итоги/заголовки пропускаются;
- ничего НЕ придумывает: если поля нет — null.
"""
from __future__ import annotations

import io
import json
import logging
import re
from typing import Any

import pandas as pd
from openai import AsyncOpenAI

logger = logging.getLogger("flowof.ai_importer")

_RU_MONTHS = {
    "январ": ("январь", 1), "феврал": ("февраль", 2), "март": ("март", 3),
    "апрел": ("апрель", 4), "май": ("май", 5), "июн": ("июнь", 6),
    "июл": ("июль", 7), "август": ("август", 8), "сентябр": ("сентябрь", 9),
    "октябр": ("октябрь", 10), "ноябр": ("ноябрь", 11), "декабр": ("декабрь", 12),
}
_EN_MONTHS = {
    "jan": ("January", 1), "feb": ("February", 2), "mar": ("March", 3),
    "apr": ("April", 4), "may": ("May", 5), "jun": ("June", 6),
    "jul": ("July", 7), "aug": ("August", 8), "sep": ("September", 9),
    "oct": ("October", 10), "nov": ("November", 11), "dec": ("December", 12),
}


def _parse_period(text: str) -> tuple[str, int | None, int | None]:
    """
    Парсит строку типа 'Деньги Август 2025.xlsx', 'август', '08.2025' и т.п.
    Возвращает (month_name, month_num, year).
    """
    lo = text.lower()
    month_name = ""
    month_num: int | None = None
    for prefix, (name, num) in {**_RU_MONTHS, **_EN_MONTHS}.items():
        if prefix in lo:
            month_name = name
            month_num = num
            break
    year: int | None = None
    m = re.search(r"\b(20\d\d)\b", text)
    if m:
        year = int(m.group(1))
    else:
        m2 = re.search(r"(?<!\d)(2[0-9])(?!\d)", text)
        if m2:
            year = 2000 + int(m2.group(1))
    return month_name, month_num, year


class AIImporter:
    """GPT-4o нормализатор произвольного CSV → стандартная схема FlowOF."""

    SCHEMA = {
        "date": "дата транзакции или смены (YYYY-MM-DD)",
        "model": "имя или ник модели/исполнителя",
        "chatter": "имя или ник чаттера/менеджера",
        "amount": "сумма выручки в деньгах (число без символов валюты)",
        "shift_id": "номер или ID смены (опционально, может отсутствовать)",
    }

    BATCH_SIZE = 150
    CHUNK_LIMIT_FOR_SINGLE_CALL = 200

    def __init__(self, openai_key: str, *, model: str = "gpt-4o", mapping_model: str = "gpt-4o-mini"):
        if not openai_key or not openai_key.strip():
            raise ValueError("OPENAI_API_KEY пуст: AI-импорт невозможен")
        self.client = AsyncOpenAI(api_key=openai_key.strip())
        self.model = model
        self.mapping_model = mapping_model

    # ─────────────────────────── public API ───────────────────────────

    async def process(
        self,
        csv_content: str,
        filename: str = "",
        sheet_name: str = "",
    ) -> dict[str, Any]:
        """Основной вход. Возвращает dict с rows / total / mapping / warnings / detected_period."""
        if not csv_content or not csv_content.strip():
            return {"rows": [], "total": 0, "original_columns": [], "mapping": {}, "warnings": ["Пустой CSV"], "detected_period": ""}

        # Извлекаем мета-строки (совместимость со старым кодом, новый путь через params)
        period_hint = ""
        data_lines: list[str] = []
        for line in csv_content.splitlines():
            if line.startswith("# sheet:") and not sheet_name:
                sheet_name = line.removeprefix("# sheet:").strip()
            elif line.startswith("# period:"):
                period_hint = line.removeprefix("# period:").strip()
            elif line.startswith("# filename:") and not filename:
                filename = line.removeprefix("# filename:").strip()
            else:
                data_lines.append(line)
        csv_content = "\n".join(data_lines)

        # Определяем период из всех источников (приоритет: filename > sheet_name > period_hint)
        detected_period = self._resolve_detected_period(filename, sheet_name, period_hint)

        self._filename = filename
        self._sheet_name = sheet_name
        self._period_hint = period_hint
        self._detected_period = detected_period

        try:
            df = pd.read_csv(io.StringIO(csv_content))
        except Exception as e:
            logger.warning("CSV parse failed: %s", e)
            return {"rows": [], "total": 0, "original_columns": [], "mapping": {}, "warnings": [f"Не удалось прочитать CSV: {e}"], "detected_period": detected_period}

        df = df.dropna(axis=1, how="all")
        original_columns = [str(c) for c in df.columns.tolist()]
        total_rows = int(len(df))

        logger.info("AIImporter: %s строк, колонки: %s, period: %s", total_rows, original_columns, detected_period)

        if total_rows == 0:
            return {"rows": [], "total": 0, "original_columns": original_columns, "mapping": {}, "warnings": ["В таблице нет строк"], "detected_period": detected_period}

        if total_rows > self.CHUNK_LIMIT_FOR_SINGLE_CALL:
            rows = await self._process_in_batches(df)
        else:
            rows = await self._process_chunk(csv_content)

        mapping = await self._detect_mapping(original_columns)

        return {
            "rows": rows,
            "total": len(rows),
            "original_columns": original_columns,
            "mapping": mapping,
            "warnings": self._find_warnings(rows, total_rows),
            "detected_period": detected_period,
        }

    # ─────────────────────────── internals ───────────────────────────

    def _resolve_detected_period(self, filename: str, sheet_name: str, period_hint: str) -> str:
        """Определяет период (например 'Август 2025') из имени файла, листа или явного hint."""
        import os
        stem = os.path.splitext(filename)[0] if filename else ""
        for source in (stem, sheet_name, period_hint):
            if not source:
                continue
            month_name, month_num, year = _parse_period(source)
            if month_num or year:
                parts = []
                if month_name:
                    parts.append(month_name)
                if year:
                    parts.append(str(year))
                return " ".join(parts)
        return ""

    async def _process_chunk(self, csv_content: str) -> list[dict[str, Any]]:
        """Один вызов GPT-4o на CSV-чанк (до ~300 строк)."""
        lines = csv_content.split("\n")
        if len(lines) > 300:
            csv_content = "\n".join(lines[:300])

        prompt = self._build_normalize_prompt(csv_content)

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        return self._extract_rows(content)

    async def _process_in_batches(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        """Большая таблица — обрабатываем кусками."""
        all_rows: list[dict[str, Any]] = []
        for i in range(0, len(df), self.BATCH_SIZE):
            batch_df = df.iloc[i : i + self.BATCH_SIZE]
            batch_csv = batch_df.to_csv(index=False)
            try:
                batch_rows = await self._process_chunk(batch_csv)
            except Exception as e:
                logger.warning("batch %s failed: %s", i // self.BATCH_SIZE + 1, e)
                continue
            all_rows.extend(batch_rows)
            logger.info("AIImporter batch %s: получено %s строк", i // self.BATCH_SIZE + 1, len(batch_rows))
        return all_rows

    async def _detect_mapping(self, columns: list[str]) -> dict[str, str]:
        """GPT-4o-mini — короткая задача: вернуть колонки → поля FlowOF."""
        if not columns:
            return {}
        prompt = (
            f"Колонки таблицы: {columns}\n\n"
            "Наша схема: date, model, chatter, amount, shift_id\n\n"
            "Верни JSON маппинг (колонка_пользователя → наше_поле), напр.:\n"
            '{"Дата выхода": "date", "Ник модели": "model"}\n\n'
            "Только те колонки, которые ЯВНО соответствуют. Ничего не придумывай. ТОЛЬКО JSON."
        )
        try:
            response = await self.client.chat.completions.create(
                model=self.mapping_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items() if isinstance(v, str)}
        except Exception as e:
            logger.debug("mapping detect failed: %s", e)
        return {}

    def _build_normalize_prompt(self, csv_content: str) -> str:
        filename = getattr(self, "_filename", "")
        sheet_name = getattr(self, "_sheet_name", "")
        detected_period = getattr(self, "_detected_period", "")

        # Контекст модели из имени листа
        sheet_context = (
            f"\nИмя листа: «{sheet_name}». "
            "Если колонка model отсутствует — используй имя листа как значение model для всех строк."
            if sheet_name else ""
        )

        # Контекст дат — главная инструкция
        if filename or sheet_name or detected_period:
            file_ctx = f"«{filename}»" if filename else ""
            sheet_ctx = f"лист «{sheet_name}»" if sheet_name else ""
            period_ctx = f"период: «{detected_period}»" if detected_period else ""
            ctx_parts = ", ".join(p for p in [file_ctx, sheet_ctx, period_ctx] if p)

            date_instruction = (
                f"\nНАЗВАНИЕ ФАЙЛА/ЛИСТА: {ctx_parts}\n"
                "КРИТИЧЕСКИ ВАЖНО ПО ДАТАМ:\n"
                "Значения в колонке дат ЧАСТО содержат неправильный месяц/год — это дефолтное значение "
                "из Google Sheets или Excel, НЕ реальные даты.\n"
                "Реальный период определяй по названию файла и листа:\n"
            )
            if detected_period:
                _, month_num, year = _parse_period(detected_period)
                month_name = detected_period.split()[0] if detected_period else ""
                year_str = str(year) if year else "текущий"
                date_instruction += (
                    f"- Данные относятся к периоду: {detected_period}\n"
                    f"- Из ячейки даты бери ТОЛЬКО НОМЕР ДНЯ (1–31)\n"
                    f"- Итоговая дата: {year_str}-{'0'+str(month_num) if month_num and month_num < 10 else month_num or 'MM'}-DD\n"
                    f"- Например: если в ячейке '15' или '15.12.2024' или '2024-12-15' → итог '{ year_str }-{'0'+str(month_num) if month_num and month_num < 10 else str(month_num) if month_num else 'MM'}-15'\n"
                )
            else:
                date_instruction += (
                    "- Определи реальный месяц и год из названия файла/листа\n"
                    "- Из ячейки бери только номер дня\n"
                    "- Если год нигде не указан — используй 2025\n"
                )
        else:
            date_instruction = ""

        return (
            "Ты помощник по импорту данных для FlowOF — системы аналитики OF-агентств.\n\n"
            "Вот CSV таблица агентства:\n```\n"
            f"{csv_content}\n```\n\n"
            f"{sheet_context}\n"
            f"{date_instruction}\n"
            "Наша стандартная схема транзакций:\n"
            f"{json.dumps(self.SCHEMA, ensure_ascii=False, indent=2)}\n\n"
            "Задача:\n"
            "1. Найди колонки, соответствующие схеме (названия могут быть на любом языке).\n"
            "2. Преобразуй КАЖДУЮ строку данных в наш формат.\n"
            '3. Очисти суммы: убери $, руб, €, пробелы, запятые → оставь только число '
            '(например "1 500,50 $" → 1500.50).\n'
            "4. Нормализуй даты → YYYY-MM-DD используя правила выше.\n"
            "5. Строки-итоги/заголовки/пустые — пропусти.\n"
            "6. Верни ТОЛЬКО валидный JSON:\n"
            '{"rows": [\n'
            '  {"date": "2025-08-01", "model": "Anna", "chatter": "Max", "amount": 150.0, "shift_id": "1"},\n'
            "  ...\n"
            "]}\n\n"
            "Если поле не найдено — ставь null. Не придумывай данные, которых нет в таблице."
        )

    @staticmethod
    def _extract_rows(content: str) -> list[dict[str, Any]]:
        """Достать массив rows из ответа GPT, какой бы формат он ни вернул."""
        try:
            parsed = json.loads(content)
        except Exception as e:
            logger.warning("GPT returned non-JSON: %s", e)
            return []
        if isinstance(parsed, list):
            return [r for r in parsed if isinstance(r, dict)]
        if isinstance(parsed, dict):
            for key in ("rows", "data", "transactions", "items"):
                v = parsed.get(key)
                if isinstance(v, list):
                    return [r for r in v if isinstance(r, dict)]
            for v in parsed.values():
                if isinstance(v, list):
                    return [r for r in v if isinstance(r, dict)]
        return []

    @staticmethod
    def _find_warnings(rows: list[dict[str, Any]], original_count: int) -> list[str]:
        warnings: list[str] = []
        imported = len(rows)
        if original_count > 0 and imported < original_count * 0.5:
            warnings.append(
                f"Распознано только {imported} из {original_count} строк. "
                "Возможно таблица содержит нестандартный формат."
            )
        no_amount = sum(1 for r in rows if not r.get("amount"))
        if no_amount > 0 and imported > 0:
            warnings.append(f"{no_amount} строк без суммы — проверьте колонку с выручкой.")
        no_model = sum(1 for r in rows if not r.get("model"))
        if imported > 0 and no_model > imported * 0.3:
            warnings.append(f"У {no_model} строк не определена модель.")
        return warnings
