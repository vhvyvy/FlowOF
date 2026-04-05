"""
Onlymonster API — async httpx client.
Docs: https://omapi.onlymonster.ai/docs/json

Endpoints used:
  GET /api/v0/users/metrics    - chatter KPI (PPV Open Rate, APV, Total Chats)
"""
from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import urlencode

import httpx

logger = logging.getLogger("flowof.onlymonster")

_BASE_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "FlowOF/1.0",
}


def _to_iso(d: datetime | str) -> str:
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if isinstance(d, str):
        return d if "T" in d else f"{d}T00:00:00.000Z"
    return str(d)


async def fetch_chatter_metrics(
    api_url: str,
    api_key: str,
    start_date: datetime,
    end_date: datetime,
    creator_ids: list[str] | None = None,
) -> list[dict]:
    """
    Calls GET /api/v0/users/metrics and returns list of parsed records.
    Each record: {chatter: str(user_id), user_id, ppv_open_rate, apv, total_chats, source='api'}
    """
    base = api_url.rstrip("/")
    headers = {**_BASE_HEADERS, "x-om-auth-token": api_key}
    from_ts = _to_iso(start_date)
    to_ts = _to_iso(end_date)

    records: list[dict] = []
    offset = 0
    limit = 100

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            params: list[tuple[str, str | int]] = [
                ("from", from_ts),
                ("to", to_ts),
                ("offset", offset),
                ("limit", limit),
            ]
            if creator_ids:
                for cid in creator_ids[:100]:
                    params.append(("creator_ids", cid))

            qs = urlencode(params)
            url = f"{base}/api/v0/users/metrics?{qs}"

            try:
                resp = await client.get(url, headers=headers)
            except httpx.RequestError as e:
                raise RuntimeError(f"Onlymonster request error: {e}") from e

            if resp.status_code == 401:
                raise ValueError("Неверный API-токен Onlymonster")
            if resp.status_code == 403:
                body = resp.json() if resp.content else {}
                msg = body.get("message") or body.get("error") or resp.text[:300]
                raise PermissionError(f"403 Forbidden: {msg}")
            resp.raise_for_status()

            data = resp.json()
            items = data.get("items") or []
            if not items:
                break

            for item in items:
                user_id = item.get("user_id")
                if user_id is None:
                    continue

                paid = item.get("paid_messages_count") or 0
                sold = item.get("sold_messages_count") or 0
                sold_sum = item.get("sold_messages_price_sum") or 0
                messages = item.get("messages_count") or 0

                ppv_open_rate = round(sold / paid * 100, 1) if paid > 0 else None
                apv = round(sold_sum / sold, 2) if sold > 0 else None

                records.append({
                    "chatter": str(user_id),
                    "user_id": user_id,
                    "ppv_open_rate": ppv_open_rate,
                    "apv": apv,
                    "total_chats": messages or None,
                    "creator_ids": item.get("creator_ids") or [],
                    "source": "api",
                })

            if len(items) < limit:
                break
            offset += limit

    logger.info("Onlymonster sync: %d records", len(records))
    return records
