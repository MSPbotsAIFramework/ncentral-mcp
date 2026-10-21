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
"""Authentication, request shapes and retries against a mocked N-central API."""

import json

import httpx
import pytest

from ncentral_mcp import api_client
from ncentral_mcp.api_client import NcentralClient, NcentralCredentials, NcentralError
from ncentral_mcp.server import _credentials_var, create_mcp_server

CREDS = NcentralCredentials(server_url="https://ncentral.example.com", jwt="jwt-123")
AUTH = {"tokens": {"access": {"token": "access-1", "type": "Bearer", "expirySeconds": 3600},
                   "refresh": {"token": "refresh-1", "type": "Bearer"}}}
PAGE = {"data": [{"id": 1}], "pageNumber": 1, "pageSize": 50, "itemCount": 1, "totalItems": 1, "totalPages": 1, "_links": {}}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(api_client.asyncio, "sleep", instant)


class Recorder:
    """Mock transport: answers authenticate, then replies by "METHOD path" or path below /api/."""

    def __init__(self, routes=None, default=None, auth=None):
        self.requests: list[httpx.Request] = []
        self.routes = routes or {}
        self.default = default if default is not None else PAGE
        self.auth = auth

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/api/").removeprefix("/api")
        if path == "auth/authenticate":
            return self.auth(request) if callable(self.auth) else httpx.Response(200, json=AUTH)
        reply = self.routes.get(f"{request.method} {path}", self.routes.get(path, self.default))
        if callable(reply):
            return reply(request)
        return httpx.Response(200, json=reply)

    def calls(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path == f"/api/{path}"]

    def last(self) -> httpx.Request:
        return self.requests[-1]


def body(request: httpx.Request):
    return json.loads(request.content) if request.content else None


async def _call(monkeypatch, recorder: Recorder, tool: str, args: dict):
    http = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    monkeypatch.setattr(api_client, "_get_shared_http_client", lambda: http)
    ctx = _credentials_var.set(CREDS)
    try:
        content, _ = await create_mcp_server().call_tool(tool, args)
    finally:
        _credentials_var.reset(ctx)
    return json.loads(content[0].text)


def _client(recorder: Recorder) -> NcentralClient:
    return NcentralClient(CREDS, httpx.AsyncClient(transport=httpx.MockTransport(recorder)))


# ---- authentication --------------------------------------------------------


async def test_jwt_is_exchanged_for_access_token_once():
    rec = Recorder()
    client = _client(rec)
    await client.get("devices")
    await client.get("customers")
    auth = rec.calls("POST", "auth/authenticate")
    assert len(auth) == 1
    assert auth[0].headers["Authorization"] == "Bearer jwt-123"
    assert rec.last().headers["Authorization"] == "Bearer access-1"
    assert str(rec.requests[1].url) == "https://ncentral.example.com/api/devices"


async def test_rejected_jwt_is_unauthorized(monkeypatch):
    rec = Recorder(auth=lambda r: httpx.Response(401, json={"message": "Invalid token jwt-123"}))
    result = await _call(monkeypatch, rec, "ncentral_status", {})
    assert result["error"]["code"] == "unauthorized"
    assert "jwt-123" not in result["error"]["message"]


async def test_expired_access_token_is_renewed_once():
    replies = iter([httpx.Response(401), httpx.Response(200, json=PAGE)])
    rec = Recorder({"devices": lambda r: next(replies)})
    await _client(rec).get("devices")
    assert len(rec.calls("POST", "auth/authenticate")) == 2
    assert len(rec.calls("GET", "devices")) == 2


async def test_get_retries_5xx():
    replies = iter([httpx.Response(503), httpx.Response(200, json=PAGE)])
    rec = Recorder({"devices": lambda r: next(replies)})
    await _client(rec).get("devices")
    assert len(rec.calls("GET", "devices")) == 2


async def test_writes_are_not_retried_on_5xx():
    rec = Recorder({"POST scheduled-tasks/direct": lambda r: httpx.Response(500, json={"message": "boom"})})
    with pytest.raises(NcentralError):
        await _client(rec).post("scheduled-tasks/direct", {})
    assert len(rec.calls("POST", "scheduled-tasks/direct")) == 1


