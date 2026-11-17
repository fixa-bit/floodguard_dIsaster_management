"""The alarm automation routes against a fake n8n public API (no real n8n needed)."""
import json

import httpx
import pytest
from pydantic import SecretStr

from app.api.routes import alarm_automation
from app.core.config import Settings
from app.main import app
from app.services.n8n_alarm import N8nAlarmClient

WORKFLOW = {
    "id": "wf1", "name": "FloodGuard – Flood alarm & escalation", "active": True, "isArchived": False,
    "nodes": [
        {"id": "t1", "name": "Forecast webhook", "type": "n8n-nodes-base.webhook"},
        {"id": "t2", "name": "Mock Slack", "type": "n8n-nodes-base.webhook"},
        {"id": "n1", "name": "Alarm settings", "type": "n8n-nodes-base.code"},
        {"id": "n2", "name": "Decide action", "type": "n8n-nodes-base.code"},
        {"id": "n3", "name": "Send Gmail", "type": "n8n-nodes-base.emailSend", "disabled": False},
        {"id": "s1", "name": "Note", "type": "n8n-nodes-base.stickyNote"},
    ],
    "connections": {"Forecast webhook": {"main": [[{"node": "Alarm settings"}]]},
                    "Alarm settings": {"main": [[{"node": "Decide action"}]]},
                    "Decide action": {"main": [[{"node": "Send Gmail"}]]}},
    "nodeGroups": [{"id": "g1", "name": "Load settings", "nodeIds": ["n1"]},
                   {"id": "g2", "name": "Decide & notify", "description": "d", "nodeIds": ["n2", "n3"]}],
}


def run_data(nodes, error_node=None):
    return {name: [{"startTime": i, "executionTime": 5, "executionStatus": "success",
                    "data": {"main": [[{"json": {}}, {"json": {}}]]},
                    **({"error": {"message": "SMTP login failed"}} if name == error_node else {})}]
            for i, name in enumerate(nodes)}


EXECUTIONS = [
    {"id": 12, "status": "error", "mode": "webhook", "startedAt": "2026-11-17T07:00:00Z",
     "data": {"resultData": {"lastNodeExecuted": "Send Gmail",
                             "runData": run_data(["Forecast webhook", "Alarm settings", "Decide action", "Send Gmail"], "Send Gmail")}}},
    {"id": 11, "status": "success", "mode": "webhook", "data": {"resultData": {"runData": run_data(["Mock Slack"])}}},
]


class FakeN8n:
    def __init__(self):
        self.tables = {
            "duty_roster": [{"id": 1, "name": "Officer A", "tier": 1, "email": "a@example.org", "gmail_on": True}],
            "alert_channels": [{"id": 3, "level": 2, "slack": True, "gmail": True, "whatsapp": False}],
            "flood_alarms": [{"id": 7, "alarm_id": "FG-1", "status": "open", "level": 3, "tier": 1}],
            "alarm_events": [], "alarm_notifications": [],
        }
        self.ids = {name: f"id_{name}" for name in self.tables}
        self.calls = []

    def _table(self, request):
        table_id = request.url.path.split("/")[4]
        return next(name for name, i in self.ids.items() if i == table_id)

    @staticmethod
    def _match(rows, filter_json):
        filters = json.loads(filter_json)["filters"]
        return [r for r in rows if all(r.get(f["columnName"]) == f["value"] for f in filters)]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append((method, path))
        if path.startswith("/webhook/"):
            assert "x-n8n-api-key" not in request.headers
            if path.endswith("/flood-alarm/ack"):
                found = any(r["alarm_id"] == request.url.params["alarm_id"] for r in self.tables["flood_alarms"])
                return httpx.Response(200, text="Alarm acknowledged" if found else "Alarm not found")
            return httpx.Response(202, json={"http_status": 202, "received": 1})
        if request.headers.get("x-n8n-api-key") != "test-key":
            return httpx.Response(401, json={"message": "unauthorized"})
        if path == "/api/v1/workflows":
            return httpx.Response(200, json={"data": [{"id": "wf1", "isArchived": False, "active": True}]})
        if path == "/api/v1/workflows/wf1":
            return httpx.Response(200, json=WORKFLOW)
        if path == "/api/v1/executions":
            return httpx.Response(200, json={"data": EXECUTIONS})
        if path == "/api/v1/data-tables":
            return httpx.Response(200, json={"data": [{"name": n, "id": i} for n, i in self.ids.items()]})
        table = self._table(request)
        rows = self.tables[table]
        if path.endswith("/rows") and method == "GET":
            found = self._match(rows, request.url.params["filter"]) if "filter" in request.url.params else rows
            return httpx.Response(200, json={"data": found})
        if path.endswith("/rows") and method == "POST":
            row = {"id": 100 + len(rows), **json.loads(request.content)["data"][0]}
            rows.append(row)
            return httpx.Response(200, json=[row])
        if path.endswith("/rows/update"):
            body = json.loads(request.content)
            found = self._match(rows, json.dumps(body["filter"]))
            for row in found:
                row.update(body["data"])
            return httpx.Response(200, json=found)
        if path.endswith("/rows/delete"):
            found = self._match(rows, request.url.params["filter"])
            self.tables[table] = [r for r in rows if r not in found]
            return httpx.Response(200, json=found)
        return httpx.Response(404, json={"message": "unknown"})


