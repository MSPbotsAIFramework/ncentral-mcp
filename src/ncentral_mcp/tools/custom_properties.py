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
"""Custom properties of org units and devices."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import NcentralClient
from ._common import (
    OVERWRITES,
    READ_ONLY,
    ClientFactory,
    DeviceId,
    Offset,
    OrgUnitId,
    PageNumber,
    PageSize,
    PropertyId,
    SortBy,
    SortOrder,
    entity,
    list_result,
    paged,
    run_tool,
)

Value = Annotated[
    str, Field(description="New value. ENUMERATED properties take one of their enumeratedValueList values; DATE takes ISO.")
]


def _warnings(result: Any, **ids: int) -> dict:
    out: dict[str, Any] = {"updated": True, **ids}
    if isinstance(result, dict) and result.get("_warnings"):
        out["warnings"] = result["_warnings"]
    return out


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_list_org_custom_properties(
        orgUnitId: OrgUnitId,
        pageNumber: PageNumber = None,
        pageSize: PageSize = None,
        sortBy: SortBy = None,
        sortOrder: SortOrder = None,
        offset: Offset = None,
    ) -> str:
        """List an org unit's custom properties with their type and value."""

        async def action(client: NcentralClient) -> Any:
            params, pos = paged(offset, pageNumber, pageSize, sortBy, sortOrder)
            return list_result(await client.get(f"org-units/{orgUnitId}/custom-properties", params), **pos)

        return await run_tool("ncentral_list_org_custom_properties", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_get_org_custom_property(orgUnitId: OrgUnitId, propertyId: PropertyId) -> str:
        """Get one custom property of an org unit."""

        async def action(client: NcentralClient) -> Any:
            return entity(await client.get(f"org-units/{orgUnitId}/custom-properties/{propertyId}"))

        return await run_tool("ncentral_get_org_custom_property", client_factory, action)

    @mcp.tool(annotations=OVERWRITES)
    async def ncentral_update_org_custom_property(orgUnitId: OrgUnitId, propertyId: PropertyId, value: Value) -> str:
        """Set the value of an org unit's custom property. Only when the user explicitly asks."""

        async def action(client: NcentralClient) -> Any:
            result = await client.put(f"org-units/{orgUnitId}/custom-properties/{propertyId}", {"value": value})
            return _warnings(result, orgUnitId=orgUnitId, propertyId=propertyId)

        return await run_tool("ncentral_update_org_custom_property", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_list_device_custom_properties(deviceId: DeviceId) -> str:
        """List a device's custom properties with their type and value."""

        async def action(client: NcentralClient) -> Any:
            return list_result(await client.get(f"devices/{deviceId}/custom-properties"))

        return await run_tool("ncentral_list_device_custom_properties", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_get_device_custom_property(deviceId: DeviceId, propertyId: PropertyId) -> str:
        """Get one custom property of a device."""

        async def action(client: NcentralClient) -> Any:
            return entity(await client.get(f"devices/{deviceId}/custom-properties/{propertyId}"))

        return await run_tool("ncentral_get_device_custom_property", client_factory, action)

    @mcp.tool(annotations=OVERWRITES)
    async def ncentral_update_device_custom_property(deviceId: DeviceId, propertyId: PropertyId, value: Value) -> str:
        """Set the value of a device's custom property. Only when the user explicitly asks."""

        async def action(client: NcentralClient) -> Any:
            result = await client.put(f"devices/{deviceId}/custom-properties/{propertyId}", {"value": value})
            return _warnings(result, deviceId=deviceId, propertyId=propertyId)

        return await run_tool("ncentral_update_device_custom_property", client_factory, action)
