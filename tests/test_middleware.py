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
"""Credential middleware: 401 / 400 on bad headers, per-request isolation."""

import asyncio

import pytest
from starlette.testclient import TestClient

from ncentral_mcp.__main__ import build_http_app
from ncentral_mcp.server import (
    GatewayCredentialsMiddleware,
    _credentials_var,
    create_mcp_server,
    get_client_from_context,
    normalize_server_url,
)

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
GOOD = {"X-Ncentral-Server-Url": "https://ncentral.example.com", "X-Ncentral-Jwt": "your-jwt"}


def _client() -> TestClient:
    return TestClient(build_http_app(create_mcp_server()))


def test_health_is_local():
    with _client() as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.parametrize("drop", ["X-Ncentral-Server-Url", "X-Ncentral-Jwt"])
@pytest.mark.parametrize("value", [None, "", "${NCENTRAL_JWT}"])
def test_missing_header_returns_401(drop, value):
    headers = MCP_HEADERS | GOOD
    if value is None:
        headers.pop(drop)
    else:
        headers[drop] = value
    with _client() as client:
        resp = client.post("/mcp", json=LIST_TOOLS, headers=headers)
    assert resp.status_code == 401
    assert resp.json()["required_headers"] == ["X-Ncentral-Server-Url", "X-Ncentral-Jwt"]


def test_plain_http_server_returns_400():
    headers = MCP_HEADERS | GOOD | {"X-Ncentral-Server-Url": "http://ncentral.example.com"}
    with _client() as client:
        resp = client.post("/mcp", json=LIST_TOOLS, headers=headers)
    assert resp.status_code == 400


def test_tools_list_over_http():
    with _client() as client:
        resp = client.post("/mcp", json=LIST_TOOLS, headers=MCP_HEADERS | GOOD)
    assert resp.status_code == 200
    for name in ("ncentral_list_devices", "ncentral_create_direct_task", "ncentral_delete_maintenance_windows"):
        assert name in resp.text


@pytest.mark.parametrize(
    "value,expected",
    [("https://ncentral.example.com", "https://ncentral.example.com"),
     ("ncentral.example.com/", "https://ncentral.example.com"),
     ("https://ncentral.example.com/api/", "https://ncentral.example.com"),
     ("https://ncentral.example.com:8443", "https://ncentral.example.com:8443"),
     ("http://localhost:8080", "http://localhost:8080"),
     ("http://ncentral.example.com", None),
     ("https://ncentral.example.com/?a=b", None)],
)
def test_normalize_server_url(value, expected):
    assert normalize_server_url(value) == expected


def _run_middleware(headers: list[tuple[bytes, bytes]]) -> dict:
    seen: dict = {}

    async def app(scope, receive, send):
        seen["credentials"] = _credentials_var.get()
        seen["client"] = get_client_from_context()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    asyncio.run(GatewayCredentialsMiddleware(app)({"type": "http", "path": "/mcp", "headers": headers}, receive, send))
    return seen


def _headers(jwt: bytes) -> list[tuple[bytes, bytes]]:
    return [(b"x-ncentral-server-url", b"ncentral.example.com"), (b"x-ncentral-jwt", jwt)]


def test_credentials_reach_request_context_and_are_reset():
    seen = _run_middleware(_headers(b" jwt-123 "))
    assert seen["credentials"].jwt == "jwt-123"
    assert seen["client"].server_url == "https://ncentral.example.com"
    assert _credentials_var.get() is None


def test_concurrent_requests_do_not_share_credentials():
    observed: list[tuple[str, str]] = []

    async def app(scope, receive, send):
        before = _credentials_var.get().jwt
        await asyncio.sleep(0.01)
        observed.append((before, _credentials_var.get().jwt))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    middleware = GatewayCredentialsMiddleware(app)

    def scope(jwt: bytes) -> dict:
        return {"type": "http", "path": "/mcp", "headers": _headers(jwt)}

    async def both():
        await asyncio.gather(middleware(scope(b"tenant-a"), receive, send), middleware(scope(b"tenant-b"), receive, send))

    asyncio.run(both())
    assert sorted(observed) == [("tenant-a", "tenant-a"), ("tenant-b", "tenant-b")]


def test_credentials_repr_hides_jwt():
    seen = _run_middleware(_headers(b"very-secret-jwt"))
    assert "very-secret-jwt" not in repr(seen["credentials"])