@pytest.fixture
def n8n():
    fake = FakeN8n()
    settings = Settings(n8n_api_key=SecretStr("test-key"), n8n_api_url="http://n8n.test/api/v1",
                        n8n_webhook_url="http://n8n.test/webhook", n8n_editor_url="http://n8n.test")
    client = N8nAlarmClient(settings=settings, transport=httpx.MockTransport(fake))
    app.dependency_overrides[alarm_automation.get_client] = lambda: client
    yield fake
    app.dependency_overrides.pop(alarm_automation.get_client, None)


def test_workflow_layout_has_triggers_blocks_and_links(client, n8n):
    body = client.get("/api/v1/alarm-automation/workflow").json()
    assert [t["name"] for t in body["triggers"]] == ["Forecast webhook", "Mock Slack"]
    assert [b["name"] for b in body["blocks"]] == ["Load settings", "Decide & notify"]
    assert {"from": "Forecast webhook", "to": "Load settings"} in body["links"]
    assert {"from": "Load settings", "to": "Decide & notify"} in body["links"]


def test_runs_show_each_node_and_block_and_hide_mock_runs(client, n8n):
    runs = client.get("/api/v1/alarm-automation/runs").json()["runs"]
    assert [r["id"] for r in runs] == ["12"]
    run = runs[0]
    assert run["trigger"] == "Forecast webhook" and run["status"] == "error"
    assert run["blocks"] == {"Load settings": "success", "Decide & notify": "error"}
    gmail = next(n for n in run["nodes"] if n["name"] == "Send Gmail")
    assert gmail["error"] == "SMTP login failed" and gmail["items"] == 2
    assert len(client.get("/api/v1/alarm-automation/runs?include_mocks=true").json()["runs"]) == 2


def test_duty_roster_add_edit_and_remove(client, n8n):
    added = client.post("/api/v1/alarm-automation/duty-roster", json={"name": "Officer Z", "tier": 2, "whatsapp": "+92 300 1234567"})
    assert added.status_code == 201
    row = added.json()
    assert row["whatsapp"] == "+923001234567" and row["whatsapp_on"] is True and row["gmail_on"] is False
    edited = client.patch(f"/api/v1/alarm-automation/duty-roster/{row['id']}", json={"gmail_on": True, "email": "z@example.org"})
    assert edited.json()["gmail_on"] is True
    assert client.delete(f"/api/v1/alarm-automation/duty-roster/{row['id']}").status_code == 204
    assert [r["name"] for r in n8n.tables["duty_roster"]] == ["Officer A"]
    assert client.delete("/api/v1/alarm-automation/duty-roster/999").status_code == 404


def test_roster_rejects_bad_values(client, n8n):
    assert client.post("/api/v1/alarm-automation/duty-roster", json={"name": "X", "tier": 1, "email": "not-an-email"}).status_code == 422
    assert client.post("/api/v1/alarm-automation/duty-roster", json={"name": "X", "tier": 4}).status_code == 422
    assert client.patch("/api/v1/alarm-automation/duty-roster/1", json={"whatsapp": "call me"}).status_code == 422
    assert client.patch("/api/v1/alarm-automation/duty-roster/1", json={}).status_code == 422


def test_channel_toggles_and_unknown_tables(client, n8n):
    assert client.patch("/api/v1/alarm-automation/alert-channels/3", json={"whatsapp": True}).json()["whatsapp"] is True
    assert client.get("/api/v1/alarm-automation/tables/users").status_code == 422
    assert client.get("/api/v1/alarm-automation/tables/alert_channels").json()["rows"][0]["whatsapp"] is True


def test_resolve_closes_alarm_and_records_event(client, n8n):
    response = client.post("/api/v1/alarm-automation/alarms/FG-1/resolve", json={"by": "Control room"})
    assert response.json()["status"] == "resolved"
    assert n8n.tables["flood_alarms"][0]["status"] == "resolved"
    event = n8n.tables["alarm_events"][0]
    assert event["event"] == "resolved" and event["actor"] == "Control room" and event["alarm_id"] == "FG-1"
    assert client.post("/api/v1/alarm-automation/alarms/FG-404/resolve", json={}).status_code == 404


def test_acknowledge_goes_through_workflow_link_without_api_key(client, n8n):
    assert client.post("/api/v1/alarm-automation/alarms/FG-1/acknowledge", json={"by": "Officer A"}).json()["status"] == "acknowledged"
    assert client.post("/api/v1/alarm-automation/alarms/FG-404/acknowledge", json={}).status_code == 404
    assert ("GET", "/webhook/flood-alarm/ack") in n8n.calls


def test_status_reports_missing_or_wrong_key(client):
    for key in ("", "wrong"):
        settings = Settings(n8n_api_key=SecretStr(key), n8n_api_url="http://n8n.test/api/v1")
        app.dependency_overrides[alarm_automation.get_client] = lambda s=settings: N8nAlarmClient(settings=s, transport=httpx.MockTransport(FakeN8n()))
        body = client.get("/api/v1/alarm-automation/status").json()
        assert body["connected"] is False and "N8N_API_KEY" in body["message"]
        assert client.get("/api/v1/alarm-automation/workflow").status_code == 503
    app.dependency_overrides.pop(alarm_automation.get_client, None)
