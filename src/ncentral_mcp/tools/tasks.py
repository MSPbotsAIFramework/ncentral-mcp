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
"""Scheduled tasks: per-device lists, status, and direct-support (run now) tasks."""

import json
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from ..api_client import NcentralClient
from ._common import (
    READ_ONLY,
    WRITES,
    ClientFactory,
    DeviceId,
    TaskId,
    entity,
    enum_value,
    list_result,
    run_tool,
)


CredentialType = Literal["LocalSystem", "DeviceCredentials", "CustomCredentials"]
TaskType = Literal["AutomationPolicy", "Script", "MacScript"]


class TaskCredential(BaseModel):
    type: CredentialType = Field(
        description="Run as the local system account, the device's stored credentials, or the username / password given."
    )
    username: str | None = Field(default=None, description="Only for CustomCredentials.")
    password: str | None = Field(default=None, description="Only for CustomCredentials.")


class TaskParameter(BaseModel):
    name: str = Field(min_length=1, description="Parameter name as defined on the script / policy.")
    value: str | None = Field(default=None, description="Parameter value.")
    description: str | None = Field(default=None, description="Defaults to the name.")
    type: Literal["string", "integer", "boolean", "text", "dword"] | None = Field(default=None, description="Default string.")


def _credential(value: TaskCredential | str) -> TaskCredential:
    """Accept the credential object, its JSON text, or just the type name (e.g. LocalSystem)."""
    if isinstance(value, TaskCredential):
        return value
    text = value.strip()
    if text.startswith("{"):
        try:
            return TaskCredential.model_validate(json.loads(text))
        except json.JSONDecodeError as e:
            raise ValueError(f"credential is not valid JSON: {e.msg}.") from None
    return TaskCredential.model_validate({"type": enum_value(text, CredentialType)})


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_list_device_tasks(deviceId: DeviceId) -> str:
        """List the scheduled tasks of a device with their name and status."""

        async def action(client: NcentralClient) -> Any:
            return list_result(await client.get(f"devices/{deviceId}/scheduled-tasks"))

        return await run_tool("ncentral_list_device_tasks", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_get_task(taskId: TaskId) -> str:
        """Get a scheduled task: name, type, item, org unit and devices."""

        async def action(client: NcentralClient) -> Any:
            return entity(await client.get(f"scheduled-tasks/{taskId}"))

        return await run_tool("ncentral_get_task", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_get_task_status(taskId: TaskId) -> str:
        """Get a task's status counts across its devices."""

        async def action(client: NcentralClient) -> Any:
            return entity(await client.get(f"scheduled-tasks/{taskId}/status"))

        return await run_tool("ncentral_get_task_status", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def ncentral_get_task_status_details(taskId: TaskId) -> str:
        """Get a task's status per device, with the script output and message."""

        async def action(client: NcentralClient) -> Any:
            return list_result(await client.get(f"scheduled-tasks/{taskId}/status/details"))

        return await run_tool("ncentral_get_task_status_details", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def ncentral_create_direct_task(
        name: Annotated[str, Field(description="Task name; must be unique.", min_length=1)],
        deviceId: DeviceId,
        itemId: Annotated[int, Field(description="Script or automation policy id in the N-central repository.", ge=1)],
        taskType: Annotated[TaskType | str, Field(description="What itemId is.")],
        customerId: Annotated[int, Field(description="Customer that owns the device.", ge=1)],
        credential: Annotated[
            TaskCredential | str,
            Field(description="Account the task runs as. A string is read as the object's JSON text or just its type."),
        ],
        parameters: Annotated[list[TaskParameter] | None, Field(description="Script / policy parameters.")] = None,
    ) -> str:
        """Run a script or automation policy on one device now. Only when the user explicitly asks.

        Returns the taskId; follow up with ncentral_get_task_status_details for the output.
        """

        async def action(client: NcentralClient) -> Any:
            run_as = _credential(credential)
            if run_as.type == "CustomCredentials" and not (run_as.username and run_as.password):
                raise ValueError("CustomCredentials needs credential.username and credential.password.")
            body: dict[str, Any] = {
                "name": name.strip(),
                "itemId": itemId,
                "taskType": enum_value(taskType, TaskType),
                "customerId": customerId,
                "deviceId": deviceId,
                "credential": run_as.model_dump(exclude_none=True),
            }
            if parameters:
                body["parameters"] = [
                    {
                        "name": p.name,
                        "value": p.value if p.value is not None else "",
                        "description": p.description or p.name,
                        "type": p.type or "string",
                    }
                    for p in parameters
                ]
            return entity(await client.post("scheduled-tasks/direct", body))

        return await run_tool("ncentral_create_direct_task", client_factory, action)
