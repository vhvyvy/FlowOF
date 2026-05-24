"""Загрузка CSV/XLSX + Google Sheets (через AI), превью, подтверждение маппинга и импорт в transactions."""
from __future__ import annotations

import logging
import os
import re
import hashlib
from datetime import date, datetime
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, get_db
from dependencies import get_current_tenant
from import_contract import ColumnMapping, ExcelImportState, TenantSourceMappingConfig
from models import SyncLog, Tenant, TenantSource, Transaction
from services.ai_importer import AIImporter
from services.credentials_crypto import encrypt_credentials_blob
from services.file_import import (
    build_transactions_from_dataframe,
    dataframe_preview,
    load_dataframe,
    new_batch_id,
    suggest_mapping,
)
from services.google_sheets_service import GoogleAuthError, GoogleSheetsService
from services.google_unify import (
    get_google_access_token,
    save_selected_spreadsheet,
)
from services.upload_store import get_upload_path, pop_upload, save_upload

logger = logging.getLogger("flowof.import")

router = APIRouter(prefix="/api/v1/import", tags=["import"])


class ImportUploadResponse(BaseModel):
    upload_id: str
    filename: str
    columns_detected: list[str]
    preview_rows: list[dict]
    total_rows: int
    suggested_mapping: dict[str, str | None]


class ImportConfirmRequest(BaseModel):
    upload_id: str
    mapping: ColumnMapping
    original_filename: str = Field("", description="Имя файла с клиента для выбора парсера")


class ImportConfirmResponse(BaseModel):
    rows_imported: int
    rows_skipped: int
    sync_log_id: int


@router.post("/upload", response_model=ImportUploadResponse)
async def post_import_upload(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_current_tenant),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Файл без имени")
    raw = await file.read()
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Файл больше 15 МБ")
    suffix = os.path.splitext(file.filename)[1] or ".csv"
    upload_id = save_upload(tenant.id, raw, suffix)
    path = get_upload_path(upload_id, tenant.id)
    if not path:
        raise HTTPException(status_code=500, detail="Не удалось сохранить загрузку")

    try:
        df = load_dataframe(str(path), file.filename)
        cols, preview, total = dataframe_preview(df)
    except Exception as e:
        logger.warning("parse upload failed: %s", e)
        raise HTTPException(
            status_code=400,
            detail="Не удалось прочитать таблицу. Проверьте формат CSV или XLSX.",
        ) from e

    sug = suggest_mapping(cols)
    return ImportUploadResponse(
        upload_id=upload_id,
        filename=file.filename,
        columns_detected=cols,
        preview_rows=preview,
        total_rows=total,
        suggested_mapping=sug,
    )


