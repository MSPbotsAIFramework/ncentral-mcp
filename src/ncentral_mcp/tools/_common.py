# Copyright 2026 MSPbots.ai
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Shared argument types, paging helpers and the error-handling wrapper."""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import NcentralClient, NcentralError

logger = logging.getLogger("ncentral_mcp.tools")

ClientFactory = Callable[[], NcentralClient | None]

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
LOCAL = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
OVERWRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)

NOT_CONFIGURED = error_envelope(
    "not_configured", "N-central credentials are missing for this request (X-Ncentral-Server-Url, X-Ncentral-Jwt).", False
)

DEFAULT_PAGE_SIZE = 50

DeviceId = Annotated[int, Field(description="Device id (from ncentral_list_devices).", ge=1)]
OrgUnitId = Annotated[int, Field(description="Org unit id: a service organization, customer or site id.", ge=1)]
TaskId = Annotated[int, Field(description="Scheduled task id.", ge=1)]
PropertyId = Annotated[int, Field(description="Custom property id (from the matching list tool).", ge=1)]
Confirm = Annotated[bool | None, Field(description="Must be true to delete; ask the user first.")]

PageNumber = Annotated[int | None, Field(description="Page number, from 1 (default 1).", ge=1)]
PageSize = Annotated[
    int | None, Field(description=f"Items per page, 1-1000 (default {DEFAULT_PAGE_SIZE}).", ge=1, le=1000)
]
SortBy = Annotated[str | None, Field(description="Field to sort by, e.g. longName.")]
SortOrder = Annotated[
    Literal["asc", "ascending", "natural", "desc", "descending", "reverse"] | None,
    Field(description="Sort direction (default ascending)."),
]

_DESCENDING = {"desc", "descending", "reverse"}


def compact(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def page_params(
    page_number: int | None, page_size: int | None, sort_by: str | None, sort_order: str | None
) -> dict[str, Any]:
    order = None
    if sort_order:
        order = "desc" if sort_order in _DESCENDING else "asc"
    return compact(
        {
            "pageNumber": page_number,
            "pageSize": page_size or DEFAULT_PAGE_SIZE,
            "sortBy": sort_by.strip() if sort_by and sort_by.strip() else None,
            "sortOrder": order,
        }
    )


def list_result(payload: Any) -> Any:
    """Add a paging summary to {data, totalItems[, pageNumber, totalPages]} lists."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return payload
    data = payload["data"]
    summary: dict[str, Any] = {"count": len(data), "total": payload.get("totalItems", len(data))}
    if "pageNumber" in payload:
        page, pages = payload.get("pageNumber") or 1, payload.get("totalPages") or 1
        summary |= {"page": page, "total_pages": pages, "has_more": page < pages}
        if page < pages:
            summary["next_page"] = page + 1
    body = {k: v for k, v in payload.items() if k != "_links"}
    return {"summary": summary, **body}


def entity(payload: Any) -> Any:
    """Unwrap {data, _links} single-item responses."""
    if isinstance(payload, dict) and "data" in payload and set(payload) <= {"data", "_links", "_warning", "_warnings"}:
        extra = {k: payload[k] for k in ("_warning", "_warnings") if payload.get(k)}
        return payload["data"] if not extra else {"data": payload["data"], **extra}
    return payload


async def run_tool(
    name: str,
    client_factory: ClientFactory,
    action: Callable[[NcentralClient], Awaitable[Any]],
) -> str:
    """Resolve the caller's client, run ``action``, and always return a string.

    Errors never escape as exceptions: they become the standard error envelope.
    """
    client = client_factory()
    if client is None:
        return NOT_CONFIGURED
    started = time.monotonic()
    try:
        result = await action(client)
    except NcentralError as e:
        logger.info("tool=%s outcome=error status=%s ms=%d", name, e.status_code, _ms(started))
        return e.to_envelope()
    except ValueError as e:
        logger.info("tool=%s outcome=invalid_argument ms=%d", name, _ms(started))
        return error_envelope("invalid_argument", str(e), False)
    except Exception as e:  # noqa: BLE001 - tools must never raise
        logger.warning("tool=%s outcome=unexpected error=%s ms=%d", name, type(e).__name__, _ms(started))
        return error_envelope("upstream_error", f"Unexpected error: {type(e).__name__}", True)
    logger.info("tool=%s outcome=ok ms=%d", name, _ms(started))
    if result is None:
        result = {"result": None, "note": "N-central returned an empty response."}
    return result if isinstance(result, str) else dump_json_capped(result)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
