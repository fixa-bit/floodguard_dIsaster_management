"""The n8n flood alarm workflow, seen and edited from the FloodGuard app.

Runs (node by node) come from n8n's executions; the duty roster, channels per level
and alarms are n8n data tables, edited here through n8n's public API.

Every successful read is also saved on disk. When n8n cannot be reached, the reads answer
with that saved copy (marked ``offline`` with its ``saved_at`` time), so the app still shows
the roster, channels, alarms, runs and logs as they last were; nothing new arrives and
nothing can be changed until n8n is back.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.core.config import get_settings
from app.providers import last_good_store
from app.services.n8n_alarm import N8nAlarmClient, N8nError, summarize_execution, workflow_layout

router = APIRouter(prefix="/alarm-automation", tags=["Alarm automation"])

TableName = Literal["duty_roster", "alert_channels", "flood_alarms", "alarm_events", "alarm_notifications"]
# Newest first for the history tables; the roster and channels in their natural order.
TABLE_SORT = {"duty_roster": "tier:asc", "alert_channels": "level:asc", "flood_alarms": "updatedAt:desc",
              "alarm_events": "id:desc", "alarm_notifications": "id:desc"}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE = re.compile(r"^\+?[0-9]{8,15}$")

_client = N8nAlarmClient()


def get_client() -> N8nAlarmClient:
    return _client


def _fail(error: N8nError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=str(error))


# Saved copies of the reads, served while n8n is unreachable (kept for a year: it is history).
SNAPSHOT_MAX_AGE_HOURS = 24 * 365


def _snapshot_name(key: str) -> str:
    return f"n8n-alarm-{key}"


def _remember(key: str, payload: dict) -> dict:
    last_good_store.save(_snapshot_name(key), payload)
    return payload


def _saved_or_fail(key: str, error: N8nError) -> dict:
    """The last saved copy of a read when n8n is down (5xx); otherwise the error itself."""
    saved = last_good_store.load(_snapshot_name(key), SNAPSHOT_MAX_AGE_HOURS) if error.status >= 500 else None
    if saved is None:
        raise _fail(error) from error
    saved_at, payload = saved
    return {**payload, "offline": True, "offline_message": str(error),
            "saved_at": datetime.fromtimestamp(saved_at, tz=timezone.utc).isoformat()}


# ---- request bodies ----------------------------------------------------------
class RosterFields(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    role: str | None = Field(default=None, max_length=80)
    tier: int | None = Field(default=None, ge=1, le=3)
    email: str | None = Field(default=None, max_length=120)
    whatsapp: str | None = Field(default=None, max_length=20)
    gmail_on: bool | None = None
    whatsapp_on: bool | None = None
    on_duty: bool | None = None
    notes: str | None = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        value = value.strip() if value is not None else None
        if value and not EMAIL.match(value):
            raise ValueError("not a valid email address")
        return value

    @field_validator("whatsapp")
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        value = re.sub(r"[\s-]", "", value) if value is not None else None
        if value and not PHONE.match(value):
            raise ValueError("use an international number such as +923001234567")
        return value


class NewRosterRow(RosterFields):
    name: str = Field(min_length=1, max_length=80)
    tier: int = Field(ge=1, le=3)


class ChannelFields(BaseModel):
    slack: bool | None = None
    gmail: bool | None = None
    whatsapp: bool | None = None
    notes: str | None = Field(default=None, max_length=200)


class AlarmAction(BaseModel):
    by: str = Field(default="FloodGuard app", min_length=1, max_length=80)


class TestForecast(BaseModel):
    target_name: str = Field(default="App test station", min_length=1, max_length=60)
    # A river station's id (e.g. "TRIMMU"), so the test alarm matches that station; else made from the name.
    target_id: str | None = Field(default=None, max_length=60, pattern=r"^[A-Za-z0-9_-]+$")
    model_case: Literal["riverine", "flash", "urban", "upstream", "seasonal"] = "riverine"
    risk_class: Literal["Normal", "Moderate", "High", "Very high", "Extreme"] = "High"
    probability: float = Field(default=0.7, ge=0, le=1)
    value: float | None = Field(default=None, ge=0)
    value_unit: str = Field(default="cumecs", max_length=20)
    horizon_hours: int = Field(default=6, ge=0, le=720)


def _changes(body: BaseModel) -> dict:
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=422, detail="Nothing to change.")
    return data


# ---- workflow and runs -------------------------------------------------------
@router.get("/status")
async def status(client: N8nAlarmClient = Depends(get_client)):
    settings = get_settings()
    base = {"editor_url": settings.n8n_editor_url, "workflow_name": settings.n8n_alarm_workflow_name}
    try:
        workflow = await client.workflow()
    except N8nError as error:
        # The workflow as it last was, so the page can still name it and say when it was saved.
        saved = last_good_store.load(_snapshot_name("status"), SNAPSHOT_MAX_AGE_HOURS)
        last = {"saved_at": datetime.fromtimestamp(saved[0], tz=timezone.utc).isoformat(), "active": saved[1].get("active"),
                "workflow_url": saved[1].get("workflow_url")} if saved else None
        return {**base, "connected": False, "message": str(error), "last_seen": last}
    return _remember("status", {**base, "connected": True, "message": None, "workflow_id": workflow["id"], "active": bool(workflow.get("active")),
                                "workflow_url": f"{settings.n8n_editor_url.rstrip('/')}/workflow/{workflow['id']}"})


@router.get("/workflow")
async def workflow(client: N8nAlarmClient = Depends(get_client)):
    try:
        return _remember("workflow", workflow_layout(await client.workflow()))
    except N8nError as error:
        return _saved_or_fail("workflow", error)


@router.get("/runs")
async def runs(limit: int = Query(default=20, ge=1, le=100), include_mocks: bool = False,
               client: N8nAlarmClient = Depends(get_client)):
    key = f"runs-{limit}-{int(include_mocks)}"
    try:
        layout = workflow_layout(await client.workflow())
        executions = await client.executions(layout["id"], limit if include_mocks else min(100, limit * 3))
    except N8nError as error:
        return _saved_or_fail(key, error)
    summaries = [summarize_execution(execution, layout) for execution in executions]
    if not include_mocks:
        summaries = [run for run in summaries if not run["is_mock"]]
    return _remember(key, {"runs": summaries[:limit]})


# Alarm history: runs started by a forecast, an acknowledgement link or by hand (and failed runs),
# searched further back than the recent runs, which are mostly routine escalation checks.
_HISTORY_CACHE: dict[int, tuple[float, dict]] = {}
HISTORY_CACHE_SECONDS = 60
HISTORY_SCAN_LIMIT = 3000


@router.get("/runs/history")
async def run_history(limit: int = Query(default=20, ge=1, le=50), client: N8nAlarmClient = Depends(get_client)):
    key = f"history-{limit}"
    cached = _HISTORY_CACHE.get(limit)
    if cached and time.monotonic() - cached[0] < HISTORY_CACHE_SECONDS:
        return cached[1]
    try:
        layout = workflow_layout(await client.workflow())
        picked: list[str] = []
        cursor, scanned = None, 0
        while len(picked) < limit * 2 and scanned < HISTORY_SCAN_LIMIT:
            page = await client.execution_page(layout["id"], cursor)
            for execution in page.get("data", []):
                scanned += 1
                if execution.get("mode") != "trigger" or execution.get("status") in ("error", "crashed"):
                    picked.append(str(execution["id"]))
            cursor = page.get("nextCursor")
            if not cursor:
                break
        runs = []
        for execution_id in picked:
            summary = summarize_execution(await client.execution(execution_id), layout)
            if not summary["is_mock"]:
                runs.append(summary)
            if len(runs) >= limit:
                break
    except N8nError as error:
        return _saved_or_fail(key, error)
    payload = _remember(key, {"runs": runs, "scanned": scanned})
    _HISTORY_CACHE[limit] = (time.monotonic(), payload)
    return payload


@router.get("/runs/{execution_id}")
async def run(execution_id: str, client: N8nAlarmClient = Depends(get_client)):
    if not execution_id.isdigit():
        raise HTTPException(status_code=422, detail="Run ids are numbers.")
    try:
        layout = workflow_layout(await client.workflow())
        return _remember(f"run-{execution_id}", summarize_execution(await client.execution(execution_id), layout))
    except N8nError as error:
        return _saved_or_fail(f"run-{execution_id}", error)


# ---- data tables ---------------------------------------------------------------
@router.get("/tables/{table}")
async def table_rows(table: TableName, limit: int = Query(default=200, ge=1, le=250),
                     alarm_id: str | None = Query(default=None, max_length=80),
                     client: N8nAlarmClient = Depends(get_client)):
    filters = [{"columnName": "alarm_id", "condition": "eq", "value": alarm_id}] if alarm_id and table in ("alarm_events", "alarm_notifications") else None
    key = f"table-{table}-{limit}-{alarm_id or ''}"
    try:
        return _remember(key, {"table": table, "rows": await client.rows(table, limit, TABLE_SORT[table], filters)})
    except N8nError as error:
        return _saved_or_fail(key, error)


@router.post("/duty-roster", status_code=201)
async def add_person(body: NewRosterRow, client: N8nAlarmClient = Depends(get_client)):
    row = {"role": "", "email": "", "whatsapp": "", "gmail_on": bool(body.email), "whatsapp_on": bool(body.whatsapp),
           "on_duty": True, "notes": "", **body.model_dump(exclude_none=True)}
    try:
        return await client.insert_row("duty_roster", row)
    except N8nError as error:
        raise _fail(error) from error


@router.patch("/duty-roster/{row_id}")
async def update_person(row_id: int, body: RosterFields, client: N8nAlarmClient = Depends(get_client)):
    try:
        return await client.update_row("duty_roster", row_id, _changes(body))
    except N8nError as error:
        raise _fail(error) from error


@router.delete("/duty-roster/{row_id}", status_code=204)
async def remove_person(row_id: int, client: N8nAlarmClient = Depends(get_client)):
    try:
        await client.delete_row("duty_roster", row_id)
    except N8nError as error:
        raise _fail(error) from error


@router.patch("/alert-channels/{row_id}")
async def update_channels(row_id: int, body: ChannelFields, client: N8nAlarmClient = Depends(get_client)):
    try:
        return await client.update_row("alert_channels", row_id, _changes(body))
    except N8nError as error:
        raise _fail(error) from error


# ---- alarms ------------------------------------------------------------------
@router.post("/alarms/{alarm_id}/acknowledge")
async def acknowledge(alarm_id: str, body: AlarmAction, client: N8nAlarmClient = Depends(get_client)):
    """Goes through the workflow's own acknowledge link, so the audit trail and backend callback run too."""
    try:
        page = await client.acknowledge(alarm_id, body.by)
    except N8nError as error:
        raise _fail(error) from error
    if "not found" in str(page).lower():
        raise HTTPException(status_code=404, detail=f"No alarm {alarm_id}.")
    return {"alarm_id": alarm_id, "status": "acknowledged", "by": body.by}


