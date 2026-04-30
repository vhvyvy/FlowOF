"""
Контракт импорта: поля FlowOF ↔ колонки файла, credentials для tenant_sources.

Один активный источник типа excel|notion на тенанта для MVP импорта файла;
таблица tenant_sources допускает несколько строк — при confirm деактивируем предыдущие excel.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# Поля целевой строки transactions (импорт файла)
FLOWOF_TRANSACTION_FIELDS: tuple[str, ...] = (
    "date",
    "model",
    "chatter",
    "amount",
    "shift_id",
)

SourceTypeLiteral = Literal["notion", "google_sheets", "excel", "manual"]


class ColumnMapping(BaseModel):
    """Маппинг: поле FlowOF → имя колонки в файле/таблице."""

    date: Optional[str] = None
    model: Optional[str] = None
    chatter: Optional[str] = None
    amount: Optional[str] = None
    shift_id: Optional[str] = None

    def to_dict(self) -> dict[str, Optional[str]]:
        return {
            "date": self.date,
            "model": self.model,
            "chatter": self.chatter,
            "amount": self.amount,
            "shift_id": self.shift_id,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> ColumnMapping:
        if isinstance(raw, dict):
            return cls.model_validate({k: raw.get(k) for k in FLOWOF_TRANSACTION_FIELDS})
        return cls()


class NotionCredentialsPlain(BaseModel):
    """Токен и базы Notion (до шифрования в БД)."""

    token: str = Field(..., min_length=10)
    database_ids: list[str] = Field(default_factory=list)


class ExcelImportState(BaseModel):
    """Состояние последнего загрузочного импорта (в mapping_config)."""

    upload_batch_id: Optional[str] = None
    last_rows_imported: int = 0


class TenantSourceMappingConfig(BaseModel):
    """Содержимое tenant_sources.mapping_config JSON."""

    column_mapping: ColumnMapping = Field(default_factory=ColumnMapping)
    excel: Optional[ExcelImportState] = None
    version: int = 1
