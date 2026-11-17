# FloodGuard flood alarm (n8n)

An n8n alarm system for FloodGuard flood forecasts. It does the following:
- Turns each forecast into an alarm level and keeps one alarm per forecast target.
- Alerts whoever is on duty, on Slack, Gmail and WhatsApp.
- Escalates alarms nobody acknowledges.
- Tells the FloodGuard backend about every alarm event.
- Records everything in n8n data tables.

| File | What it is |
|---|---|
| `floodguard-flood-alarm.workflow.json` | The whole alarm system as one n8n workflow: alarm logic, table setup, test forecasts, and mock Slack and backend endpoints |
| `send-dummy-forecast.mjs` | Sends dummy forecasts in the portal's format to the webhook |

Built and tested on **n8n 2.47** (data tables need n8n 1.113 or later).

## How it works

```
Portal ──POST /webhook/flood-forecast──▶┐
Set up & test (manual) ¹ ──────────────▶├▶ Alarm settings ─▶ Load duty roster ─▶ Which input?
Escalation check (every 5 min) ────────▶│                    (duty_roster)        │
Alert "Acknowledge" link (GET) ────────▶┘                                         │
   ┌──────────────────────────────────────────────────────────────────────────────┘
   ├─ forecast:    Normalize & classify ─▶ Load open alarms ─▶ Decide action ──┐
   ├─ escalation:  Load unacknowledged alarms ─▶ Due for escalation ───────────┤
   └─ acknowledge: Mark acknowledged ─▶ confirmation page ──────────────┐      │
                                                                        ▼      ▼
   Decide action ─▶ Reply to portal (202 / 400 / 401)          Alarm events ◀──┤
                                                               (alarm_events)  │
   Save alarm (flood_alarms) ◀─────────────────────────────────────────────────┤
   Build messages ─▶ Route by channel ─┬─ Slack     (incoming webhook) ◀──────┘
                                       ├─ Gmail     (credential pending)
                                       └─ WhatsApp  (credential pending)
                                          └─▶ Log notification (alarm_notifications)
   Alarm events ─▶ Backend callback (POST to FloodGuard) ─▶ Log notification

¹ Set up & test: creates missing tables ─▶ adds example rows to empty duty_roster / alert_channels ─▶ dummy forecasts
  Mock Slack (/webhook/mock-slack) and Mock backend (/webhook/mock-backend): stand-ins while testing
```

### Alarm levels

The level comes from the forecast's `risk_class`. A probability of 85 % or more raises a Warning-or-worse forecast by one level. With no recognised `risk_class`, the probability alone decides (≥ 80 % Danger, ≥ 60 % Warning, ≥ 35 % Watch).

| Level | `risk_class` | Alerts on | First recipients |
|---|---|---|---|
| 0 Normal | Normal, Low | — (closes an open alarm with an all-clear) | — |
| 1 Watch | Watch, Moderate, Medium | Slack | Tier 1 |
| 2 Warning | High | Slack, Gmail | Tier 1 |
| 3 Danger | Very high, Extremely high, Severe | Slack, Gmail, WhatsApp | Tier 1 |
| 4 Extreme | Extreme, Exceptionally high, Critical | Slack, Gmail, WhatsApp | Tiers 1 and 2 |

### What happens to each forecast

One alarm is kept per `model_case` + `target_id` (for example `riverine:balloki`).

| Action | When | Alerts? |
|---|---|---|
| `raise` | Watch or worse, no open alarm for that target | Yes |
| `escalate_level` | Worse than the open alarm | Yes, at once |
| `update` | Same or lower level, within the reminder interval | No (alarm updated) |
| `reminder` | Same or lower level, reminder interval passed (6 h Watch, 2 h Warning, 1 h Danger, 30 min Extreme) | Yes |
| `resolve` | Back to Normal while an alarm is open | All-clear on Slack and email |
| `duplicate` | The same forecast was already processed (see below) | No; nothing changes |
| `invalid` | Missing `target_id`, or neither a known `risk_class` nor a probability | No; the reason is returned to the portal |

**Duplicates.** Each forecast has a reference:
- The portal's `id` (or `forecast_id` / `alert_id`) when it sends one.
- Otherwise its `issued_at`, `risk_class`, `value` and `probability` together.

The alarm stores the reference of the last forecast it processed (`last_forecast_ref`). A forecast with the same reference for the same target is ignored, so a portal retry or a double send never re-alerts anyone. Repeats within one request are caught too.

### Who gets alerts, and on which channels

Two data tables control this. Edit them in n8n under **Overview → Data tables**. The workflow reads both on every run, so changes apply at once without editing the workflow.

