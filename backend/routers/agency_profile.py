"""Agency profile endpoints — owner configures thresholds, priorities, glossary."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_owner, get_current_tenant
from models import Tenant
from services.agency_profile import (
    get_agency_profile,
    save_agency_profile,
    build_profile_context,
)

logger = logging.getLogger("flowof.agency_profile")
router = APIRouter(prefix="/api/v1/agency-profile", tags=["agency-profile"])


class AgencyProfileOut(BaseModel):
    tenant_id:           int
    rpc_critical:        float
    rpc_working_low:     float
    rpc_strong:          float
    open_rate_critical:  float
    open_rate_working:   float
    open_rate_strong:    float
    priorities:          str | None
    glossary:            str | None
    target_notes:        str | None


class AgencyProfileUpdate(BaseModel):
    rpc_critical:        float | None = None
    rpc_working_low:     float | None = None
    rpc_strong:          float | None = None
    open_rate_critical:  float | None = None
    open_rate_working:   float | None = None
    open_rate_strong:    float | None = None
    priorities:          str | None = None
    glossary:            str | None = None
    target_notes:        str | None = None


class AgencyProfileWithContext(AgencyProfileOut):
    auto_context: str | None = None


def _row_to_out(row: dict[str, Any]) -> AgencyProfileOut:
    return AgencyProfileOut(
        tenant_id=row["tenant_id"],
        rpc_critical=float(row.get("rpc_critical") or 0.15),
        rpc_working_low=float(row.get("rpc_working_low") or 0.25),
        rpc_strong=float(row.get("rpc_strong") or 0.50),
        open_rate_critical=float(row.get("open_rate_critical") or 20.0),
        open_rate_working=float(row.get("open_rate_working") or 25.0),
        open_rate_strong=float(row.get("open_rate_strong") or 35.0),
        priorities=row.get("priorities"),
        glossary=row.get("glossary"),
        target_notes=row.get("target_notes"),
    )


@router.get("", response_model=AgencyProfileWithContext)
async def read_agency_profile(
    _: Any = Depends(require_owner),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Return the agency profile including auto-calculated context paragraph."""
    row = await get_agency_profile(db, tenant.id)
    ctx = await build_profile_context(db, tenant.id)
    out = _row_to_out(row)
    return AgencyProfileWithContext(**out.model_dump(), auto_context=ctx)


@router.put("", response_model=AgencyProfileOut)
async def update_agency_profile(
    body: AgencyProfileUpdate,
    _: Any = Depends(require_owner),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    row = await save_agency_profile(db, tenant.id, updates)
    return _row_to_out(row)
