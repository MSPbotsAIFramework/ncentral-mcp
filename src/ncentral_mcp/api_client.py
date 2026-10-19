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
"""Async client for the N-central REST API (API-Service)."""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ._json import error_envelope

logger = logging.getLogger("ncentral_mcp.api")

_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
_MAX_RETRIES = 2
_MAX_BACKOFF_SECONDS = 20.0
# Whole-call budget including retries; the gateway times a tool call out at 120s.
_CALL_BUDGET_SECONDS = 100.0

# One connection pool for the process. It never holds credentials: the
# Authorization header is built per request from the caller's own token, so
# sharing the pool across tenants is safe.
_shared_http_client: httpx.AsyncClient | None = None


def _get_shared_http_client() -> httpx.AsyncClient:
    global _shared_http_client
    if _shared_http_client is None:
        _shared_http_client = httpx.AsyncClient(timeout=_TIMEOUT)
    return _shared_http_client


# status_code -> (error code, retryable). 0 means no HTTP response at all
# (connection error or timeout).
_STATUS_TO_CODE: dict[int, tuple[str, bool]] = {
    0: ("upstream_error", True),
    400: ("invalid_argument", False),
    401: ("unauthorized", False),
    403: ("unauthorized", False),
    404: ("not_found", False),
    422: ("invalid_argument", False),
    429: ("rate_limited", True),
}


def classify_status(status_code: int) -> tuple[str, bool]:
    if status_code in _STATUS_TO_CODE:
        return _STATUS_TO_CODE[status_code]
    if status_code >= 500:
        return "upstream_error", True
    if status_code >= 400:
        return "invalid_argument", False
    return "upstream_error", True


class NcentralError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"N-central API error {status_code}: {message}")

    def to_envelope(self) -> str:
        code, retryable = classify_status(self.status_code)
        return error_envelope(code, self.message, retryable)


@dataclass(frozen=True)
class NcentralCredentials:
    server_url: str
    jwt: str

    def __repr__(self) -> str:  # never leak the token into logs or tracebacks
        return f"NcentralCredentials(server_url={self.server_url!r}, jwt=<redacted>)"