async def test_html_error_page_is_not_echoed():
    rec = Recorder({"devices/9": lambda r: httpx.Response(404, text="<html><body>Not Found</body></html>")})
    with pytest.raises(NcentralError) as err:
        await _client(rec).get("devices/9")
    assert err.value.message == "N-central returned HTTP 404 for devices/9"


# ---- reads -----------------------------------------------------------------


async def test_list_devices_paging_and_filter(monkeypatch):
    rec = Recorder()
    result = await _call(monkeypatch, rec, "ncentral_list_devices",
                         {"filterId": 7, "pageNumber": 2, "pageSize": 10, "sortBy": "longName", "sortOrder": "descending"})
    assert dict(rec.last().url.params) == {"filterId": "7", "pageNumber": "2", "pageSize": "10", "sortBy": "longName", "sortOrder": "desc"}
    assert result["summary"]["count"] == 1 and "_links" not in result


@pytest.mark.parametrize(
    "tool,args,path",
    [("ncentral_list_customers", {}, "customers"),
     ("ncentral_list_customers", {"soId": 50}, "service-orgs/50/customers"),
     ("ncentral_list_sites", {}, "sites"),
     ("ncentral_list_sites", {"customerId": 100}, "customers/100/sites"),
     ("ncentral_list_devices_by_org_unit", {"orgUnitId": 100}, "org-units/100/devices"),
     ("ncentral_list_active_issues", {"orgUnitId": 100}, "org-units/100/active-issues"),
     ("ncentral_list_access_groups", {"orgUnitId": 100}, "org-units/100/access-groups"),
     ("ncentral_list_org_custom_properties", {"orgUnitId": 100}, "org-units/100/custom-properties"),
     ("ncentral_list_org_unit_children", {"orgUnitId": 1}, "org-units/1/children")],
)
async def test_list_paths(monkeypatch, tool, args, path):
    rec = Recorder()
    await _call(monkeypatch, rec, tool, args)
    assert rec.last().url.path == f"/api/{path}"
    assert rec.last().url.params["pageSize"] == "50"


@pytest.mark.parametrize(
    "tool,args,path",
    [("ncentral_get_device", {"deviceId": 9}, "devices/9"),
     ("ncentral_get_device_lifecycle", {"deviceId": 9}, "devices/9/assets/lifecycle-info"),
     ("ncentral_get_device_service_status", {"deviceId": 9}, "devices/9/service-monitor-status"),
     ("ncentral_list_device_tasks", {"deviceId": 9}, "devices/9/scheduled-tasks"),
     ("ncentral_list_maintenance_windows", {"deviceId": 9}, "devices/9/maintenance-windows"),
     ("ncentral_list_job_statuses", {"orgUnitId": 3}, "org-units/3/job-statuses"),
     ("ncentral_get_task_status_details", {"taskId": 5}, "scheduled-tasks/5/status/details"),
     ("ncentral_get_registration_token", {"kind": "org-unit", "id": 3}, "org-units/3/registration-token"),
     ("ncentral_get_registration_token", {"kind": "site", "id": 4}, "sites/4/registration-token"),
     ("ncentral_validate_token", {}, "auth/validate")],
)
async def test_get_paths(monkeypatch, tool, args, path):
    rec = Recorder(default={"data": {"ok": True}, "_links": {}})
    result = await _call(monkeypatch, rec, tool, args)
    assert rec.last().url.path == f"/api/{path}"
    assert "error" not in result


async def test_server_info_tolerates_missing_extra(monkeypatch):
    rec = Recorder({"server-info": {"message": "API-Service 1.0"},
                    "server-info/extra": lambda r: httpx.Response(404, json={"message": "nope"})})
    result = await _call(monkeypatch, rec, "ncentral_server_info", {})
    assert result == {"message": "API-Service 1.0"}


# ---- writes ----------------------------------------------------------------


async def test_update_lifecycle_patches_given_fields(monkeypatch):
    rec = Recorder({"PATCH devices/9/assets/lifecycle-info": lambda r: httpx.Response(204)})
    result = await _call(monkeypatch, rec, "ncentral_update_device_lifecycle",
                         {"deviceId": 9, "data": {"warrantyExpiryDate": "2027-01-31", "cost": 1200}})
    assert body(rec.calls("PATCH", "devices/9/assets/lifecycle-info")[0]) == {"warrantyExpiryDate": "2027-01-31", "cost": 1200}
    assert result == {"updated": True, "deviceId": 9, "fields": ["cost", "warrantyExpiryDate"]}