**`alert_channels`**: one row per alarm level, with a **Slack**, **Gmail** and **WhatsApp** toggle. Tick all three for every channel, or only the ones you want at that level. Level 0 is the all-clear sent when an alarm closes. The defaults:

| Level | Slack | Gmail | WhatsApp |
|---|---|---|---|
| 0 Normal (all-clear) | ✓ | ✓ | |
| 1 Watch | ✓ | | |
| 2 Warning | ✓ | ✓ | |
| 3 Danger | ✓ | ✓ | ✓ |
| 4 Extreme | ✓ | ✓ | ✓ |

**`duty_roster`**: one row per person.
- `on_duty`: whether they get alerts at all.
- `gmail_on` and `whatsapp_on`: their personal toggles. Turn off Gmail for someone who only has WhatsApp, or the reverse.
- `tier` (1 District, 2 PDMA, 3 NDMA), `email`, `whatsapp`.

A person gets a channel only when **all** of these hold:
- The level's toggle for that channel is on.
- They are on duty.
- Their own toggle for that channel is on.
- They have an address for it.

Slack goes to the tier's channel regardless of the roster. The example roster shows each case: one officer with email and WhatsApp, one off duty, one WhatsApp-only and one email-only.

These toggles choose who *should* get an alert. Gmail and WhatsApp still need their credentials (see below); until then those alerts are logged as `pending_auth`.

**When nobody at a tier can be reached** (nobody on duty there, or everyone on duty has both Gmail and WhatsApp off):
- A new Warning-or-worse alarm starts at the next tier that has someone on duty.
- An open alarm whose tier has nobody on duty, for example after someone goes off duty, escalates on the next 5-minute check without waiting for the escalation time.
- Every skipped tier is recorded as a `no_recipient` event, and the alert says which tier was skipped.
- If a channel has nobody to send to, the delivery is logged with status `no_recipient` instead of disappearing silently.

### Escalation

Every 5 minutes, open Warning-or-worse alarms that nobody has acknowledged move up one tier: **District duty officers → PDMA provincial control room → NDMA national command**. This happens after 60 min for Warning, 30 min for Danger and 15 min for Extreme. Tiers with nobody on duty are skipped.

Every alert contains an **Acknowledge** link. Opening it marks the alarm acknowledged and stops the tier escalation. A worse forecast still re-alerts.

### Backend callback

Every alarm event is POSTed to the FloodGuard backend in one call per run, with header `x-floodguard-key: <backendCallbackKey>`. Events include raised, escalated, acknowledged, resolved, and the rest:

```json
{ "source": "n8n-flood-alarm", "trigger": "forecast-webhook", "sent_at": "2026-11-17T09:00:00Z",
  "events": [{ "alarm_id": "FG-RIVERINE-BALLOKI-…", "event": "raised", "level": 2, "tier": 1,
               "actor": "n8n", "detail": "Warning · High · Balloki", "at": "2026-11-17T09:00:00Z" }] }
```

The call is logged in `alarm_notifications` with channel `backend`. A failed call is logged as `failed` and does not stop the alerts. Set `backendCallbackUrl` to empty to turn the callback off. By default it points at the **Mock backend** node in the same workflow.

### Data tables

**Set up & test** creates five tables.

**`flood_alarms`**: one row per alarm, with these columns:
- `alarm_id`, `alarm_key`, `status` (open / acknowledged / resolved)
- `level`, `level_name`, `risk_class`, `model_case`, `target_id`, `target_name`
- `value`, `value_unit`, `probability`, `issued_at`, `valid_at`, `model_name`, `source`
- `tier`, `tier_name`, `escalations`, `notify_count`
- `first_raised_at`, `last_forecast_at`, `last_notified_at`, `last_action`, `last_forecast_ref`
- `acknowledged_by`, `acknowledged_at`, `resolved_at`

**`alarm_events`**: the audit trail. It has one row per change to an alarm, with these columns:
- `alarm_id`
- `event`: `raised`, `level_escalated`, `reminder_sent`, `forecast_updated`, `resolved`, `tier_escalated`, `acknowledged` or `no_recipient`
- `level`, `tier`
- `actor`: `n8n`, or who acknowledged
- `detail`, `at`