@router.post("/confirm", response_model=ImportConfirmResponse)
async def post_import_confirm(
    body: ImportConfirmRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    path = pop_upload(body.upload_id, tenant.id)
    if not path or not path.exists():
        raise HTTPException(
            status_code=400,
            detail="Сессия загрузки истекла или файл не найден. Загрузите файл снова.",
        )

    name = body.original_filename or path.name
    try:
        df = load_dataframe(str(path), name)
    except Exception as e:
        path.unlink(missing_ok=True)
        logger.warning("confirm re-parse failed: %s", e)
        raise HTTPException(status_code=400, detail="Не удалось прочитать файл") from e
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    m = body.mapping
    if not m.date or not m.amount:
        raise HTTPException(
            status_code=400,
            detail="Укажите маппинг для даты и суммы",
        )

    batch_id = new_batch_id()
    rows_data, skipped = build_transactions_from_dataframe(df, m, tenant.id, batch_id)
    imported = len(rows_data)
    fin = datetime.utcnow()
    started = datetime.utcnow()

    try:
        await db.execute(
            delete(Transaction).where(
                Transaction.tenant_id == tenant.id,
                Transaction.notion_id.like("excel:%"),
            )
        )

        for tr in rows_data:
            db.add(Transaction(**tr))

        await db.execute(
            update(Tenant)
            .where(Tenant.id == tenant.id)
            .values(last_sync_at=fin)
        )

        await db.execute(
            update(TenantSource)
            .where(
                TenantSource.tenant_id == tenant.id,
                TenantSource.source_type == "excel",
            )
            .values(active=False)
        )

        cfg = TenantSourceMappingConfig(
            column_mapping=m,
            excel=ExcelImportState(
                upload_batch_id=batch_id,
                last_rows_imported=imported,
            ),
        )
        cred = encrypt_credentials_blob({"kind": "excel", "last_filename": name[:500]})
        db.add(
            TenantSource(
                tenant_id=tenant.id,
                source_type="excel",
                credentials=cred,
                mapping_config=cfg.model_dump(mode="json"),
                active=True,
            )
        )

        log_row = SyncLog(
            tenant_id=tenant.id,
            source_type="excel",
            started_at=started,
            finished_at=fin,
            status="success",
            rows_imported=imported,
            rows_skipped=skipped,
        )
        db.add(log_row)
        await db.flush()
        log_id = log_row.id
    except Exception as e:
        await db.rollback()
        logger.exception("import confirm failed tenant=%s", tenant.id)
        async with AsyncSessionLocal() as s:
            s.add(
                SyncLog(
                    tenant_id=tenant.id,
                    source_type="excel",
                    started_at=started,
                    finished_at=datetime.utcnow(),
                    status="failed",
                    rows_imported=0,
                    rows_skipped=skipped,
                    error_message=str(e)[:2000],
                )
            )
            await s.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка записи в базу",
        ) from e

    return ImportConfirmResponse(
        rows_imported=imported,
        rows_skipped=skipped,
        sync_log_id=log_id,
    )


class SuggestRequest(BaseModel):
    columns: list[str]


@router.post("/suggest-mapping")
async def post_suggest_mapping(body: SuggestRequest):
    return {"mapping": suggest_mapping(body.columns)}


# ─────────────────────────── Google Sheets + AI ───────────────────────────


class GoogleSheetImportRequest(BaseModel):
    spreadsheet_id: str = Field(..., min_length=10)
    sheet_name: str = Field(..., min_length=1)


class GoogleSheetConfirmRequest(GoogleSheetImportRequest):
    """confirm: можно прислать уже подсчитанные AI-rows (preview), чтобы не звать GPT повторно."""

    rows: list[dict[str, Any]] | None = Field(
        default=None,
        description="Готовые rows от /preview. Если None — confirm заново вызовет AI на полной таблице.",
    )


class GoogleSheetPreviewResponse(BaseModel):
    rows: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Полный набор нормализованных строк (используется фронтом для /confirm).",
    )
    preview: list[dict[str, Any]]
    total_rows: int
    columns_detected: list[str]
    mapping_used: dict[str, str]
    warnings: list[str]


class GoogleSheetConfirmResponse(BaseModel):
    success: bool
    rows_imported: int
    rows_skipped: int
    sync_log_id: int


def _gsheet_dedupe_prefix(spreadsheet_id: str, sheet_name: str) -> str:
    """
    Стабильный (но короткий) префикс notion_id для строки конкретного (spreadsheet, sheet).
    Позволяет идемпотентно перезаливать импорт ИЗ ЭТОГО листа, не трогая другие google-импорты тенанта.
    """
    raw = f"{spreadsheet_id.strip()}|{sheet_name.strip()}".encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()[:12]  # 48 бит — для одного tenant пересечений практически нет
    return f"gsheet:{digest}:"


def _resolve_openai_key(tenant: Tenant) -> str:
    key = (tenant.openai_key or "").strip() or (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY не настроен — AI-импорт недоступен",
        )
    return key