@router.post("/alarms/{alarm_id}/resolve")
async def resolve(alarm_id: str, body: AlarmAction, client: N8nAlarmClient = Depends(get_client)):
    """Closes an alarm by hand (no all-clear forecast came) and records it in the audit trail."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        found = await client.rows("flood_alarms", 1, None, [{"columnName": "alarm_id", "condition": "eq", "value": alarm_id}])
        if not found:
            raise HTTPException(status_code=404, detail=f"No alarm {alarm_id}.")
        alarm = found[0]
        if alarm.get("status") == "resolved":
            return {"alarm_id": alarm_id, "status": "resolved", "by": body.by}
        await client.update_row("flood_alarms", alarm["id"], {"status": "resolved", "resolved_at": now, "last_action": "resolve"})
        await client.insert_row("alarm_events", {"alarm_id": alarm_id, "event": "resolved", "level": alarm.get("level") or 0,
                                                 "tier": alarm.get("tier") or 1, "actor": body.by,
                                                 "detail": "closed by hand from the FloodGuard app", "at": now})
    except N8nError as error:
        raise _fail(error) from error
    return {"alarm_id": alarm_id, "status": "resolved", "by": body.by}


@router.post("/test-forecast")
async def test_forecast(body: TestForecast, client: N8nAlarmClient = Depends(get_client)):
    """Sends one test forecast through the whole workflow (it alerts like a real one)."""
    now = datetime.now(timezone.utc)
    slug = (body.target_id or re.sub(r"[^a-z0-9]+", "_", body.target_name.lower()).strip("_") or "app_test").lower()
    forecast = {"id": f"app-test-{int(now.timestamp())}", "model_case": body.model_case, "target_id": slug,
                "target_name": body.target_name, "issued_at": now.isoformat(), "valid_at": now.isoformat(), "horizon_hours": body.horizon_hours,
                "value": body.value, "value_unit": body.value_unit, "probability": body.probability, "risk_class": body.risk_class,
                "model_name": "floodguard_app_test", "point_metadata": {"simulation_source": "floodguard_app_test"}}
    try:
        return await client.send_forecasts([forecast])
    except N8nError as error:
        raise _fail(error) from error