**`alarm_notifications`**: one row per delivery attempt, including the backend callback. It has these columns:
- `alarm_id`, `action`, `level`, `tier`
- `channel`: `slack`, `gmail`, `whatsapp` or `backend`
- `recipient`
- `status`: `sent`, `failed`, `pending_auth`, `not_configured` or `no_recipient`
- `detail` (the provider's message id, or the error)
- `message`, `sent_at`

**`duty_roster`**: who gets alerts, with these columns: `name`, `role`, `tier`, `email`, `whatsapp`, `gmail_on`, `whatsapp_on`, `on_duty` (toggles), `notes`.

**`alert_channels`**: which channels each level uses, with these columns: `level`, `level_name`, `slack`, `gmail`, `whatsapp` (toggles), `notes`. If this table is empty, the `routing` channels in **Alarm settings** are used instead.

## Running n8n locally

### With Docker (recommended)

Docker Desktop needs WSL. If Docker Desktop says WSL is not installed, run `wsl --install` in an **administrator** PowerShell and restart Windows.

```bash
powershell -ExecutionPolicy Bypass -File automation/n8n/start-n8n-docker.ps1
```

- This runs n8n 2.47.7 from [`docker-compose.yml`](docker-compose.yml) at http://localhost:5678.
- The container restarts by itself whenever Docker Desktop is running, so the 5-minute escalation check keeps going after a reboot.
- Everything n8n stores is kept in the `floodguard_n8n_data` Docker volume: your account, workflows, data tables, execution history and encryption key.
- The first run copies in the data from the native install below, so nothing has to be set up again. The native folder stays as a backup.
- Logs: `docker logs -f floodguard-n8n`. Stop: `docker compose -f automation/n8n/docker-compose.yml stop`.
- Inside Docker, `localhost` is the container itself. The mock Slack and mock backend URLs therefore still work. A FloodGuard backend running on Windows must be addressed as `http://host.docker.internal:<port>` in **Alarm settings**, for example in `backendCallbackUrl`.

### Without Docker

`start-n8n.ps1` runs n8n directly with Node at http://localhost:5678:

```bash
powershell -ExecutionPolicy Bypass -File automation/n8n/start-n8n.ps1
```

- n8n and its data live in `%USERPROFILE%\.floodguard-n8n`, outside the repo. They survive reboots and are never committed.
- The first run installs n8n 2.47.7 there if it is missing.
- Keep the window open while n8n should run; Ctrl+C stops it. The escalation check only runs while n8n is running.
- Only one of the two can use port 5678 at a time. Changes made in one do not appear in the other.

## Setup

1. Import `floodguard-flood-alarm.workflow.json` into n8n: **Workflows → Import from file**.
2. Open **FloodGuard – Flood alarm & escalation** and run **Set up & test** once (**Execute workflow**). It is safe to run again at any time.
   - It creates the five data tables. Tables that already exist are kept as they are.
   - If `duty_roster` is empty, it adds five example people. Replace them with real staff.
   - If `alert_channels` is empty, it adds the default channels per level.
   - It never changes rows that are already there, so your edits are kept.
   - Finally it sends the dummy forecasts through the alarm.
3. In the same workflow, edit the **Alarm settings** node:
   - `n8nBaseUrl`: the public address of this n8n instance. Acknowledge links point here.
   - `tiers`: each tier's Slack channel name and incoming-webhook URL. The people come from `duty_roster`.
   - `backendCallbackUrl` / `backendCallbackKey`: the FloodGuard API endpoint that receives alarm events, and its key.
   - `webhookSecret`: set a shared secret before connecting the real portal (see below).
   - Levels, routing, reminder and escalation intervals, if you want different ones.
4. **Publish** the workflow. The forecast webhook, acknowledge link, 5-minute escalation check, and mock Slack and backend endpoints go live.

**Upgrading an earlier import.** n8n does not add columns to a table that already exists. Either add the new columns yourself in **Data tables**, or delete those tables and run **Set up & test** again:
- `flood_alarms` needs `last_forecast_ref` (string).
- `duty_roster`, if you have it, needs `gmail_on` and `whatsapp_on` (boolean). Until you add them, everyone counts as on for both.

Running **Set up & test** also creates any missing tables (`alarm_events`, `duty_roster`, `alert_channels`). If you imported the earlier two-workflow version, archive **FloodGuard – Alarm setup & test helpers** before publishing: its mock webhooks use the same paths as this workflow's. The per-tier `emails` and `whatsapp` lists in **Alarm settings** are no longer used; put those people in `duty_roster` instead.

### Slack

Each tier's `slackWebhookUrl` is a Slack **Incoming Webhook** URL (*Slack app → Incoming Webhooks → Add New Webhook to Workspace*), which needs no OAuth credential. The default URL points at the **Mock Slack** node in the same workflow. Alerts "send" successfully in tests, and the mock shows exactly what Slack would receive.

### Gmail and WhatsApp (next stage)

Both are fully wired but switched off. Their alerts are logged as `pending_auth` so you can see what would have been sent, and to whom. n8n will not publish a workflow whose nodes lack credentials, so the two send nodes are disabled until then. To switch one on:

- **Gmail** (sent over SMTP with an app password):
  1. Turn on 2-Step Verification for the Gmail account, then create an app password at https://myaccount.google.com/apppasswords.
  2. In n8n, create an **SMTP** credential:
     - User: the Gmail address
     - Password: the app password
     - Host: `smtp.gmail.com`
     - Port: `465`
     - SSL/TLS: on
  3. Open **Send Gmail**, select the credential, and enable the node.
  4. In **Alarm settings**, set `channels.gmail.fromEmail` to the Gmail address and `channels.gmail.enabled: true`.
- **WhatsApp:**
  1. Create a WhatsApp Business Cloud credential.
  2. Open **Send WhatsApp**, select the credential, and enable the node.
  3. In **Alarm settings**, set `channels.whatsapp.phoneNumberId` (from Meta's WhatsApp manager) and `channels.whatsapp.enabled: true`.
  4. Note that WhatsApp only delivers free-form text inside a 24-hour customer window; outside it Meta requires an approved template message.

If a channel is enabled in settings but its node is still disabled, the log says so (`failed`, "send node is disabled") rather than reporting it as sent.

## Testing with dummy forecasts

- In n8n, run **Set up & test**. After checking the tables, it sends dummy forecasts that raise a Watch, a Warning, a Danger and an Extreme alarm and ignore one Normal forecast.
- Or send forecasts to the webhook the way the portal will. Each scenario is described below the commands.

```bash
node automation/n8n/send-dummy-forecast.mjs rising
```
```bash
node automation/n8n/send-dummy-forecast.mjs worse
```
```bash
node automation/n8n/send-dummy-forecast.mjs clear
```
```bash
node automation/n8n/send-dummy-forecast.mjs invalid
```
```bash
node automation/n8n/send-dummy-forecast.mjs repeat
```

| Scenario | What it sends | Expected result |
|---|---|---|
| `rising` | Watch, Warning, Danger and Extreme forecasts plus one Normal | Raises four alarms |
| `worse` | Worse forecasts for two of those targets | Escalates their alarms at once |
| `clear` | Normal forecasts | Sends all-clear alerts and resolves the alarms |
| `invalid` | A malformed forecast | HTTP 400 with the reason; nothing raised |
| `repeat` | One forecast with a fixed portal `id` | First run raises an alarm; a second run is reported as a `duplicate` |

Add `--key YOUR_SECRET` once `webhookSecret` is set, and `--url …` for a non-local n8n. Each call prints the HTTP status and n8n's reply: what was decided for every forecast.

To see the no-recipient behaviour, set `on_duty` (or both `gmail_on` and `whatsapp_on`) to false for everyone at tier 2 in `duty_roster`, then send `rising`. The Extreme alarm skips PDMA and goes to NDMA. The `alarm_events` table shows a `no_recipient` event for tier 2.

## Connecting the portal (later)

POST to `{n8n}/webhook/flood-forecast` with header `x-floodguard-key: <webhookSecret>`.
- The body can be a single forecast, a list, or `{ "forecasts": [ ... ] }`.
- Each forecast uses the portal's `/api/v1/flood/model-forecasts` format.
- Only `target_id` and a `risk_class` or `probability` are required.
- Send the forecast's `id` so retries are recognised as duplicates.

```json
{
  "forecasts": [
    {
      "id": 1234, "model_case": "riverine", "target_id": "balloki", "target_name": "Balloki",
      "issued_at": "2026-11-16T09:00:00Z", "valid_at": "2026-11-16T21:00:00Z", "horizon_hours": 12,
      "value": 2950, "value_unit": "cumecs", "probability": 0.72, "risk_class": "High",
      "model_name": "xgboost_riverine_baseline_v1"
    }
  ]
}
```

The HTTP status says whether the request was accepted:

| Status | Meaning |
|---|---|
| `202` | At least one forecast was valid and processed |
| `400` | No forecasts in the request, or none of them valid (`error` says which) |
| `401` | Missing or wrong `x-floodguard-key` (`rejected` says so) |

The reply body lists what happened to each forecast:

```json
{ "http_status": 202, "received": 1, "duplicates": 0, "alerts_sent": 1,
  "alarms": [{ "target": "Balloki", "model_case": "riverine", "level": 2, "level_name": "Warning", "action": "raise", "alarm_id": "FG-RIVERINE-BALLOKI-…", "tier": 1 }] }
```
