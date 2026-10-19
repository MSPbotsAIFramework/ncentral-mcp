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
"""Device maintenance windows."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import NcentralClient
from ._common import (
    DESTRUCTIVE,
    READ_ONLY,
    WRITES,
    ClientFactory,
    Confirm,
    DeviceId,
    list_result,
    run_tool,
)

_REQUIRED = ("name", "type", "cron", "duration", "enabled", "applicableAction")
_OPTIONAL = (
    "downtimeOnAction",
    "maxDowntime",
    "rebootMethod",
    "rebootDelay",
    "userMessageEnabled",
    "userMessage",
    "messageSenderEnabled",
    "messageSender",
    "preserveStateEnabled",
)


def _check_window(index: int, window: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in _REQUIRED if window.get(k) is None]
    if missing:
        raise ValueError(f"windows[{index}] is missing: {', '.join(missing)}.")
    unknown = sorted(set(window) - set(_REQUIRED) - set(_OPTIONAL))
    if unknown:
        raise ValueError(f"windows[{index}] has unknown field(s): {', '.join(unknown)}.")
    return window


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_list_maintenance_windows(deviceId: DeviceId) -> str:
        """List a device's maintenance windows with schedule (cron), duration and scheduleID."""

        async def action(client: NcentralClient) -> Any:
            return list_result(await client.get(f"devices/{deviceId}/maintenance-windows"))

        return await run_tool("ncentral_list_maintenance_windows", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def ncentral_add_maintenance_windows(
        deviceIds: Annotated[list[int], Field(description="Devices to add every window to.", min_length=1)],
        windows: Annotated[
            list[dict[str, Any]],
            Field(
                description="Windows, each with name, type (action), cron (schedule), duration (minutes), "
                "enabled, applicableAction ([{type, actions}]); reboot windows may add rebootMethod, rebootDelay, "
                "maxDowntime, downtimeOnAction and user message fields.",
                min_length=1,
            ),
        ],
    ) -> str:
        """Add maintenance windows to devices (changes patching / reboots). Only when the user explicitly asks."""

        async def action(client: NcentralClient) -> Any:
            body = {
                "deviceIDs": deviceIds,
                "maintenanceWindows": [_check_window(i, w) for i, w in enumerate(windows)],
            }
            result = await client.post("devices/maintenance-windows", body)
            return result if result else {"success": True, "deviceIds": deviceIds, "windows": len(windows)}

        return await run_tool("ncentral_add_maintenance_windows", client_factory, action)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def ncentral_delete_maintenance_windows(
        scheduleIds: Annotated[
            list[int], Field(description="scheduleID values from ncentral_list_maintenance_windows.", min_length=1)
        ],
        confirm: Confirm = None,
    ) -> str:
        """Delete device-level patch maintenance windows. Irreversible: only when the user explicitly asks."""

        async def action(client: NcentralClient) -> Any:
            if confirm is not True:
                raise ValueError("Deleting maintenance windows is irreversible; ask the user, then call again with confirm=true.")
            result = await client.delete("devices/maintenance-windows", {"scheduleIds": scheduleIds})
            return result if result else {"success": True, "scheduleIds": scheduleIds}

        return await run_tool("ncentral_delete_maintenance_windows", client_factory, action)
