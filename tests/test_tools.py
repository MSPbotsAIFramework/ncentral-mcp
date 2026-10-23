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
"""tools/list snapshot, helpers and error-envelope mapping. No network access."""

import asyncio
import json

import pytest

from ncentral_mcp.api_client import NcentralError
from ncentral_mcp.server import INSTRUCTIONS, create_mcp_server
from ncentral_mcp.tools._common import entity, list_result, page_params

# Tool names are a public contract: existing agents and tenant connections
# depend on them. Changing this snapshot is a breaking change.
EXPECTED_TOOLS: dict[str, set[str]] = {
    "ncentral_navigate": set(),
    "ncentral_status": set(),
    "ncentral_health": set(),
    "ncentral_server_info": set(),
    "ncentral_validate_token": set(),
    "ncentral_list_service_orgs": set(),
    "ncentral_list_customers": set(),
    "ncentral_get_customer": {"customerId"},
    "ncentral_list_sites": set(),
    "ncentral_get_site": {"siteId"},
    "ncentral_list_org_units": set(),
    "ncentral_get_org_unit": {"orgUnitId"},
    "ncentral_list_org_unit_children": {"orgUnitId"},
    "ncentral_get_registration_token": {"kind", "id"},
    "ncentral_list_devices": set(),
    "ncentral_get_device": {"deviceId"},
    "ncentral_get_device_assets": {"deviceId"},
    "ncentral_get_device_lifecycle": {"deviceId"},
    "ncentral_update_device_lifecycle": {"deviceId", "data"},
    "ncentral_get_device_service_status": {"deviceId"},
    "ncentral_list_devices_by_org_unit": {"orgUnitId"},
    "ncentral_list_device_filters": set(),
    "ncentral_list_active_issues": {"orgUnitId"},
    "ncentral_list_job_statuses": {"orgUnitId"},
    "ncentral_list_device_tasks": {"deviceId"},
    "ncentral_get_task": {"taskId"},
    "ncentral_get_task_status": {"taskId"},
    "ncentral_get_task_status_details": {"taskId"},
    "ncentral_create_direct_task": {"name", "deviceId", "itemId", "taskType", "customerId", "credential"},
    "ncentral_list_org_custom_properties": {"orgUnitId"},
    "ncentral_get_org_custom_property": {"orgUnitId", "propertyId"},
    "ncentral_update_org_custom_property": {"orgUnitId", "propertyId", "value"},
    "ncentral_list_device_custom_properties": {"deviceId"},
    "ncentral_get_device_custom_property": {"deviceId", "propertyId"},
    "ncentral_update_device_custom_property": {"deviceId", "propertyId", "value"},
    "ncentral_list_maintenance_windows": {"deviceId"},
    "ncentral_add_maintenance_windows": {"deviceIds", "windows"},
    "ncentral_delete_maintenance_windows": {"scheduleIds"},
    "ncentral_list_access_groups": {"orgUnitId"},
    "ncentral_get_access_group": {"accessGroupId"},
    "ncentral_create_device_access_group": {"orgUnitId", "groupName", "groupDescription"},
    "ncentral_create_org_unit_access_group": {"orgUnitId", "groupName", "groupDescription"},
}
WRITE_TOOLS = {
    "ncentral_update_device_lifecycle",
    "ncentral_create_direct_task",
    "ncentral_update_org_custom_property",
    "ncentral_update_device_custom_property",
    "ncentral_add_maintenance_windows",
    "ncentral_delete_maintenance_windows",
    "ncentral_create_device_access_group",
    "ncentral_create_org_unit_access_group",
}
# Deletes, and updates that overwrite an existing value.
DESTRUCTIVE = {
    "ncentral_update_device_lifecycle",
    "ncentral_update_org_custom_property",
    "ncentral_update_device_custom_property",
    "ncentral_delete_maintenance_windows",
}


@pytest.fixture(scope="module")
def tools():
    return {t.name: t for t in asyncio.run(create_mcp_server().list_tools())}


def test_tool_names_are_stable(tools):
    assert set(tools) == set(EXPECTED_TOOLS)


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_required_params(tools, name):
    assert set(tools[name].inputSchema.get("required", [])) == EXPECTED_TOOLS[name]


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_description_budget(tools, name):
    description = (tools[name].description or "").strip()
    assert description, f"{name} has no description"
    assert len(description) <= 500
    assert len(description.splitlines()[0]) <= 100


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_annotations_match_side_effects(tools, name):
    annotations = tools[name].annotations
    assert annotations.readOnlyHint is (name not in WRITE_TOOLS)
    assert bool(annotations.destructiveHint) is (name in DESTRUCTIVE)


@pytest.mark.parametrize("name", sorted(WRITE_TOOLS))
def test_write_tools_say_when_to_use_them(tools, name):
    assert "explicitly asks" in tools[name].description


def test_list_tools_take_paging(tools):
    properties = tools["ncentral_list_devices"].inputSchema["properties"]
    assert {"filterId", "pageNumber", "pageSize", "sortBy", "sortOrder"} <= set(properties)


def test_page_size_is_capped_at_200(tools):
    paged = [t for t in tools.values() if "pageSize" in t.inputSchema["properties"]]
    assert len(paged) == 11
    for tool in paged:
        assert tool.inputSchema["properties"]["pageSize"]["anyOf"][0]["maximum"] == 200, tool.name
    content, _ = asyncio.run(create_mcp_server().call_tool("ncentral_list_devices", {"pageSize": 201}))
    error = json.loads(content[0].text)["error"]
    assert error["code"] == "invalid_argument" and "less than or equal to 200" in error["message"]


def test_instructions_budget():
    assert len(INSTRUCTIONS) <= 1500


@pytest.mark.parametrize(
    "status,code,retryable",
    [(401, "unauthorized", False), (403, "unauthorized", False), (404, "not_found", False),
     (400, "invalid_argument", False), (429, "rate_limited", True), (500, "upstream_error", True), (0, "upstream_error", True)],
)
def test_error_envelope(status, code, retryable):
    envelope = json.loads(NcentralError(status, "boom").to_envelope())
    assert envelope == {"error": {"code": code, "message": "boom", "retryable": retryable}}


def test_tool_without_credentials_returns_not_configured():
    content, _ = asyncio.run(create_mcp_server().call_tool("ncentral_status", {}))
    assert json.loads(content[0].text)["error"]["code"] == "not_configured"


def test_navigate_is_local():
    content, _ = asyncio.run(create_mcp_server().call_tool("ncentral_navigate", {"domain": "maintenance"}))
    assert "ncentral_delete_maintenance_windows" in json.loads(content[0].text)["tools"]
    content, _ = asyncio.run(create_mcp_server().call_tool("ncentral_navigate", {}))
    assert set(json.loads(content[0].text)) >= {"orgs", "devices", "access-groups"}


@pytest.mark.parametrize("order,expected", [("descending", "desc"), ("reverse", "desc"), ("natural", "asc"), (None, None)])
def test_page_params_sort_order(order, expected):
    params = page_params(None, None, "longName", order)
    assert params.get("sortOrder") == expected
    assert params["pageSize"] == 50


def test_list_result_summary():
    shaped = list_result({"data": [{"a": 1}], "pageNumber": 1, "totalPages": 3, "totalItems": 120, "_links": {"x": "y"}})
    assert shaped["summary"] == {"count": 1, "total": 120, "page": 1, "total_pages": 3, "has_more": True, "next_page": 2}
    assert "_links" not in shaped


def test_entity_unwraps_data():
    assert entity({"data": {"id": 1}, "_links": {}}) == {"id": 1}
    assert entity({"name": "x"}) == {"name": "x"}
