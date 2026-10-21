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
"""Access groups: which users can see which devices or org units."""

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import NcentralClient
from ._common import (
    READ_ONLY,
    WRITES,
    ClientFactory,
    OrgUnitId,
    PageNumber,
    PageSize,
    SortBy,
    SortOrder,
    compact,
    entity,
    enum_value,
    list_result,
    page_params,
    run_tool,
)

GroupName = Annotated[str, Field(description="Access group name.", min_length=1)]
GroupDescription = Annotated[str, Field(description="Access group description.")]
UserIds = Annotated[list[str | int] | None, Field(description="User ids to give the group's access.")]
AutoInclude = Literal["true", "false"]


def _ids(values: list[str | int] | None) -> list[str] | None:
    if not values:
        return None
    return [str(v).strip() for v in values if str(v).strip()]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_list_access_groups(
        orgUnitId: OrgUnitId,
        pageNumber: PageNumber = None,
        pageSize: PageSize = None,
        sortBy: SortBy = None,
        sortOrder: SortOrder = None,
    ) -> str:
        """List the access groups of an org unit."""

        async def action(client: NcentralClient) -> Any:
            params = page_params(pageNumber, pageSize, sortBy, sortOrder)
            return list_result(await client.get(f"org-units/{orgUnitId}/access-groups", params))

        return await run_tool("ncentral_list_access_groups", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_get_access_group(
        accessGroupId: Annotated[int, Field(description="Access group id.", ge=1)],
    ) -> str:
        """Get an access group with its org units, devices and users."""

        async def action(client: NcentralClient) -> Any:
            return entity(await client.get(f"access-groups/{accessGroupId}"))

        return await run_tool("ncentral_get_access_group", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def ncentral_create_device_access_group(
        orgUnitId: OrgUnitId,
        groupName: GroupName,
        groupDescription: GroupDescription,
        deviceIds: Annotated[list[str | int] | None, Field(description="Device ids in the group.")] = None,
        userIds: UserIds = None,
    ) -> str:
        """Create an access group giving users access to chosen devices. Only when the user explicitly asks."""

        async def action(client: NcentralClient) -> Any:
            body = compact(
                {
                    "groupName": groupName.strip(),
                    "groupDescription": groupDescription,
                    "deviceIds": _ids(deviceIds),
                    "userIds": _ids(userIds),
                }
            )
            result = await client.post(f"org-units/{orgUnitId}/device-access-groups", body)
            return result if result else {"created": True, "orgUnitId": orgUnitId, "groupName": groupName.strip()}

        return await run_tool("ncentral_create_device_access_group", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def ncentral_create_org_unit_access_group(
        orgUnitId: OrgUnitId,
        groupName: GroupName,
        groupDescription: GroupDescription,
        orgUnitIds: Annotated[list[str | int] | None, Field(description="Org unit ids in the group.")] = None,
        userIds: UserIds = None,
        autoIncludeNewOrgUnits: Annotated[
            AutoInclude | str | None, Field(description="Add org units created later automatically.")
        ] = None,
    ) -> str:
        """Create an access group giving users access to chosen org units. Only when the user explicitly asks."""

        async def action(client: NcentralClient) -> Any:
            body = compact(
                {
                    "groupName": groupName.strip(),
                    "groupDescription": groupDescription,
                    "orgUnitIds": _ids(orgUnitIds),
                    "userIds": _ids(userIds),
                    "autoIncludeNewOrgUnits": enum_value(autoIncludeNewOrgUnits, AutoInclude),
                }
            )
            result = await client.post(f"org-units/{orgUnitId}/access-groups", body)
            return result if result else {"created": True, "orgUnitId": orgUnitId, "groupName": groupName.strip()}

        return await run_tool("ncentral_create_org_unit_access_group", client_factory, action)