class NcentralClient:
    """N-central API wrapper for one caller's User-API Token (JWT).

    The JWT is exchanged for a short-lived access token on first use. The access
    token lives only on this instance, which serves a single MCP request; nothing
    is cached across requests.
    """

    def __init__(self, credentials: NcentralCredentials, http_client: httpx.AsyncClient | None = None):
        self._credentials = credentials
        self._http = http_client
        self.server_url = credentials.server_url.rstrip("/")
        self._token: str | None = None

    def _client(self) -> httpx.AsyncClient:
        return self._http or _get_shared_http_client()

    def _redact(self, text: str) -> str:
        text = text.replace(self._credentials.jwt, "[REDACTED]")
        return text.replace(self._token, "[REDACTED]") if self._token else text

    async def _authenticate(self) -> str:
        url = f"{self.server_url}/api/auth/authenticate"
        headers = {"Authorization": f"Bearer {self._credentials.jwt}", "Accept": "application/json"}
        try:
            resp = await self._client().post(url, headers=headers)
        except httpx.TimeoutException as e:
            raise NcentralError(0, "Timed out reaching the N-central server (authenticate)") from e
        except httpx.RequestError as e:
            raise NcentralError(0, f"Network error reaching the N-central server (authenticate): {type(e).__name__}") from e
        logger.info("ncentral_api method=POST path=api/auth/authenticate status=%s", resp.status_code)
        if resp.status_code in (400, 401, 403):
            raise NcentralError(
                401,
                "N-central rejected the User-API Token (JWT). Generate a new one for an API-only user "
                "(Administration > User Management > Users > API Access) and check the user has MFA disabled.",
            )
        if resp.status_code in (404, 405):
            raise NcentralError(
                400,
                f"No N-central API-Service answered at {self.server_url}/api (HTTP {resp.status_code}); "
                "check X-Ncentral-Server-Url is the N-central server root.",
            )
        if resp.status_code >= 400:
            raise NcentralError(resp.status_code, self._redact(_error_message(resp, "api/auth/authenticate")))
        data = _parse_body(resp)
        tokens = data.get("tokens") if isinstance(data, dict) else None
        access = tokens.get("access") if isinstance(tokens, dict) else None
        token = access.get("token") if isinstance(access, dict) else None
        if not token:
            raise NcentralError(502, "N-central authenticate response had no access token")
        return token

    async def _bearer(self, renew: bool = False) -> str:
        if renew or not self._token:
            self._token = await self._authenticate()
        return self._token

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, body: Any = None) -> Any:
        return await self.request("POST", path, body=body)

    async def put(self, path: str, body: Any) -> Any:
        return await self.request("PUT", path, body=body)

    async def patch(self, path: str, body: Any) -> Any:
        return await self.request("PATCH", path, body=body)

    async def delete(self, path: str, body: Any = None) -> Any:
        return await self.request("DELETE", path, body=body)

    async def request(self, method: str, path: str, params: dict[str, Any] | None = None, body: Any = None) -> Any:
        """Call ``{server}/api/{path}``; on 401 gets a new access token once and retries."""
        resp = await self._send(method, path, params, body, await self._bearer())
        if resp.status_code == 401:
            resp = await self._send(method, path, params, body, await self._bearer(renew=True))
        if resp.status_code >= 400:
            raise NcentralError(resp.status_code, self._redact(_error_message(resp, path)))
        return _parse_body(resp)

    async def _send(self, method: str, path: str, params: dict[str, Any] | None, body: Any, token: str) -> httpx.Response:
        url = f"{self.server_url}/api/{path.strip('/')}" if path.strip("/") else f"{self.server_url}/api"
        query = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        started = time.monotonic()
        attempt = 0
        while True:
            t0 = time.monotonic()
            resp: httpx.Response | None = None
            error: NcentralError | None = None
            try:
                resp = await self._client().request(
                    method, url, params=query, json=body if body is not None else None, headers=headers
                )
                status = resp.status_code
            except httpx.TimeoutException:
                status, error = 0, NcentralError(0, f"Timed out calling N-central ({method} {path})")
            except httpx.RequestError as e:
                status = 0
                error = NcentralError(0, f"Network error calling N-central ({method} {path}): {type(e).__name__}")

            logger.info(
                "ncentral_api method=%s path=%s status=%s ms=%d attempt=%d",
                method, path, status, (time.monotonic() - t0) * 1000, attempt,
            )

            # 429 is refused before processing, so any method may retry it; other
            # failures are retried only for reads, so a write never runs twice.
            retryable = status == 429 or (method == "GET" and (status == 0 or status >= 500))
            if retryable and attempt < _MAX_RETRIES:
                delay = _retry_delay(resp, attempt)
                if time.monotonic() - started + delay < _CALL_BUDGET_SECONDS:
                    attempt += 1
                    await asyncio.sleep(delay)
                    continue
            if error is not None:
                if method != "GET" and status == 0:
                    error.message += "; the change may or may not have been applied, check before retrying"
                raise error
            assert resp is not None
            return resp


def _retry_delay(resp: httpx.Response | None, attempt: int) -> float:
    if resp is not None:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), _MAX_BACKOFF_SECONDS))
            except ValueError:
                pass
    return min(float(2**attempt), _MAX_BACKOFF_SECONDS)


def _parse_body(resp: httpx.Response) -> Any:
    if not resp.content or not resp.content.strip():
        return None
    try:
        return resp.json()
    except ValueError:
        return {"raw_response": resp.text[:2000]}


def _error_message(resp: httpx.Response, path: str) -> str:
    fallback = f"N-central returned HTTP {resp.status_code} for {path}"
    try:
        payload = resp.json()
    except ValueError:
        text = resp.text.strip()
        if text.lstrip().startswith("<"):  # an HTML error page says nothing useful
            return fallback
        return f"{fallback}: {text[:300]}" if text else fallback
    if isinstance(payload, dict):
        parts = [str(payload[k]) for k in ("message", "error", "detail") if isinstance(payload.get(k), str) and payload[k]][:1]
        errors = payload.get("errors")
        if isinstance(errors, list):
            parts += [str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors]
        if parts:
            return f"{fallback}: {' - '.join(parts)[:500]}"
    return fallback
