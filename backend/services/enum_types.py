"""
Shared SQLAlchemy PostgreSQL ENUM type objects.

create_type=False — the actual PostgreSQL types are created by schema_patch.py;
SQLAlchemy must NOT attempt to re-create them via CREATE TYPE, only reference them.

Names here MUST match the enum names in schema_patch._ENUM_PATCHES exactly.
"""
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

CASE_STAGE = PG_ENUM(
    "detected", "in_progress", "hold", "review_due", "closed", "cancelled",
    name="case_stage", create_type=False,
)
CASE_PRIORITY = PG_ENUM(
    "high", "normal", "low",
    name="case_priority", create_type=False,
)
CASE_RESULT = PG_ENUM(
    "success", "failed", "cancelled",
    name="case_result", create_type=False,
)
METRIC_TYPE = PG_ENUM(
    "ppv_open_rate", "rpc", "apv", "total_chats", "revenue",
    name="metric_type", create_type=False,
)
SNAPSHOT_TYPE = PG_ENUM(
    "baseline", "target", "result",
    name="snapshot_type", create_type=False,
)
SNAPSHOT_SOURCE = PG_ENUM(
    "system_from_daily", "system_from_monthly", "manual",
    name="snapshot_source", create_type=False,
)
LEDGER_EVENT_TYPE = PG_ENUM(
    "case_opened", "case_closed_success", "case_closed_failed",
    "case_cancelled", "guardrail_triggered", "baseline_frozen",
    name="ledger_event_type", create_type=False,
)
STAGE_CHANGED_BY = PG_ENUM(
    "admin", "owner", "system",
    name="stage_changed_by", create_type=False,
)

# Alias — KpiConfig.metric_type uses the same DB enum as AdminCase.metric_type
KPI_METRIC_TYPE = METRIC_TYPE
