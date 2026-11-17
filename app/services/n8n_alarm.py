"""Client for the n8n flood alarm workflow (automation/n8n), through n8n's public API.

The FloodGuard app uses it to show the workflow's runs node by node and to edit the
alarm data tables (duty roster, channels per level, alarms). The API key never leaves
the server.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import Settings, get_settings

TRIGGER_TYPES = ("Trigger", "webhook")


class N8nError(Exception):
    """n8n could not be used: not configured, not running, or it refused the request."""

    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.status = status


@dataclass
class N8nAlarmClient:
    settings: Settings = field(default_factory=get_settings)
    transport: httpx.AsyncBaseTransport | None = None
    _table_ids: dict[str, str] = field(default_factory=dict)
    _tables_at: float = 0.0

    async def _request(self, method: str, path: str, *, params: dict | None = None, body: Any = None,
                       base: str | None = None, auth: bool = True) -> Any:
        key = self.settings.n8n_api_key.get_secret_value()
        if auth and not key:
            raise N8nError("n8n is not connected: set N8N_API_KEY in the backend .env (n8n: Settings > n8n API).")
        headers = {"X-N8N-API-KEY": key} if auth else {}
        url = (base or self.settings.n8n_api_url).rstrip("/") + path
        try:
            async with httpx.AsyncClient(timeout=self.settings.n8n_timeout_seconds, transport=self.transport) as client:
                response = await client.request(method, url, params=params, json=body, headers=headers)
        except httpx.HTTPError as error:
            raise N8nError(f"Cannot reach n8n at {self.settings.n8n_editor_url}: is it running? ({error.__class__.__name__})") from error
        if response.status_code == 401:
            raise N8nError("n8n refused the API key: create a new one in n8n (Settings > n8n API) and update N8N_API_KEY.")
        if response.status_code >= 400:
            try:
                message = response.json().get("message") or response.text
            except ValueError:
                message = response.text
            raise N8nError(f"n8n error {response.status_code}: {str(message)[:300]}", 502 if response.status_code >= 500 else 400)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    # ---- workflow and runs -------------------------------------------------
    async def workflow(self) -> dict:
        found = await self._request("GET", "/workflows", params={"name": self.settings.n8n_alarm_workflow_name, "limit": 50})
        candidates = [w for w in found.get("data", []) if not w.get("isArchived")]
        if not candidates:
            raise N8nError(f'No workflow named "{self.settings.n8n_alarm_workflow_name}" in n8n: import automation/n8n/floodguard-flood-alarm.workflow.json.', 404)
        candidates.sort(key=lambda w: (not w.get("active"), w.get("updatedAt", "")))
        return await self._request("GET", f"/workflows/{candidates[0]['id']}")

    async def executions(self, workflow_id: str, limit: int) -> list[dict]:
        result = await self._request("GET", "/executions", params={"workflowId": workflow_id, "limit": limit, "includeData": "true"})
        return result.get("data", [])

    async def execution(self, execution_id: str) -> dict:
        return await self._request("GET", f"/executions/{execution_id}", params={"includeData": "true"})

    # ---- data tables -------------------------------------------------------
    async def table_id(self, name: str) -> str:
        if name not in self._table_ids or time.monotonic() - self._tables_at > 300:
            found = await self._request("GET", "/data-tables", params={"limit": 100})
            self._table_ids = {t["name"]: t["id"] for t in found.get("data", [])}
            self._tables_at = time.monotonic()
        if name not in self._table_ids:
            raise N8nError(f'n8n has no "{name}" data table: run "Set up & test" in the alarm workflow once.', 404)
        return self._table_ids[name]

    @staticmethod
    def _by_id(row_id: int) -> str:
        return json.dumps({"type": "and", "filters": [{"columnName": "id", "condition": "eq", "value": row_id}]})

    async def rows(self, table: str, limit: int = 200, sort: str | None = None, filters: list[dict] | None = None) -> list[dict]:
        params: dict[str, Any] = {"limit": min(limit, 250)}
        if sort:
            params["sortBy"] = sort
        if filters:
            params["filter"] = json.dumps({"type": "and", "filters": filters})
        result = await self._request("GET", f"/data-tables/{await self.table_id(table)}/rows", params=params)
        return result.get("data", [])

    async def insert_row(self, table: str, data: dict) -> dict:
        result = await self._request("POST", f"/data-tables/{await self.table_id(table)}/rows",
                                     body={"data": [data], "returnType": "all"})
        return result[0] if isinstance(result, list) and result else data

    async def update_row(self, table: str, row_id: int, data: dict) -> dict:
        body = {"filter": json.loads(self._by_id(row_id)), "data": data, "returnData": True}
        result = await self._request("PATCH", f"/data-tables/{await self.table_id(table)}/rows/update", body=body)
        if isinstance(result, list):
            if not result:
                raise N8nError(f"No row {row_id} in {table}.", 404)
            return result[0]
        return {"id": row_id, **data}

    async def delete_row(self, table: str, row_id: int) -> None:
        result = await self._request("DELETE", f"/data-tables/{await self.table_id(table)}/rows/delete",
                                     params={"filter": self._by_id(row_id), "returnData": "true"})
        if isinstance(result, list) and not result:
            raise N8nError(f"No row {row_id} in {table}.", 404)

    # ---- the workflow's own webhooks (no API key needed) --------------------
    async def acknowledge(self, alarm_id: str, by: str) -> str:
        return await self._request("GET", "/flood-alarm/ack", params={"alarm_id": alarm_id, "by": by},
                                   base=self.settings.n8n_webhook_url, auth=False)

    async def send_forecasts(self, forecasts: list[dict]) -> dict:
        return await self._request("POST", "/flood-forecast", body={"source": "floodguard-app (test)", "forecasts": forecasts},
                                   base=self.settings.n8n_webhook_url, auth=False)


# ---- shaping n8n's data for the app ----------------------------------------
def is_trigger(node: dict) -> bool:
    return node.get("type", "").endswith(TRIGGER_TYPES)


def workflow_layout(workflow: dict) -> dict:
    """The workflow as the app draws it: triggers, then the node groups ("blocks") in order."""
    nodes = {n["id"]: n for n in workflow.get("nodes", []) if n.get("type") != "n8n-nodes-base.stickyNote"}
    grouped: set[str] = set()
    blocks = []
    for group in workflow.get("nodeGroups") or []:
        members = [nodes[i] for i in group.get("nodeIds", []) if i in nodes]
        grouped.update(n["id"] for n in members)
        blocks.append({"name": group["name"], "description": group.get("description") or "",
                       "nodes": [{"name": n["name"], "type": n["type"].split(".")[-1], "disabled": bool(n.get("disabled"))} for n in members]})
    loose = [n for i, n in nodes.items() if i not in grouped]
    by_name = {n["name"]: n for n in nodes.values()}
    block_of = {n["name"]: b["name"] for b in blocks for n in b["nodes"]}
    # Which blocks lead into which, from the connections (for drawing the flow).
    links: set[tuple[str, str]] = set()
    for source, outputs in (workflow.get("connections") or {}).items():
        for output in outputs.get("main", []) or []:
            for link in output or []:
                a = block_of.get(source) or (source if source in by_name else None)
                b = block_of.get(link["node"]) or link["node"]
                if a and b and a != b:
                    links.add((a, b))
    return {
        "id": workflow["id"], "name": workflow["name"], "active": bool(workflow.get("active")),
        "triggers": [{"name": n["name"], "type": n["type"].split(".")[-1]} for n in loose if is_trigger(n)],
        "blocks": blocks,
        "other_nodes": [n["name"] for n in loose if not is_trigger(n)],
        "links": sorted([{"from": a, "to": b} for a, b in links], key=lambda x: (x["from"], x["to"])),
    }


def summarize_execution(execution: dict, layout: dict) -> dict:
    """One run: which trigger started it, and each node's and block's status."""
    run_data = (((execution.get("data") or {}).get("resultData") or {}).get("runData")) or {}
    block_of = {n["name"]: b["name"] for b in layout["blocks"] for n in b["nodes"]}
    trigger_names = {t["name"] for t in layout["triggers"]}
    nodes = []
    for name, runs in run_data.items():
        items = sum(len(output or []) for run in runs for output in ((run.get("data") or {}).get("main") or []))
        error = next((run.get("error") for run in runs if run.get("error")), None)
        nodes.append({
            "name": name, "block": block_of.get(name),
            "status": "error" if error else (runs[-1].get("executionStatus") or "success"),
            "items": items, "ms": sum(int(run.get("executionTime") or 0) for run in runs),
            "started_at": runs[0].get("startTime"),
            "error": (error.get("message") if isinstance(error, dict) else str(error))[:300] if error else None,
        })
    nodes.sort(key=lambda n: n["started_at"] or 0)
    blocks = {}
    for node in nodes:
        if node["block"]:
            current = blocks.get(node["block"], "success")
            blocks[node["block"]] = "error" if "error" in (current, node["status"]) else "success"
    status = execution.get("status") or ("success" if execution.get("finished") else "running")
    trigger = next((n["name"] for n in nodes if n["name"] in trigger_names), None)
    return {
        "id": str(execution["id"]), "status": status, "mode": execution.get("mode"),
        "trigger": trigger, "started_at": execution.get("startedAt"), "stopped_at": execution.get("stoppedAt"),
        "last_node": (((execution.get("data") or {}).get("resultData") or {}).get("lastNodeExecuted")),
        "blocks": blocks, "nodes": nodes,
        "is_mock": trigger in ("Mock Slack", "Mock backend"),
    }
