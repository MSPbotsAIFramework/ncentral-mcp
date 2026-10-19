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
"""Tool discovery (kept for compatibility) and the connection check."""

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .._json import compact as to_json
from ..api_client import NcentralClient
from ._common import LOCAL, READ_ONLY, ClientFactory, run_tool

DOMAINS: dict[str, tuple[str, list[str]]] = {
    "system": (
        "Server health, version information and token validation.",
        ["ncentral_health", "ncentral_server_info", "ncentral_validate_token"],
    ),
    "orgs": (
        "Service organizations, customers, sites, org units and agent registration tokens.",
        [
            "ncentral_list_service_orgs",
            "ncentral_list_customers",
            "ncentral_get_customer",
            "ncentral_list_sites",
            "ncentral_get_site",
            "ncentral_list_org_units",
            "ncentral_get_org_unit",
            "ncentral_list_org_unit_children",
            "ncentral_get_registration_token",
        ],
    ),
    "devices": (
        "Device inventory, assets, lifecycle (warranty) data, service status and saved filters.",
        [
            "ncentral_list_devices",
            "ncentral_get_device",
            "ncentral_get_device_assets",
            "ncentral_get_device_lifecycle",
            "ncentral_update_device_lifecycle",
            "ncentral_get_device_service_status",
            "ncentral_list_devices_by_org_unit",
            "ncentral_list_device_filters",
        ],
    ),
    "monitoring": ("Active issues and job statuses of an org unit.", ["ncentral_list_active_issues", "ncentral_list_job_statuses"]),
    "tasks": (
        "Scheduled tasks, their status, and running a script on one device now.",
        [
            "ncentral_list_device_tasks",
            "ncentral_get_task",
            "ncentral_get_task_status",
            "ncentral_get_task_status_details",
            "ncentral_create_direct_task",
        ],
    ),
    "custom-properties": (
        "Org unit and device custom properties: list, get, update.",
        [
            "ncentral_list_org_custom_properties",
            "ncentral_get_org_custom_property",
            "ncentral_update_org_custom_property",
            "ncentral_list_device_custom_properties",
            "ncentral_get_device_custom_property",
            "ncentral_update_device_custom_property",
        ],
    ),
    "maintenance": (
        "Device maintenance windows: list, add, delete.",
        ["ncentral_list_maintenance_windows", "ncentral_add_maintenance_windows", "ncentral_delete_maintenance_windows"],
    ),
    "access-groups": (
        "Access groups of an org unit: list, get, create device or org unit groups.",
        [
            "ncentral_list_access_groups",
            "ncentral_get_access_group",
            "ncentral_create_device_access_group",
            "ncentral_create_org_unit_access_group",
        ],
    ),
}

Domain = Literal["system", "orgs", "devices", "monitoring", "tasks", "custom-properties", "maintenance", "access-groups"]


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=LOCAL)
    async def ncentral_navigate(
        domain: Annotated[Domain | None, Field(description="Area to describe; omit to list every area.")] = None,
    ) -> str:
        """Describe the N-central tool areas. All tools are already callable; this changes nothing."""
        if domain is None:
            return to_json({name: {"summary": summary, "tools": tools} for name, (summary, tools) in DOMAINS.items()})
        summary, tools = DOMAINS[domain]
        return to_json({"domain": domain, "summary": summary, "tools": tools})

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_status() -> str:
        """Check the N-central connection (server reachable, JWT accepted) and list the tool areas."""

        async def action(client: NcentralClient) -> dict:
            await client.get("auth/validate")
            return {
                "connected": True,
                "server_url": client.server_url,
                "domains": {name: summary for name, (summary, _tools) in DOMAINS.items()},
            }

        return await run_tool("ncentral_status", client_factory, action)
