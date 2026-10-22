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
"""The org unit hierarchy: service organizations, customers, sites and registration tokens."""

from typing import Annotated, Any, Literal

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
    entity,
    list_result,
    paged,
    run_tool,
)


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_list_service_orgs(
        pageNumber: PageNumber = None,
        pageSize: PageSize = None,
        sortBy: SortBy = None,
        sortOrder: SortOrder = None,
        offset: Offset = None,
    ) -> str:
        """List service organizations (the top-level org units under the system)."""

        async def action(client: NcentralClient) -> Any:
            params, pos = paged(offset, pageNumber, pageSize, sortBy, sortOrder)
            return list_result(await client.get("service-orgs", params), **pos)

        return await run_tool("ncentral_list_service_orgs", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_list_customers(
        soId: Annotated[int | None, Field(description="Only customers of this service organization.", ge=1)] = None,
        pageNumber: PageNumber = None,
        pageSize: PageSize = None,
        sortBy: SortBy = None,
        sortOrder: SortOrder = None,
        offset: Offset = None,
    ) -> str:
        """List customers (all, or those of one service organization)."""

        async def action(client: NcentralClient) -> Any:
            path = f"service-orgs/{soId}/customers" if soId else "customers"
            params, pos = paged(offset, pageNumber, pageSize, sortBy, sortOrder)
            return list_result(await client.get(path, params), **pos)

        return await run_tool("ncentral_list_customers", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_get_customer(customerId: Annotated[int, Field(description="Customer id.", ge=1)]) -> str:
        """Get one customer: contact, address and external ids."""

        async def action(client: NcentralClient) -> Any:
            return entity(await client.get(f"customers/{customerId}"))

        return await run_tool("ncentral_get_customer", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_list_sites(
        customerId: Annotated[int | None, Field(description="Only sites of this customer.", ge=1)] = None,
        pageNumber: PageNumber = None,
        pageSize: PageSize = None,
        sortBy: SortBy = None,
        sortOrder: SortOrder = None,
        offset: Offset = None,
    ) -> str:
        """List sites (all, or those of one customer)."""

        async def action(client: NcentralClient) -> Any:
            path = f"customers/{customerId}/sites" if customerId else "sites"
            params, pos = paged(offset, pageNumber, pageSize, sortBy, sortOrder)
            return list_result(await client.get(path, params), **pos)

        return await run_tool("ncentral_list_sites", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_get_site(siteId: Annotated[int, Field(description="Site id.", ge=1)]) -> str:
        """Get one site: contact, address and external ids."""

        async def action(client: NcentralClient) -> Any:
            return entity(await client.get(f"sites/{siteId}"))

        return await run_tool("ncentral_get_site", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_list_org_units(
        pageNumber: PageNumber = None,
        pageSize: PageSize = None,
        sortBy: SortBy = None,
        sortOrder: SortOrder = None,
        offset: Offset = None,
    ) -> str:
        """List every org unit (system, service organizations, customers, sites) with its type and parent."""

        async def action(client: NcentralClient) -> Any:
            params, pos = paged(offset, pageNumber, pageSize, sortBy, sortOrder)
            return list_result(await client.get("org-units", params), **pos)

        return await run_tool("ncentral_list_org_units", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_get_org_unit(orgUnitId: OrgUnitId) -> str:
        """Get one org unit by id."""

        async def action(client: NcentralClient) -> Any:
            return entity(await client.get(f"org-units/{orgUnitId}"))

        return await run_tool("ncentral_get_org_unit", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_list_org_unit_children(
        orgUnitId: OrgUnitId,
        pageNumber: PageNumber = None,
        pageSize: PageSize = None,
        sortBy: SortBy = None,
        sortOrder: SortOrder = None,
        offset: Offset = None,
    ) -> str:
        """List the org units directly under an org unit."""

        async def action(client: NcentralClient) -> Any:
            params, pos = paged(offset, pageNumber, pageSize, sortBy, sortOrder)
            return list_result(await client.get(f"org-units/{orgUnitId}/children", params), **pos)

        return await run_tool("ncentral_list_org_unit_children", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_get_registration_token(
        kind: Annotated[Literal["customer", "site", "org-unit"], Field(description="What the id refers to.")],
        id: Annotated[int, Field(description="Customer, site or org unit id.", ge=1)],
    ) -> str:
        """Get the agent registration token (and expiry) of a customer, site or org unit.

        The token lets new agents enrol under that org unit: treat it as a secret.
        """

        async def action(client: NcentralClient) -> Any:
            prefix = {"customer": "customers", "site": "sites", "org-unit": "org-units"}[kind]
            return entity(await client.get(f"{prefix}/{id}/registration-token"))

        return await run_tool("ncentral_get_registration_token", client_factory, action)
