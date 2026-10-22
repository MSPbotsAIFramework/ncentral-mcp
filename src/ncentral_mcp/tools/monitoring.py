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
"""Monitoring: active issues and job statuses of an org unit."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import NcentralClient
from ._common import (
    READ_ONLY,
    ClientFactory,
    Offset,
    OrgUnitId,
    PageNumber,
    PageSize,
    SortBy,
    SortOrder,
    list_result,
    paged,
    run_tool,
)


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_list_active_issues(
        orgUnitId: Annotated[int, Field(description="Customer or site id (service organizations are not supported).", ge=1)],
        pageNumber: PageNumber = None,
        pageSize: PageSize = None,
        sortBy: SortBy = None,
        sortOrder: SortOrder = None,
        offset: Offset = None,
    ) -> str:
        """List active monitoring issues (failed / warning services) of a customer or site."""

        async def action(client: NcentralClient) -> Any:
            params, pos = paged(offset, pageNumber, pageSize, sortBy, sortOrder)
            return list_result(await client.get(f"org-units/{orgUnitId}/active-issues", params), **pos)

        return await run_tool("ncentral_list_active_issues", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_list_job_statuses(orgUnitId: OrgUnitId) -> str:
        """List the job statuses of an org unit."""

        async def action(client: NcentralClient) -> Any:
            return list_result(await client.get(f"org-units/{orgUnitId}/job-statuses"))

        return await run_tool("ncentral_list_job_statuses", client_factory, action)
