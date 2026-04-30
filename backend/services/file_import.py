"""Разбор CSV/XLSX и преобразование строк в поля Transaction."""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

from import_contract import ColumnMapping
from notion_sync_service import _parse_date

_PREVIEW_ROWS = 15


def _suffix_from_name(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".xlsx") or lower.endswith(".xls"):
        return ".xlsx"
    if lower.endswith(".csv"):
        return ".csv"
    return ".csv"


def load_dataframe(path: str, original_name: str) -> pd.DataFrame:
    suf = _suffix_from_name(original_name)
    if suf == ".xlsx":
        return pd.read_excel(path, engine="openpyxl")
    return pd.read_csv(path, encoding="utf-8-sig", on_bad_lines="skip")


def dataframe_preview(df: pd.DataFrame) -> tuple[list[str], list[dict[str, Any]], int]:
    df = df.dropna(axis=1, how="all")
    columns = [str(c) for c in df.columns.tolist()]
    total = len(df.index)
    head = df.head(_PREVIEW_ROWS)
    preview_rows: list[dict[str, Any]] = []
    for _, row in head.iterrows():
        preview_rows.append({str(k): _cell_preview(v) for k, v in row.items()})
    return columns, preview_rows, total


def _cell_preview(v: Any) -> Any:
    if pd.isna(v):
        return None
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()  # type: ignore[no-any-return]
        except Exception:
            pass
    return v


def _parse_amount(val: Any) -> float | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    s = str(val).strip().replace("\u00a0", " ").replace(" ", "")
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s or s == "-":
        return None
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(Decimal(s))
    except (InvalidOperation, ValueError):
        try:
            return float(s)
        except ValueError:
            return None


def suggest_mapping(columns: list[str]) -> dict[str, str | None]:
    """Простая эвристика без LLM: ключевые слова по имени колонки."""
    out: dict[str, str | None] = {
        "date": None,
        "model": None,
        "chatter": None,
        "amount": None,
        "shift_id": None,
    }
    for c in columns:
        n = str(c).strip().lower()
        if out["date"] is None and any(
            x in n for x in ("date", "дата", "день", "time")
        ):
            out["date"] = c
        if out["amount"] is None and any(
            x in n for x in ("amount", "сумм", "sum", "total", "выруч", "доход")
        ):
            out["amount"] = c
        if out["model"] is None and any(x in n for x in ("model", "модел")):
            out["model"] = c
        if out["chatter"] is None and any(
            x in n for x in ("chatter", "чаттер", "chat")
        ):
            out["chatter"] = c
        if out["shift_id"] is None and any(x in n for x in ("shift", "смен")):
            out["shift_id"] = c
    return out


def build_transactions_from_dataframe(
    df: pd.DataFrame,
    mapping: ColumnMapping,
    tenant_id: int,
    batch_id: str,
) -> tuple[list[dict[str, Any]], int]:
    """
    Возвращает список dict полей для вставки Transaction и число пропущенных строк.
    """
    df = df.dropna(axis=1, how="all")
    m = mapping.to_dict()
    skipped = 0
    rows_out: list[dict[str, Any]] = []
    for i, (_, row) in enumerate(df.iterrows()):
        def cell(field: str) -> Any:
            col = m.get(field)
            if not col:
                return None
            target = str(col).strip()
            for c in df.columns:
                if str(c).strip() == target:
                    v = row[c]
                    return None if pd.isna(v) else v
            return None

        raw_date = cell("date")
        d = _parse_date(raw_date)
        if d is None:
            skipped += 1
            continue

        amt = _parse_amount(cell("amount"))
        if amt is None:
            skipped += 1
            continue

        model_v = cell("model")
        chatter_v = cell("chatter")
        model_s = None if model_v is None or (isinstance(model_v, float) and pd.isna(model_v)) else str(model_v).strip() or None
        chatter_s = None if chatter_v is None or (isinstance(chatter_v, float) and pd.isna(chatter_v)) else str(chatter_v).strip() or None

        shift_raw = cell("shift_id")
        shift_s = None if shift_raw is None or (isinstance(shift_raw, float) and pd.isna(shift_raw)) else str(shift_raw).strip() or None

        notion_id = f"excel:{batch_id}:{i}"
        rows_out.append(
            {
                "tenant_id": tenant_id,
                "notion_id": notion_id,
                "date": d,
                "model": model_s,
                "chatter": chatter_s,
                "amount": Decimal(str(amt)),
                "shift_id": shift_s,
                "shift_name": None,
                "notion_database_id": None,
                "month_source": "excel",
                "synced_at": datetime.utcnow(),
            }
        )
    return rows_out, skipped


def new_batch_id() -> str:
    return str(uuid.uuid4())