async def test_update_lifecycle_rejects_unknown_field(monkeypatch):
    rec = Recorder()
    result = await _call(monkeypatch, rec, "ncentral_update_device_lifecycle", {"deviceId": 9, "data": {"warranty": "x"}})
    assert result["error"]["code"] == "invalid_argument"
    assert not rec.calls("PATCH", "devices/9/assets/lifecycle-info")


@pytest.mark.parametrize(
    "tool,args,path",
    [("ncentral_update_device_custom_property", {"deviceId": 9, "propertyId": 2, "value": "x"}, "devices/9/custom-properties/2"),
     ("ncentral_update_org_custom_property", {"orgUnitId": 3, "propertyId": 2, "value": "x"}, "org-units/3/custom-properties/2")],
)
async def test_custom_property_update(monkeypatch, tool, args, path):
    rec = Recorder({f"PUT {path}": {"_warnings": ["heads up"]}})
    result = await _call(monkeypatch, rec, tool, args)
    assert body(rec.calls("PUT", path)[0]) == {"value": "x"}
    assert result["updated"] is True and result["warnings"] == ["heads up"]


async def test_direct_task_body(monkeypatch):
    rec = Recorder({"POST scheduled-tasks/direct": {"data": {"taskId": 77}, "_links": {}}})
    args = {"name": "Clear temp", "deviceId": 9, "itemId": 1001, "taskType": "Script", "customerId": 100,
            "credential": {"type": "LocalSystem"}, "parameters": [{"name": "Path", "value": "C:\\Temp"}]}
    result = await _call(monkeypatch, rec, "ncentral_create_direct_task", args)
    assert body(rec.calls("POST", "scheduled-tasks/direct")[0]) == {
        "name": "Clear temp", "itemId": 1001, "taskType": "Script", "customerId": 100, "deviceId": 9,
        "credential": {"type": "LocalSystem"},
        "parameters": [{"name": "Path", "value": "C:\\Temp", "description": "Path", "type": "string"}],
    }
    assert result == {"taskId": 77}


async def test_direct_task_custom_credentials_need_login(monkeypatch):
    rec = Recorder()
    args = {"name": "x", "deviceId": 9, "itemId": 1, "taskType": "Script", "customerId": 1, "credential": {"type": "CustomCredentials"}}
    result = await _call(monkeypatch, rec, "ncentral_create_direct_task", args)
    assert result["error"]["code"] == "invalid_argument"
    assert not rec.calls("POST", "scheduled-tasks/direct")


async def test_add_maintenance_windows(monkeypatch):
    rec = Recorder({"POST devices/maintenance-windows": {"success": True}})
    window = {"name": "Patch Sunday", "type": "action", "cron": "0 0 2 ? * SUN", "duration": 120, "enabled": True,
              "applicableAction": [{"type": "patch", "actions": ["install"]}]}
    await _call(monkeypatch, rec, "ncentral_add_maintenance_windows", {"deviceIds": [9, 10], "windows": [window]})
    assert body(rec.calls("POST", "devices/maintenance-windows")[0]) == {"deviceIDs": [9, 10], "maintenanceWindows": [window]}


async def test_add_maintenance_window_needs_required_fields(monkeypatch):
    rec = Recorder()
    result = await _call(monkeypatch, rec, "ncentral_add_maintenance_windows", {"deviceIds": [9], "windows": [{"name": "x"}]})
    assert result["error"]["code"] == "invalid_argument"
    assert "cron" in result["error"]["message"]


async def test_delete_maintenance_windows_needs_confirm(monkeypatch):
    rec = Recorder({"DELETE devices/maintenance-windows": {"success": True}})
    result = await _call(monkeypatch, rec, "ncentral_delete_maintenance_windows", {"scheduleIds": [5]})
    assert result["error"]["code"] == "invalid_argument"
    assert not rec.calls("DELETE", "devices/maintenance-windows")
    result = await _call(monkeypatch, rec, "ncentral_delete_maintenance_windows", {"scheduleIds": [5], "confirm": True})
    assert body(rec.calls("DELETE", "devices/maintenance-windows")[0]) == {"scheduleIds": [5]}
    assert result == {"success": True}


