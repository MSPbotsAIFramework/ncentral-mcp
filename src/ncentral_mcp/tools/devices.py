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
"""Devices: inventory, assets, lifecycle data, service status and saved filters."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import NcentralClient
from ._common import (
    OVERWRITES,
    READ_ONLY,
    ClientFactory,
    DeviceId,
    OrgUnitId,
    PageNumber,
    PageSize,
    SortBy,
    SortOrder,
    compact,
    entity,
    list_result,
    page_params,
    run_tool,
)

_LIFECYCLE_FIELDS = {
    "warrantyExpiryDate",
    "leaseExpiryDate",
    "expectedReplacementDate",
    "purchaseDate",
    "cost",
    "location",
    "assetTag",
    "description",
}


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_list_devices(
        filterId: Annotated[int | None, Field(description="Saved device filter (from ncentral_list_device_filters).")] = None,
        pageNumber: PageNumber = None,
        pageSize: PageSize = None,
        sortBy: SortBy = None,
        sortOrder: SortOrder = None,
    ) -> str:
        """List devices the API user can see, optionally through a saved device filter."""

        async def action(client: NcentralClient) -> Any:
            params = page_params(pageNumber, pageSize, sortBy, sortOrder) | compact({"filterId": filterId})
            return list_result(await client.get("devices", params))

        return await run_tool("ncentral_list_devices", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_get_device(deviceId: DeviceId) -> str:
        """Get one device: name, class, OS, customer / site, last check-in and logged-in user."""

        async def action(client: NcentralClient) -> Any:
            return entity(await client.get(f"devices/{deviceId}"))

        return await run_tool("ncentral_get_device", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_get_device_assets(deviceId: DeviceId) -> str:
        """Get a device's full asset inventory record."""

        async def action(client: NcentralClient) -> Any:
            return entity(await client.get(f"devices/{deviceId}/assets"))

        return await run_tool("ncentral_get_device_assets", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_get_device_lifecycle(deviceId: DeviceId) -> str:
        """Get a device's lifecycle data: warranty / lease expiry, purchase date, cost, asset tag."""

        async def action(client: NcentralClient) -> Any:
            return entity(await client.get(f"devices/{deviceId}/assets/lifecycle-info"))

        return await run_tool("ncentral_get_device_lifecycle", client_factory, action)

    @mcp.tool(annotations=OVERWRITES)
    async def ncentral_update_device_lifecycle(
        deviceId: DeviceId,
        data: Annotated[
            dict[str, Any],
            Field(
                description="Fields to change (others keep their values): warrantyExpiryDate, leaseExpiryDate, "
                "expectedReplacementDate, purchaseDate (ISO dates), cost (number), location, assetTag, description."
            ),
        ],
    ) -> str:
        """Change a device's lifecycle data; only the given fields change. Only when the user explicitly asks."""

        async def action(client: NcentralClient) -> Any:
            unknown = sorted(set(data) - _LIFECYCLE_FIELDS)
            if unknown:
                raise ValueError(f"Unknown lifecycle field(s): {', '.join(unknown)}; allowed: {', '.join(sorted(_LIFECYCLE_FIELDS))}.")
            if not data:
                raise ValueError("data has no fields to change.")
            await client.patch(f"devices/{deviceId}/assets/lifecycle-info", data)
            return {"updated": True, "deviceId": deviceId, "fields": sorted(data)}

        return await run_tool("ncentral_update_device_lifecycle", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_get_device_service_status(deviceId: DeviceId) -> str:
        """Get the state of every monitoring service on a device (normal, warning, failed...)."""

        async def action(client: NcentralClient) -> Any:
            return list_result(await client.get(f"devices/{deviceId}/service-monitor-status"))

        return await run_tool("ncentral_get_device_service_status", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_list_devices_by_org_unit(
        orgUnitId: OrgUnitId,
        pageNumber: PageNumber = None,
        pageSize: PageSize = None,
        sortBy: SortBy = None,
        sortOrder: SortOrder = None,
    ) -> str:
        """List the devices under an org unit (a customer or site id)."""

        async def action(client: NcentralClient) -> Any:
            params = page_params(pageNumber, pageSize, sortBy, sortOrder)
            return list_result(await client.get(f"org-units/{orgUnitId}/devices", params))

        return await run_tool("ncentral_list_devices_by_org_unit", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_list_device_filters(
        pageNumber: PageNumber = None, pageSize: PageSize = None, sortBy: SortBy = None, sortOrder: SortOrder = None
    ) -> str:
        """List the saved device filters (ids for ncentral_list_devices filterId)."""

        async def action(client: NcentralClient) -> Any:
            return list_result(await client.get("device-filters", page_params(pageNumber, pageSize, sortBy, sortOrder)))

        return await run_tool("ncentral_list_device_filters", client_factory, action)