def _coerce_amount(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    # GPT уже почистил, но на всякий случай — снимем мусор.
    cleaned = (
        s.replace("$", "")
        .replace("€", "")
        .replace("₽", "")
        .replace("руб", "")
        .replace(" ", "")
        .replace("\u00a0", "")
        .replace(",", ".")
    )
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def _coerce_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        ts = pd.to_datetime(value, errors="coerce", utc=False)
    except Exception:
        return None
    if ts is None or pd.isna(ts):
        return None
    return ts.to_pydatetime().date()


async def _fetch_csv_from_google(
    db: AsyncSession, tenant: Tenant, spreadsheet_id: str, sheet_name: str
) -> str:
    try:
        access_token = await get_google_access_token(db, tenant.id)
    except GoogleAuthError as e:
        raise HTTPException(status_code=400, detail=f"Google: {e}") from e

    svc = GoogleSheetsService(access_token)
    try:
        csv_content = await svc.download_as_csv(spreadsheet_id, sheet_name)
    except GoogleAuthError as e:
        raise HTTPException(status_code=401, detail=f"Google авторизация: {e}") from e
    except Exception as e:
        logger.warning("download_as_csv failed tenant=%s sid=%s: %s", tenant.id, spreadsheet_id, e)
        raise HTTPException(status_code=502, detail="Не удалось скачать таблицу из Google") from e

    if not csv_content.strip():
        raise HTTPException(status_code=400, detail="Лист пустой — нечего импортировать")
    return csv_content


@router.post("/google-sheets/preview", response_model=GoogleSheetPreviewResponse)
async def preview_google_sheets(
    body: GoogleSheetImportRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Скачать таблицу, прогнать через AI и вернуть полный результат (preview + полный rows для confirm)."""
    openai_key = _resolve_openai_key(tenant)
    csv_content = await _fetch_csv_from_google(db, tenant, body.spreadsheet_id, body.sheet_name)

    importer = AIImporter(openai_key=openai_key)
    try:
        result = await importer.process(csv_content)
    except Exception as e:
        logger.exception("AI importer failed tenant=%s", tenant.id)
        raise HTTPException(status_code=500, detail=f"AI-обработка не удалась: {e}") from e

    rows = result.get("rows") or []
    if not rows:
        # AI вообще ничего не распознал — это не «0 импортировано», а ошибка структуры файла.
        raise HTTPException(
            status_code=422,
            detail=(
                "AI не распознал ни одной транзакции в выбранном листе. "
                "Проверьте, что в листе есть столбцы с датой и суммой, а строки содержат значения."
            ),
        )

    # Запоминаем выбор пользователя, но не активируем источник (это сделает confirm).
    try:
        await save_selected_spreadsheet(
            db,
            tenant.id,
            spreadsheet_id=body.spreadsheet_id,
            sheet_name=body.sheet_name,
            activate=False,
        )
    except GoogleAuthError as e:
        logger.warning("save_selected_spreadsheet failed tenant=%s: %s", tenant.id, e)

    return GoogleSheetPreviewResponse(
        rows=rows,
        preview=rows[:10],
        total_rows=result["total"],
        columns_detected=result["original_columns"],
        mapping_used=result["mapping"],
        warnings=result["warnings"],
    )


@router.post("/google-sheets/confirm", response_model=GoogleSheetConfirmResponse)
async def confirm_google_sheets_import(
    body: GoogleSheetConfirmRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Подтверждение AI-импорта.

    Если фронт передал `rows` (из ответа /preview) — используем их (нет повторного GPT-вызова).
    Иначе (например, фоновый sync без UI) — заново скачиваем таблицу и нормализуем через AI.
    Чистим только записи ЭТОГО (spreadsheet, sheet), чтобы не задеть другие google-источники тенанта.
    """
    started = datetime.utcnow()

    rows: list[dict[str, Any]]
    if body.rows is not None:
        rows = [r for r in body.rows if isinstance(r, dict)]
    else:
        openai_key = _resolve_openai_key(tenant)
        csv_content = await _fetch_csv_from_google(db, tenant, body.spreadsheet_id, body.sheet_name)
        importer = AIImporter(openai_key=openai_key)
        try:
            result = await importer.process(csv_content)
        except Exception as e:
            logger.exception("AI importer failed tenant=%s", tenant.id)
            raise HTTPException(status_code=500, detail=f"AI-обработка не удалась: {e}") from e
        rows = result.get("rows") or []

    if not rows:
        raise HTTPException(
            status_code=422,
            detail="Нечего импортировать — AI вернул пустой результат.",
        )

    batch_id = new_batch_id()
    notion_id_prefix = _gsheet_dedupe_prefix(body.spreadsheet_id, body.sheet_name)
    imported = 0
    skipped = 0

    try:
        # Удаляем строки ТОЛЬКО этого листа.
        #
        # Новый формат (после sha1-фикса): gsheet:{12hex}:{batch}:{idx}
        #   → совпадает с LIKE 'gsheet:{notion_id_prefix}%'
        #
        # Старый формат (первые импорты до фикса): gsheet:{uuid}:{idx}
        #   uuid начинается с 8 hex-символов, затем дефис (xxxxxxxx-...).
        #   Паттерн "gsheet:____________:%" (12 символов) НЕ совпадает с UUID-стилем
        #   (там 13-й символ — буква/цифра, не ":"), поэтому добавляем отдельное условие:
        #   удаляем gsheet:-строки, которые НЕ соответствуют паттерну нового формата —
        #   это «осиротевшие» строки от самого первого импорта (до sha1-фикса).
        await db.execute(
            delete(Transaction).where(
                Transaction.tenant_id == tenant.id,
                Transaction.notion_id.like(f"{notion_id_prefix}%"),
            )
        )
        # Совместимость: чистим строки старого формата (gsheet:{uuid}:{idx})
        # которые не имеют sha1-префикса. Их нельзя привязать к конкретному листу,
        # поэтому при ЛЮБОМ импорте убираем их раз и навсегда.
        await db.execute(
            delete(Transaction).where(
                Transaction.tenant_id == tenant.id,
                Transaction.notion_id.like("gsheet:%"),
                ~Transaction.notion_id.like("gsheet:____________:%"),
            )
        )

        for idx, row in enumerate(rows):
            try:
                amount = _coerce_amount(row.get("amount"))
                if amount is None:
                    skipped += 1
                    continue
                tx_date = _coerce_date(row.get("date"))
                shift_val = row.get("shift_id")
                shift_str = str(shift_val).strip() if shift_val not in (None, "") else None
                db.add(
                    Transaction(
                        tenant_id=tenant.id,
                        date=tx_date,
                        model=(str(row.get("model")).strip() if row.get("model") else None),
                        chatter=(str(row.get("chatter")).strip() if row.get("chatter") else None),
                        amount=amount,
                        shift_id=shift_str,
                        notion_id=f"{notion_id_prefix}{batch_id}:{idx}",
                    )
                )
                imported += 1
            except Exception as e:
                logger.debug("row %s skipped: %s", idx, e)
                skipped += 1

        finished = datetime.utcnow()

        await db.execute(
            update(Tenant).where(Tenant.id == tenant.id).values(last_sync_at=finished)
        )

        # Активируем google_sheets источник, отметим выбор.
        await save_selected_spreadsheet(
            db,
            tenant.id,
            spreadsheet_id=body.spreadsheet_id,
            sheet_name=body.sheet_name,
            activate=True,
        )

        log_row = SyncLog(
            tenant_id=tenant.id,
            source_type="google_sheets",
            started_at=started,
            finished_at=finished,
            status="success",
            rows_imported=imported,
            rows_skipped=skipped,
        )
        db.add(log_row)
        await db.flush()
        await db.commit()
        log_id = log_row.id
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.exception("google sheets import failed tenant=%s", tenant.id)
        async with AsyncSessionLocal() as s:
            s.add(
                SyncLog(
                    tenant_id=tenant.id,
                    source_type="google_sheets",
                    started_at=started,
                    finished_at=datetime.utcnow(),
                    status="failed",
                    rows_imported=0,
                    rows_skipped=skipped,
                    error_message=str(e)[:2000],
                )
            )
            await s.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка записи в базу",
        ) from e

    return GoogleSheetConfirmResponse(
        success=True,
        rows_imported=imported,
        rows_skipped=skipped,
        sync_log_id=log_id,
    )


# ─────────────────────────── AI File import (xlsx / csv) ─────────────────────


class FilePreviewResponse(BaseModel):
    rows: list[dict]
    preview: list[dict]
    total_rows: int
    columns_detected: list[str]
    mapping_used: dict
    warnings: list[str]
    detected_period: str = ""


class FileDetectSheetsResponse(BaseModel):
    upload_id: str
    filename: str
    sheets: list[str]


class FileConfirmRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(..., description="Строки из /file/preview — повторный GPT не нужен")
    filename: str = Field("", description="Имя файла — для изоляции при повторном импорте")
    sheet_name: str = Field("", description="Имя листа — для изоляции при повторном импорте")
    override_month: int | None = Field(None, description="Принудительный месяц (1-12) — замещает AI-даты")
    override_year: int | None = Field(None, description="Принудительный год — замещает AI-даты")


class FileConfirmResponse(BaseModel):
    success: bool = True
    rows_imported: int
    rows_skipped: int


_MONTHS_RU = {
    "январ": "январь", "феврал": "февраль", "март": "март",
    "апрел": "апрель", "май": "май", "июн": "июнь",
    "июл": "июль", "август": "август", "сентябр": "сентябрь",
    "октябр": "октябрь", "ноябр": "ноябрь", "декабр": "декабрь",
}
_MONTHS_EN = {
    "january": "january", "february": "february", "march": "march",
    "april": "april", "may": "may", "june": "june",
    "july": "july", "august": "august", "september": "september",
    "october": "october", "november": "november", "december": "december",
}


def _find_month_in_text(text: str) -> str:
    """Ищет название месяца (рус/англ) в произвольной строке. Возвращает '' если не найдено."""
    lo = text.lower()
    for prefix, name in _MONTHS_RU.items():
        if prefix in lo:
            return name
    for prefix, name in _MONTHS_EN.items():
        if prefix in lo:
            return name
    return ""


def _find_year_in_text(text: str) -> str:
    """Ищет год формата 20XX или короткий 2X (->20XX). Возвращает '' если не найдено."""
    m = re.search(r'\b(20\d\d)\b', text)
    if m:
        return m.group(1)
    # Короткий год: '25', '24' и т.п. не окружённый цифрами
    m2 = re.search(r'(?<!\d)(2[0-9])(?!\d)', text)
    if m2:
        return f"20{m2.group(1)}"
    return ""


def _extract_period_from_filename(filename: str) -> str:
    """Извлекает период (месяц + год) из имени файла или листа."""
    stem = os.path.splitext(filename or "")[0]
    month = _find_month_in_text(stem)
    year = _find_year_in_text(stem)
    if month or year:
        return f"{month} {year}".strip()
    return ""


def _extract_period_hint(raw: bytes, filename: str, sheet_kw: dict) -> str:
    """
    Читает первые 3 строки Excel, ищет ячейку с месяцем и/или годом.
    Возвращает строку-подсказку или '' если не найдено.
    """
    import io as _io
    try:
        df_peek = pd.read_excel(_io.BytesIO(raw), header=None, nrows=3, **sheet_kw)
        for row_idx in range(min(3, len(df_peek))):
            for col_idx in range(min(5, len(df_peek.columns))):
                cell = str(df_peek.iloc[row_idx, col_idx]).strip()
                month = _find_month_in_text(cell)
                year = _find_year_in_text(cell)
                if (month or year) and len(cell) < 60:
                    return cell
    except Exception:
        pass
    return ""


_DATE_COL_KEYWORDS = {"дата", "date", "день", "day", "data", "дата транзакции", "transaction date"}


def _parse_period_month_year(period_hint: str) -> tuple[int | None, int | None]:
    """Извлекает (month, year) из period_hint типа 'август 2025' или 'август'."""
    _RU_MONTH_MAP = {
        "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "май": 5, "июн": 6,
        "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
    }
    _EN_MONTH_MAP = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    lo = period_hint.lower()
    month: int | None = None
    for prefix, num in {**_RU_MONTH_MAP, **_EN_MONTH_MAP}.items():
        if prefix in lo:
            month = num
            break
    year_str = _find_year_in_text(period_hint)
    year = int(year_str) if year_str else None
    return month, year


def _normalize_date_column(df: "pd.DataFrame", period_hint: str) -> "pd.DataFrame":
    """
    Принудительно парсит дату в date-колонке через pandas с dayfirst=True,
    выводит чистый ISO YYYY-MM-DD. Если в дате нет года/месяца — добирает из period_hint.
    """
    period_month, period_year = _parse_period_month_year(period_hint) if period_hint else (None, None)

    for col in list(df.columns):
        col_lo = str(col).lower().strip()
        if not any(kw in col_lo for kw in _DATE_COL_KEYWORDS):
            continue
        series = df[col].copy()
        # Парсим строки / числа / datetime с dayfirst=True
        parsed = pd.to_datetime(series, dayfirst=True, errors="coerce", utc=False)
        valid_ratio = parsed.notna().sum() / max(len(series), 1)

        if valid_ratio >= 0.4:
            # Для строк где распознали только день (целые 1..31) — добавляем месяц/год из period_hint
            if period_month and period_year:
                for idx in df.index:
                    if pd.isna(parsed[idx]):
                        raw_val = str(series[idx]).strip()
                        try:
                            day = int(float(raw_val))
                            if 1 <= day <= 31:
                                parsed[idx] = pd.Timestamp(year=period_year, month=period_month, day=day)
                        except Exception:
                            pass

            # Записываем чистый ISO YYYY-MM-DD в колонку
            df[col] = parsed.dt.strftime("%Y-%m-%d").where(parsed.notna(), series)
    return df


def _df_to_csv(raw: bytes, filename: str, sheet_name: str | None = None) -> str:
    """Читает xlsx/xls/csv и возвращает строку CSV для AIImporter."""
    import io as _io

    ext = os.path.splitext(filename or "")[1].lower()
    if ext in (".xlsx", ".xls"):
        sheet_kw: dict = {"sheet_name": sheet_name} if sheet_name else {}

        # Ищем period-hint: сначала в Excel-строках, потом в имени файла/листа
        period_hint = _extract_period_hint(raw, filename, sheet_kw)
        if not period_hint:
            period_hint = _extract_period_from_filename(filename)
        if not period_hint and sheet_name:
            period_hint = _extract_period_from_filename(sheet_name)

        def _read(header: int) -> "pd.DataFrame":
            return pd.read_excel(_io.BytesIO(raw), header=header, **sheet_kw)

        df = _read(0)

        # Если заголовок «плохой» (много Unnamed: X) — пробуем header=1, 2
        # Это случается когда первая строка — объединённая ячейка-заголовок («Июль 2024» и т.п.)
        def _unnamed_ratio(frame: "pd.DataFrame") -> float:
            if not len(frame.columns):
                return 1.0
            bad = sum(1 for c in frame.columns if str(c).startswith("Unnamed:"))
            return bad / len(frame.columns)

        for alt_header in (1, 2):
            if _unnamed_ratio(df) < 0.4:
                break
            try:
                df_alt = _read(alt_header)
                if _unnamed_ratio(df_alt) < _unnamed_ratio(df):
                    df = df_alt
            except Exception:
                break

    else:
        period_hint = _extract_period_from_filename(filename)
        # CSV — пробуем несколько кодировок
        for enc in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
            try:
                df = pd.read_csv(_io.BytesIO(raw), encoding=enc)
                break
            except Exception:
                continue
        else:
            raise ValueError("Не удалось прочитать CSV ни в одной кодировке")

    df = df.dropna(how="all").dropna(axis=1, how="all")
    # Принудительно парсим дату-колонку и приводим к ISO формату (dayfirst=True для DD.MM.YY)
    df = _normalize_date_column(df, period_hint)
    csv_out = df.to_csv(index=False)

    # Мета-комментарии для AI: имя файла (всегда) + период если найден
    # AI использует их для корректного определения дат и модели
    meta = f"# filename: {filename}\n"
    if period_hint:
        meta += f"# period: {period_hint}\n"
    return meta + csv_out


def _get_excel_sheets(raw: bytes, filename: str) -> list[str]:
    """Возвращает список листов xlsx/xls. Для CSV — пустой список."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in (".xlsx", ".xls"):
        return []
    import io as _io
    try:
        xl = pd.ExcelFile(_io.BytesIO(raw))
        return xl.sheet_names  # type: ignore[return-value]
    except Exception:
        return []


@router.post("/file/detect-sheets", response_model=FileDetectSheetsResponse)
async def detect_file_sheets(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Сохранить файл и вернуть список листов (для xlsx с несколькими листами)."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Файл без имени")
    raw = await file.read()
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Файл больше 15 МБ")

    suffix = os.path.splitext(file.filename)[1] or ".bin"
    upload_id = save_upload(tenant.id, raw, suffix)
    sheets = _get_excel_sheets(raw, file.filename)

    return FileDetectSheetsResponse(
        upload_id=upload_id,
        filename=file.filename,
        sheets=sheets,
    )


@router.post("/file/preview", response_model=FilePreviewResponse)
async def preview_file_import(
    upload_id: str = Form(...),
    sheet_name: str = Form(""),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Прочитать сохранённый файл, прогнать через AI, вернуть превью."""
    path = get_upload_path(upload_id, tenant.id)
    if not path or not path.exists():
        raise HTTPException(status_code=400, detail="Сессия загрузки истекла. Загрузите файл снова.")

    raw = path.read_bytes()
    filename = path.name
    chosen_sheet = sheet_name.strip() if sheet_name else None

    try:
        csv_content = _df_to_csv(raw, filename, chosen_sheet)
    except Exception as e:
        logger.warning("file/preview parse failed: %s", e)
        raise HTTPException(status_code=400, detail=f"Не удалось прочитать файл: {e}") from e

    openai_key = _resolve_openai_key(tenant)
    importer = AIImporter(openai_key=openai_key)
    try:
        result = await importer.process(
            csv_content,
            filename=filename,
            sheet_name=chosen_sheet or "",
        )
    except Exception as e:
        logger.exception("AI importer failed tenant=%s", tenant.id)
        raise HTTPException(status_code=500, detail=f"AI-обработка не удалась: {e}") from e

    rows = result.get("rows") or []
    if not rows:
        raise HTTPException(
            status_code=422,
            detail=(
                "AI не распознал ни одной транзакции. "
                "Проверьте, что выбранный лист содержит столбцы с датой и суммой."
            ),
        )

    return FilePreviewResponse(
        rows=rows,
        preview=rows[:10],
        total_rows=result["total"],
        columns_detected=result["original_columns"],
        mapping_used=result["mapping"],
        warnings=result["warnings"],
        detected_period=result.get("detected_period", ""),
    )


def _file_dedupe_prefix(filename: str, sheet_name: str) -> str:
    """
    Стабильный sha1-префикс для строк конкретного листа.
    Дедупликация только по имени листа (не по имени файла) — это гарантирует
    что повторный импорт листа 'SalesEvelyne' из любого файла заменит старые
    данные этого листа, а не добавит рядом.
    Если лист не задан — fallback на имя файла.
    """
    key = sheet_name.strip() if sheet_name.strip() else filename.strip()
    raw = key.encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()[:12]
    return f"file_ai:{digest}:"


def _reapply_period(rows: list[dict], month: int, year: int) -> list[dict]:
    """
    Заменяет месяц и год в датах всех строк.
    Используется когда пользователь указал override_month/override_year.
    День берётся из оригинальной даты, месяц и год заменяются.
    """
    import calendar
    result = []
    for row in rows:
        row = dict(row)
        d = row.get("date")
        if d:
            try:
                parsed = _coerce_date(d)
                if parsed:
                    # Не выходим за пределы месяца (28/30/31)
                    max_day = calendar.monthrange(year, month)[1]
                    day = min(parsed.day, max_day)
                    from datetime import date as _date
                    row["date"] = _date(year, month, day).isoformat()
            except Exception:
                pass
        result.append(row)
    return result


@router.post("/file/confirm", response_model=FileConfirmResponse)
async def confirm_file_import(
    body: FileConfirmRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Сохранить AI-обработанные строки из /file/preview в БД."""
    rows = [r for r in body.rows if isinstance(r, dict)]
    if not rows:
        raise HTTPException(status_code=422, detail="Нечего импортировать")

    # Применяем override периода если пользователь его скорректировал
    if body.override_month and body.override_year:
        rows = _reapply_period(rows, body.override_month, body.override_year)

    batch_id = new_batch_id()
    # Стабильный префикс по sheet_name — любой файл с тем же листом заменяет старые данные
    prefix = _file_dedupe_prefix(body.filename, body.sheet_name)
    imported = 0
    skipped = 0

    try:
        # Удаляем строки этого листа (текущий формат sha1 по sheet_name)
        await db.execute(
            delete(Transaction).where(
                Transaction.tenant_id == tenant.id,
                Transaction.notion_id.like(f"{prefix}%"),
            )
        )
        # Совместимость: чистим старые строки формата file_ai:{uuid}:{idx} (без sha1-prefix)
        await db.execute(
            delete(Transaction).where(
                Transaction.tenant_id == tenant.id,
                Transaction.notion_id.like("file_ai:%"),
                ~Transaction.notion_id.like("file_ai:____________:%"),
            )
        )

        for idx, row in enumerate(rows):
            try:
                amount = _coerce_amount(row.get("amount"))
                if amount is None:
                    skipped += 1
                    continue
                tx_date = _coerce_date(row.get("date"))
                shift_val = row.get("shift_id")
                shift_str = str(shift_val).strip() if shift_val not in (None, "") else None
                db.add(
                    Transaction(
                        tenant_id=tenant.id,
                        date=tx_date,
                        model=(str(row.get("model")).strip() if row.get("model") else None),
                        chatter=(str(row.get("chatter")).strip() if row.get("chatter") else None),
                        amount=amount,
                        shift_id=shift_str,
                        notion_id=f"{prefix}{batch_id}:{idx}",
                    )
                )
                imported += 1
            except Exception as e:
                logger.debug("file_ai row %s skipped: %s", idx, e)
                skipped += 1

        fin = datetime.utcnow()
        await db.execute(
            update(Tenant).where(Tenant.id == tenant.id).values(last_sync_at=fin)
        )
        await db.commit()

    except Exception as e:
        logger.exception("file/confirm DB write failed tenant=%s", tenant.id)
        raise HTTPException(status_code=500, detail="Ошибка записи в базу") from e

    return FileConfirmResponse(rows_imported=imported, rows_skipped=skipped)


class ClearFileImportsRequest(BaseModel):
    sheet_name: str | None = None  # если передан — чистим только этот лист


@router.delete("/file/clear")
async def clear_file_imports(
    body: ClearFileImportsRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Удалить все file_ai транзакции (или только конкретного листа) текущего тенанта."""
    if body.sheet_name:
        prefix = _file_dedupe_prefix("", body.sheet_name)
        await db.execute(
            delete(Transaction).where(
                Transaction.tenant_id == tenant.id,
                Transaction.notion_id.like(f"{prefix}%"),
            )
        )
    else:
        await db.execute(
            delete(Transaction).where(
                Transaction.tenant_id == tenant.id,
                Transaction.notion_id.like("file_ai:%"),
            )
        )
    await db.commit()
    return {"ok": True}