async def test_create_org_unit_access_group(monkeypatch):
    rec = Recorder({"POST org-units/3/access-groups": lambda r: httpx.Response(201, content=b"")})
    args = {"orgUnitId": 3, "groupName": " Techs ", "groupDescription": "Tier 1", "orgUnitIds": ["100", 101],
            "autoIncludeNewOrgUnits": "true"}
    result = await _call(monkeypatch, rec, "ncentral_create_org_unit_access_group", args)
    assert body(rec.calls("POST", "org-units/3/access-groups")[0]) == {
        "groupName": "Techs", "groupDescription": "Tier 1", "orgUnitIds": ["100", "101"], "autoIncludeNewOrgUnits": "true"
    }
    assert result["created"] is True


async def test_create_device_access_group(monkeypatch):
    rec = Recorder({"POST org-units/3/device-access-groups": lambda r: httpx.Response(201, content=b"")})
    await _call(monkeypatch, rec, "ncentral_create_device_access_group",
                {"orgUnitId": 3, "groupName": "Servers", "groupDescription": "", "deviceIds": ["9"]})
    assert body(rec.calls("POST", "org-units/3/device-access-groups")[0]) == {
        "groupName": "Servers", "groupDescription": "", "deviceIds": ["9"]
    }


async def test_wrong_server_url_is_explained(monkeypatch):
    rec = Recorder(auth=lambda r: httpx.Response(405, text="<html>Method Not Allowed</html>"))
    result = await _call(monkeypatch, rec, "ncentral_status", {})
    assert result["error"]["code"] == "invalid_argument"
    assert "X-Ncentral-Server-Url" in result["error"]["message"]


# ---- compatibility: credential as object or text; free-text enum values ---------------------


@pytest.mark.parametrize(
    "credential,sent",
    [
        ({"type": "LocalSystem"}, {"type": "LocalSystem"}),
        ('{"type": "CustomCredentials", "username": "svc", "password": "pw"}',
         {"type": "CustomCredentials", "username": "svc", "password": "pw"}),
        ("localsystem", {"type": "LocalSystem"}),
        (" DeviceCredentials ", {"type": "DeviceCredentials"}),
    ],
)
async def test_direct_task_credential_object_or_text(monkeypatch, credential, sent):
    rec = Recorder({"POST scheduled-tasks/direct": {"data": {"taskId": 77}}})
    args = {"name": "x", "deviceId": 9, "itemId": 1, "taskType": "Script", "customerId": 1, "credential": credential}
    await _call(monkeypatch, rec, "ncentral_create_direct_task", args)
    assert body(rec.calls("POST", "scheduled-tasks/direct")[0])["credential"] == sent


async def test_direct_task_unreadable_credential_text(monkeypatch):
    rec = Recorder()
    args = {"name": "x", "deviceId": 9, "itemId": 1, "taskType": "Script", "customerId": 1, "credential": "{bad"}
    result = await _call(monkeypatch, rec, "ncentral_create_direct_task", args)
    assert result["error"]["code"] == "invalid_argument"
    assert not rec.calls("POST", "scheduled-tasks/direct")


@pytest.mark.parametrize("given,sent", [("script", "Script"), ("AUTOMATIONPOLICY", "AutomationPolicy"), ("PowerShell", "PowerShell")])
async def test_direct_task_type_normalized_or_passed_through(monkeypatch, given, sent):
    rec = Recorder({"POST scheduled-tasks/direct": {"data": {"taskId": 77}}})
    args = {"name": "x", "deviceId": 9, "itemId": 1, "taskType": given, "customerId": 1, "credential": {"type": "LocalSystem"}}
    await _call(monkeypatch, rec, "ncentral_create_direct_task", args)
    assert body(rec.calls("POST", "scheduled-tasks/direct")[0])["taskType"] == sent


@pytest.mark.parametrize("given,sent", [("True", "true"), ("FALSE", "false"), ("yes", "yes")])
async def test_access_group_auto_include_normalized_or_passed_through(monkeypatch, given, sent):
    rec = Recorder({"POST org-units/3/access-groups": lambda r: httpx.Response(201, content=b"")})
    args = {"orgUnitId": 3, "groupName": "Techs", "groupDescription": "", "autoIncludeNewOrgUnits": given}
    await _call(monkeypatch, rec, "ncentral_create_org_unit_access_group", args)
    assert body(rec.calls("POST", "org-units/3/access-groups")[0])["autoIncludeNewOrgUnits"] == sent
