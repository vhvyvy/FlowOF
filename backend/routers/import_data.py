"""Загрузка CSV/XLSX, превью, подтверждение маппинга и импорт в transactions."""
from __future__ import annotations

import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, get_db
from dependencies import get_current_tenant
from import_contract import ColumnMapping, ExcelImportState, TenantSourceMappingConfig
from models import SyncLog, Tenant, TenantSource, Transaction
from services.credentials_crypto import encrypt_credentials_blob
from services.file_import import (
    build_transactions_from_dataframe,
    dataframe_preview,
    load_dataframe,
    new_batch_id,
    suggest_mapping,
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
