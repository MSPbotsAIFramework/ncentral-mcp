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
"""Server health, version and token checks."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api_client import NcentralClient
from ._common import READ_ONLY, ClientFactory, entity, run_tool


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_health() -> str:
        """Check the N-central API-Service is running (returns the server's current time)."""

        async def action(client: NcentralClient) -> Any:
            return await client.get("health")

        return await run_tool("ncentral_health", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_server_info() -> str:
        """Get the N-central and API-Service version information."""

        async def action(client: NcentralClient) -> Any:
            info = await client.get("server-info")
            try:
                extra = entity(await client.get("server-info/extra"))
            except Exception:  # noqa: BLE001 - the extra endpoint is a preview; the base info still answers
                extra = None
            return {"server_info": info, "versions": extra} if extra else info

        return await run_tool("ncentral_server_info", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_validate_token() -> str:
        """Check the User-API Token (JWT) is accepted and an access token works."""

        async def action(client: NcentralClient) -> Any:
            return await client.get("auth/validate")

        return await run_tool("ncentral_validate_token", client_factory, action)
