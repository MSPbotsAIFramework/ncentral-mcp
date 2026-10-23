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
"""FastMCP factory and the per-request credential middleware."""

import contextvars
import re
import uuid
from collections.abc import Callable
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ._arguments import EnvelopeFastMCP
from .api_client import NcentralClient, NcentralCredentials
from .config import Settings

HEADER_SERVER = "X-Ncentral-Server-Url"
HEADER_JWT = "X-Ncentral-Jwt"
REQUIRED_HEADERS = [HEADER_SERVER, HEADER_JWT]

_PLACEHOLDER = re.compile(r"^\$\{.*\}$")
_API_SUFFIX = re.compile(r"/api/?$", re.IGNORECASE)
_LOCAL_HOSTS = {"localhost", "127.0.0.1"}

# Per-request isolation: the middleware sets these for the duration of one
# HTTP request and resets them in `finally`. Nothing credential-related is
# ever stored at module level.
_credentials_var: contextvars.ContextVar[NcentralCredentials | None] = contextvars.ContextVar(
    "ncentral_credentials", default=None
)
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("ncentral_request_id", default="-")

INSTRUCTIONS = (
    "N-central is an RMM: it monitors MSP-managed devices organised as org "
    "units (system > service organizations > customers > sites), raises "
    "monitoring issues and runs scheduled tasks.\n"
    "Usage:\n"
    "- Find ids: ncentral_list_customers / ncentral_list_sites / "
    "ncentral_list_org_units; customer and site ids are org unit ids.\n"
    "- Devices: ncentral_list_devices (optionally filterId from "
    "ncentral_list_device_filters) or ncentral_list_devices_by_org_unit; then "
    "ncentral_get_device, _assets, _lifecycle, _service_status.\n"
    "- Problems: ncentral_list_active_issues(orgUnitId of a customer or site).\n"
    "- Lists page with pageNumber / pageSize (default 50); summary.has_more "
    "says whether to page on.\n"
    "- Tasks: ncentral_create_direct_task runs a script or automation policy "
    "on one device now; follow it with ncentral_get_task_status_details.\n"
    "Creating tasks, maintenance windows or access groups and changing custom "
    "properties or lifecycle data change the live RMM: call those tools only "
    "when the user explicitly asks. Deletes need confirm=true. Registration "
    "tokens are secrets that let agents enrol: share them only with the user."
)


def get_client_from_context() -> NcentralClient | None:
    """The client for the current request, or None outside a request."""
    credentials = _credentials_var.get()
    if credentials is None:
        return None
    return NcentralClient(credentials)


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text or _PLACEHOLDER.match(text):
        return None
    return text


def normalize_server_url(value: str) -> str | None:
    """https origin (+ path prefix) of the N-central server, or None when unusable."""
    text = value.strip()
    if "://" not in text:
        text = f"https://{text}"
    parts = urlsplit(text)
    if not parts.hostname or parts.query or parts.fragment:
        return None
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in _LOCAL_HOSTS):
        return None
    path = _API_SUFFIX.sub("", parts.path.rstrip("/"))
    return f"{parts.scheme}://{parts.netloc}{path}".rstrip("/")


class GatewayCredentialsMiddleware:
    """Reads the N-central headers on /mcp requests into the request context.

    401 without X-Ncentral-Server-Url and X-Ncentral-Jwt; 400 for a server URL that is not https.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        values = {name: _clean(request.headers.get(name)) for name in REQUIRED_HEADERS}
        missing = [name for name, value in values.items() if not value]
        if missing:
            await JSONResponse(
                {
                    "error": "Missing credentials",
                    "message": f"Missing header(s): {', '.join(missing)}",
                    "required_headers": REQUIRED_HEADERS,
                },
                status_code=401,
            )(scope, receive, send)
            return

        server_url = normalize_server_url(values[HEADER_SERVER] or "")
        if server_url is None:
            await JSONResponse(
                {
                    "error": "Invalid header",
                    "message": f"{HEADER_SERVER} must be an https URL such as https://ncentral.example.com",
                },
                status_code=400,
            )(scope, receive, send)
            return

        request_id = (request.headers.get("x-request-id") or "").strip()[:64] or uuid.uuid4().hex[:12]
        creds_token = _credentials_var.set(NcentralCredentials(server_url=server_url, jwt=values[HEADER_JWT] or ""))
        rid_token = request_id_var.set(request_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _credentials_var.reset(creds_token)
            request_id_var.reset(rid_token)


def create_mcp_server(settings: Settings | None = None) -> FastMCP:
    """Build the FastMCP server and register every tool."""
    mcp = EnvelopeFastMCP(
        name="ncentral-mcp",
        instructions=INSTRUCTIONS,
        # The service sits behind the gateway, so Host is never localhost;
        # DNS-rebinding protection would reject those requests with 421.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        stateless_http=True,
    )

    client_factory: Callable[[], NcentralClient | None] = get_client_from_context

    from .tools import (
        access_groups,
        custom_properties,
        devices,
        maintenance,
        monitoring,
        navigation,
        orgs,
        system,
        tasks,
    )

    for module in (navigation, system, orgs, devices, monitoring, tasks, custom_properties, maintenance, access_groups):
        module.register(mcp, client_factory)

    return mcp
