"""
Persistent file storage for case-activity screenshots and attachments.

FILE_STORAGE_ROOT:
  - Production (Railway Volume): /data
  - Local dev: ./local_storage/ (set in .env)

Relative paths stored in DB are resolved against this root.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("flowof.file_storage")

CASE_ACTIVITIES_DIR = "case_activities"


def get_storage_root() -> Path:
    """Return absolute path to FILE_STORAGE_ROOT."""
    raw = (os.getenv("FILE_STORAGE_ROOT") or "/data").strip()
    return Path(raw).expanduser().resolve()


def get_case_activities_root() -> Path:
    return get_storage_root() / CASE_ACTIVITIES_DIR


def ensure_storage_dirs() -> dict[str, str | bool]:
    """
    Create FILE_STORAGE_ROOT and case_activities subdirectory if missing.
    Returns diagnostic info for startup logging.
    """
    root = get_storage_root()
    activities = get_case_activities_root()

    root.mkdir(parents=True, exist_ok=True)
    activities.mkdir(parents=True, exist_ok=True)

    writable = os.access(root, os.W_OK) and os.access(activities, os.W_OK)

    info = {
        "file_storage_root": str(root),
        "case_activities_dir": str(activities),
        "root_exists": root.is_dir(),
        "activities_exists": activities.is_dir(),
        "writable": writable,
    }
    logger.info(
        "file_storage: root=%s case_activities=%s exists=%s writable=%s",
        info["file_storage_root"],
        info["case_activities_dir"],
        info["activities_exists"],
        info["writable"],
    )
    if not writable:
        logger.warning(
            "file_storage: directory not writable — uploads will fail until "
            "FILE_STORAGE_ROOT is mounted (Railway Volume /data) or permissions fixed"
        )
    return info
