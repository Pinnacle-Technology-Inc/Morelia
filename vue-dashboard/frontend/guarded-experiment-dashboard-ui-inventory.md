# Guarded Experiment Dashboard UI Inventory

## Purpose

Define the target dashboard text, navigation, tabs, cards, fields, tables, dialogs, and shared labels for the guarded experiment dashboard.

This is the target UI content inventory. Product behavior and domain rules live in `guarded-experiment-dashboard.md`.

Backend alignment: reconciled with `backend/docs/backend-control-plane-architecture-plan.md` on 2026-07-20.

## Naming Decisions

Use these names consistently in user-facing UI:

| UI name | Meaning | Notes |
|---|---|---|
| `Session` | The grouped acquisition unit a scientist creates, starts, stops, monitors, and reviews. | Do not expose `stream group` as a separate UI concept. |
| `Stream` | One device's data path inside a session, including its sinks or mirror outputs. | Replaces `Device Flow` in user-facing UI. |
| `Session Monitor` | The process that supervises and reports/control-status for a session. | Replaces user-facing `Watchdog`, `runtime`, and `runtime agent`. |
| `Session Health` | The rolled-up operator-facing status for the session. | Values: `Healthy`, `Recovering`, `Needs action`, `Unknown`. |

Use `dataflow`, `runtime id`, or `watchdog id` only in diagnostic details when needed. They should not be primary labels in normal dashboard workflows.

## Primary Navigation

The target app has 8 primary navigation entries plus a persistent create action.

| Order | Route id | Label | Purpose |
|---:|---|---|---|
| 1 | `overview` | Overview | Active sessions, attention, scheduled work, and recent incidents. |
| 2 | `sessions` | Sessions | Create, start, stop, complete, duplicate, and review sessions. |
| 3 | `experiments` | Experiments | Group related sessions without affecting hardware execution. |
| 4 | `devices` | Devices | Physically connected and persisted configured devices. |
| 5 | `templates` | Templates | Reusable device and session templates. |
| 6 | `incidents` | Incidents & Gaps | Permanent interruption, gap, and recovery history. |
| 7 | `operations` | Operations | Durable operation history and uncertain-operation resolution. |
| 8 | `system-health` | System Health | Session monitors, storage, and diagnostic health. |

Persistent action:

- Button: `New Session`
- `aria-label`: `Create new session`

Do not keep `Recovery Policies` as a top-level nav item. Recovery policy selection and review belong inside session creation, session recovery, and session configuration surfaces.

## App Header

Header copy:

- Eyebrow: `Operational overview`
- Title: `Acquisition control center`
- Description: `Monitor active sessions, review recovery decisions, and confirm system readiness from one workspace.`
- Time label: `{HH:MM:SS} America/Chicago`

## Overview Page

### Section: Active Sessions

Section title:

- `Active Sessions ({count})`

Accessibility copy:

- `Drag a session by its handle or use the arrow keys while the handle is focused.`

Show/hide actions:

- `Show all {count} active sessions`
- `Show top {limit} sessions`

### Card: Active Session

Card fields:

- Session name
- Experiment name
- Lifecycle badge
- Session Health badge
- Duration
- Streams / Sinks
- Session Monitor status badge

Controls:

- Drag handle `aria-label`: `Reorder {session.name}. Use arrow keys or drag.`
- Expand/collapse `aria-label`: `Expand streams for {session.name}` or `Collapse streams for {session.name}`
- Footer action: `Open session`

Expanded streams section:

- Section heading: `Streams`
- Count label: `{count} stream` or `{count} streams`
- Stream row fields:
  - device label
  - device type
  - hardware id
  - stream status badge
  - data rate
  - last data
  - sink count
- Empty state: `No stream details are available.`

### Sidebar Section: Attention Required

Section title:

- `Attention Required ({count})`

Collapsed rail:

- `aria-label`: `Open Attention Required, {count} items`
- Tooltip/title: `Open Attention Required`

Header actions:

- `View all {count}`
- Expand/collapse `aria-label`: `Expand Attention Required` or `Collapse Attention Required`

Attention card fields:

- session name
- lifecycle badge
- Session Health badge
- attention reason
- `Since {time}`
- action text: `Review recovery`

### Sidebar Section: Upcoming Scheduled

Section title:

- `Upcoming Scheduled ({count})`

Collapsed rail:

- `aria-label`: `Open Upcoming Scheduled, {count} items`
- Tooltip/title: `Open Upcoming Scheduled`

Header action:

- Expand/collapse `aria-label`: `Expand Upcoming Scheduled` or `Collapse Upcoming Scheduled`

Scheduled card fields:

- session name
- experiment name
- label: `Scheduled`
- scheduled date/time
- Session Health badge

### Section: Recent Incidents & Recoveries

Section title:

- `Recent Incidents & Recoveries`

Table columns:

- `Time`
- `Session`
- `Stream`
- `Reason`
- `Outcome`

Rows open the related session or incident detail.

## Sessions Page

Page header:

- Eyebrow: `Session workspace`
- Title: `Sessions`
- Description: `Find, configure, schedule, and review acquisition sessions.`
- Header action: `New Session`

### Session Tabs

There are 6 session tabs.

| Order | Tab id | Label | Count source |
|---:|---|---|---|
| 1 | `needs-attention` | Needs Attention | sessions with Session Health `Needs action` |
| 2 | `active` | Active | lifecycle `Active`, `Starting`, or `Ending` |
| 3 | `scheduled` | Scheduled | lifecycle `Scheduled` |
| 4 | `drafts` | Drafts | lifecycle `Draft` |
| 5 | `completed` | Completed | lifecycle `Completed` and not archived |
| 6 | `archived` | Archived | archived sessions |

### Toolbar

Search field:

- Placeholder: `Search sessions or experiments...`

Button:

- `Filter`

### Sessions Table

Columns:

- `Session`
- `State`
- `Session Health`
- `Experiment`
- `Streams`
- `Session Monitor`
- `Time`
- blank action column

Row fields:

- session name
- optional attention reason
- lifecycle badge
- Session Health badge
- experiment or `-`
- `{streamCount}/{sinkCount}`
- Session Monitor status badge
- time label
- row action: `Open`

Time labels:

- Active sessions: duration string
- Scheduled sessions: scheduled date/time
- Completed sessions: localized start date
- Missing time: `-`

Empty state:

- Title: `No sessions in this category`
- Description: `Try another tab or change the current search.`

## Create Session Page

The session workflow does not configure physical devices. Device configuration belongs under `Devices`.

The session workflow lets users:

- choose free configured devices as streams for a session;
- or start from a session template, then resolve required free configured devices, sinks, schedule, and policy.

Page header:

- Eyebrow: `Guided configuration`
- Title: `Create Session`
- Description: `Choose streams, outputs, scheduling, and guarded recovery behavior.`

### Wizard Steps

There are 6 wizard steps.

| Order | Label |
|---:|---|
| 1 | Details |
| 2 | Streams |
| 3 | Sinks & Outputs |
| 4 | Schedule |
| 5 | Recovery |
| 6 | Review |

### Step 1: Details

Fields:

- `Session Name *`
  - placeholder: `e.g. Cortical Array Session 08`
- `Description`
  - placeholder: `Optional description`
- `Experiment`
  - options include `None` plus available experiments
- `Start From`
  - options:
    - `Blank session`
    - `Session template`
- `Session Template`
  - shown when `Session template` is selected
  - placeholder: `Choose a session template`
- `Notes`
  - placeholder: `Optional session notes`

### Step 2: Streams

Section title:

- `Choose streams`

Description:

- `Choose free configured devices for this session. Device setup is managed in Devices.`

If the session starts from a template:

- `Devices required by this template are configured automatically when possible.`
- Unconfigured devices are created from the template's device settings. If auto-configuration fails, the error is shown and the step blocks.

Configured-device table columns:

- `Device`
- `Type`
- `Hardware ID`
- `Port`
- `Availability`
- `Status`
- `Config Source`
- blank selection column

Selection states:

- `Available`
- `Claimed`
- `Not found`

Actions:

- `Add Stream`
- `Remove`
- `View device`

Validation copy:

- `Only free configured devices can be added to a session.`
- `This device is already claimed by {session}.`
- `This device was not found in the latest scan.`
- `Could not auto-configure {device} from the template.`

### Dialog: Device Reserved

Shown when a selected device is claimed by another session that has not started yet (a stealable pre-start reservation). Present a single yes/no choice; do not force a retry loop.

Title:

- `Device reserved`

Description:

- `{device} is reserved by {session}, which has not started. Use it for this session instead?`

Footer actions:

- `No, keep it with {session}`
- `Yes, use it here`

### Step 3: Sinks & Outputs

Section title:

- `Configure sinks and outputs`

Description:

- `Each sink belongs to one stream and must pass write and duplicate-path validation.`

Per-stream output card fields:

- stream device label
- sink name
- sink type
- destination path
- filename preview
- writable status
- free space
- duplicate-path status

Actions:

- `Add Sink`
- `Remove Sink`
- `Validate Outputs`

Validation copy:

- `Writable`
- `Not writable`
- `Duplicate path`
- `Low storage`
- `Output validation pending`

### Step 4: Schedule

Fields:

- `Start Mode`
  - options:
    - `Manual`
    - `One-time`
    - `Daily`
- `Timezone`
  - default: `America/Chicago`
- `Start Date`
- `Start Time`

### Step 5: Recovery

There are exactly two recovery policies, `Recommend` and `Automate`. Policies are not versioned.

Fields:

- `Recovery Policy`
  - options:
    - `Recommend`
    - `Automate`

Notice:

- `Changed policies default to Recommend. Automation requires an explicit choice.`

Policy descriptions:

- `Recommend`: `Report software-fixable faults and wait for operator approval.`
- `Automate`: `Run software-fixable recovery when preconditions allow it.`

### Step 6: Review

Preflight is a backend status the frontend waits on; it is not shown as an operator-facing checklist.

Notice:

- `Complete stream and sink selection before starting.`

Review summary shows the composed session before start:

- `Session details`
- `Streams`
- `Sinks & outputs`
- `Schedule`
- `Recovery policy`

### Wizard Footer

Left action:

- Step 1: `Cancel`
- Later steps: `Back`

Right actions:

- `Save as Draft`
- Intermediate primary action: `Next: {next step label}`
- Final action: `Start Now`

## Session Detail Page

Back action:

- `Sessions`

Header fields:

- session name
- lifecycle badge
- Session Health badge
- experiment name when present
- duration or `Not started`
- `{streamCount} streams / {sinkCount} sinks`
- Session Monitor status badge
- `Last update {age} ago`

Header actions:

- `Add Note`
- `Duplicate`
- `Complete` when lifecycle is `Active`
- `Stop` when lifecycle is `Active`

Needs-action alert:

- text: attention reason
- action: `Review in Recovery`

### Session Detail Tabs

There are 6 detail tabs.

| Order | Tab id | Label |
|---:|---|---|
| 1 | `overview` | Overview |
| 2 | `streams` | Streams |
| 3 | `recovery` | Recovery |
| 4 | `incidents` | Incidents & Gaps |
| 5 | `activity` | Activity & Notes |
| 6 | `configuration` | Configuration |

### Overview Tab

Card: `Session Summary`

- `Lifecycle`
- `Session Health`
- `Collection`
- `Experiment`
- `Ownership`

`Collection` is the runtime phase (collection lifecycle), shown here only. It is separate from `Session Health` and never replaces it. Values:

- `Idle`
- `Preflight`
- `Running`
- `Stopped`
- `Closed`

Overview page cards stay health-only; runtime phase is not surfaced there.

Ownership values:

- `Owner session`
- `Monitoring only`

Note: creating and managing monitoring subscriptions is a deferred feature (planned in both frontend and backend). v1 displays ownership state only; there is no subscription create/detach UI yet.

Card: `Current Recovery`

- Needs-action text: `A guarded recovery recommendation is waiting for operator approval.`
- Healthy/no-recovery text: `No active recovery. Required verification checks are passing.`
- Action when needed: `Review Action`

Card: `Stream Health`

- stream/device label
- hardware id
- stream status badge
- data rate
- last data
- sink status summary

### Streams Tab

Repeated card per stream.

Card header:

- device label
- device type
- hardware id
- stream status badge

Metrics:

- `Data rate`
- `Last data`
- `Session Monitor`
- `Sink count`

Sink list fields:

- sink name
- sink path
- sink health badge

Actions:

- `Recover Stream`
- `Open Device`
- `Open Output`

### Recovery Tab

Card: `Assigned Policy`

- `Policy`
- `Verification`

Policy values:

- `Recommend`
- `Automate`

Card: `Recovery Activity`

Watchdog-emitted recovery log. These are diagnostic log phases from the watchdog, not an operator health enum:

- `Validate`
- `Recover`
- `Verify`

The rollup resolves to session health `Healthy` or `Needs action`. Backend `suspect` reports are shown as `Unhealthy`; `suspect` is never a separate operator-facing label.

Actions:

- `Approve Recovery` when policy is `Recommend`
- `Retry Recovery`
- `Mark Resolved`

### Incidents & Gaps Tab

Table columns:

- `Time`
- `Stream`
- `Reason`
- `Policy`
- `Outcome`
- `State`

State values:

- `Open`
- `Acknowledged`
- `Resolved`

### Activity & Notes Tab

Timeline item fields:

- time
- event title
- related stream or operation id
- status/tone
- optional note

Actions:

- `Add Note`
- `Filter`

### Configuration Tab

Card: `Metadata`

- `Name`
- `Experiment`
- `Schedule`
- `Recovery Policy`

Schedule values:

- `Manual`
- `One-time`
- `Daily`

Card: `Runtime Lock`

- Draft text: `Configuration is editable before start.`
- Started text: `Stream and sink configuration is read-only after start.`

### Dialog: Stop Session

Title:

- `Stop Session`

Description:

- `This will stop the session through the session monitor.`

Content:

- `Streams affected`
- stream list
- warning if monitoring sessions depend on mirrored streams

Footer actions:

- `Cancel`
- `Stop Session`

### Dialog: Approve Recovery Action

Title:

- `Approve Recovery Action`

Description:

- `Policy: Recommend`

Fields:

- `Detected problem`
- `Proposed action`
- `Expected interruption`
- `Required verification`

Footer actions:

- `Cancel`
- `Approve Recovery`

### Dialog: Duplicate Session

Duplicating creates a new session using the current session as a template.

Title:

- `Duplicate Session`

Fields:

- `Session Name`
  - a suggested default is provided; the user can change it
- `Device Copy Mode`
  - options:
    - `Copy device identity`: reuse the same configured devices
    - `Generic copy`: do not bind devices; the user selects devices next

Notice:

- When `Generic copy` is chosen, prompt the user to pick devices before start.

Footer actions:

- `Cancel`
- `Create Session`

## Devices Page

The Devices page focuses on physically connected and persisted configured devices. It contains both current discovery evidence and the persisted device config needed to add the device to a session.

Page header:

- Eyebrow: `Hardware inventory`
- Title: `Devices`
- Description: `Review connected hardware, configured devices, availability, and session ownership.`
- Header actions:
  - `Scan Devices`
  - `Add Device Config`

### Device Tabs

There are 3 device tabs.

| Order | Tab id | Label |
|---:|---|---|
| 1 | `all` | All Devices |
| 2 | `available` | Available |
| 3 | `claimed` | Claimed |

### Devices Table

Columns:

- `Device`
- `Type`
- `Hardware ID`
- `Port`
- `Availability`
- `Status`
- `Config Source`
- `Owning Session`
- `Last Seen`
- blank action column

Column meanings:

- `Device`: display label or nickname.
- `Type`: device type, such as `pod8206hr`.
- `Hardware ID`: opaque hardware identity read from the device.
- `Port`: latest known port.
- `Availability`: latest discovery evidence.
- `Status`: pool ownership.
- `Config Source`: source template name; `Custom` when the template link was severed (shows `was {templateName}`); or `None`. Unconfigured (scan-only) rows have no config source.
- `Owning Session`: shown only when claimed.
- `Last Seen`: timestamp from latest scan or persisted device history.

Availability values:

- `available`
- `not_found`

Status values:

- `free`
- `claimed`
- `unconfigured`

Row indicators:

- Port mismatch warning when the configured port differs from the latest scan port.
- Drift indicator when the device config parameters differ from its source template.

Row actions:

- `Open`
- `Edit Config`
- `Create Device Config`
- `Export Template`

Rules:

- `Edit Config` is available only when status is `free`.
- `Create Device Config` is shown only for `unconfigured` scan-only rows; it configures the discovered device.
- `Export Template` saves current device config parameters as a reusable device template.

### Device Detail

Sections:

- `Identity`
- `Discovery`
- `Configuration`
- `Ownership`
- `Recent Sessions`

Identity fields:

- `Device`
- `Type`
- `Hardware ID`
- `Port`

Discovery fields:

- `Availability`
- `Last Seen`
- `Scan ID`
- `Warnings` (includes a port-mismatch warning when the configured port differs from the latest scan port)

Configuration fields:

- `Config Source` (source template name; `Custom` with `was {templateName}` when the link was severed; or `None`)
- `Parameters`
- `Schema Version`
- `Content Hash` (small, shown for explainability only — it detects template similarity, not config drift)
- `Template Drift` (shown when the config parameters differ from the source template)

Ownership fields:

- `Status`
- `Owning Session`
- `Claimed At`

### Dialog: Update Source Template

Shown when a user edits a free device config's parameters.

Title:

- `Update source template?`

Description:

- `You changed parameters that came from {templateName}. Update the source template too, or keep this change on the device config only?`

Footer actions:

- `Keep on device only`
- `Update template`

## Templates Page

Templates are reusable configuration artifacts. They do not represent connected hardware.

Page header:

- Eyebrow: `Reusable configuration`
- Title: `Templates`
- Description: `Manage reusable device and session templates.`
- Header actions:
  - `New Template`
  - `Import Template`

### Template Tabs

There are 2 template tabs.

| Order | Tab id | Label |
|---:|---|---|
| 1 | `device-templates` | Device Templates |
| 2 | `session-templates` | Session Templates |

### Device Templates Tab

Columns follow the backend `device_template` row.

Columns:

- `Template`
- `Device Type`
- `Schema Version`
- `Content Hash` (small, explainability only)
- `Sessions Using`
- `Created`
- blank action column

Actions:

- `Open`
- `Edit`
- `Rename`
- `Delete`
- `Export`

Rules:

- Device templates have no port, no hardware id, and no sink.
- Rename and delete warn when sessions or device configs reference the template.

### Session Templates Tab

Columns:

- `Template`
- `Streams`
- `Sinks`
- `Policy`
- `Source Session`
- `Last Exported`
- blank action column

Actions:

- `Open`
- `Use Template`
- `Delete`
- `Export`

Rules:

- Available operations follow the backend: list, show, import, delete, use (create session from template), and export. Rename is not offered.
- A session template may include composition requirements, sinks, policy, and schedule defaults.
- It never includes runtime state, operation ids, session monitor ports/tokens, incidents, output segment ids, gaps, recovery history, or generated filenames.

## Experiments Page

Page header:

- Eyebrow: `Organizational workspace`
- Title: `Experiments`
- Description: `Group related sessions without affecting hardware execution.`
- Header action: `New Experiment`

Columns:

- `Experiment`
- `Description`
- `Sessions`
- `Active`
- `Needs Attention`
- blank action column

An experiment is a control-plane grouping only: it groups related sessions and never affects hardware execution.

Row actions:

- `Open`
- `Add Note`

Notes are a control-plane function. They are available only on sessions, experiments, and data gaps.

## Incidents & Gaps Page

Page header:

- Eyebrow: `Permanent operational record`
- Title: `Incidents & Gaps`
- Description: `Review interruptions, data gaps, guarded actions, and verification outcomes.`

### Incidents Page Tabs

There are 3 tabs.

| Order | Tab id | Label |
|---:|---|---|
| 1 | `incidents` | Incidents |
| 2 | `gaps` | Data Gaps |
| 3 | `history` | Recovery History |

### Incidents Tab

Table columns:

- `Time`
- `Session`
- `Stream`
- `Reason`
- `Policy`
- `Outcome`
- `State`

State values:

- `Open`
- `Acknowledged`
- `Resolved`

Actions:

- `Open`
- `Acknowledge`

### Data Gaps Tab

Table columns:

- `Start`
- `End`
- `Duration`
- `Session`
- `Stream`
- `Cause`
- `Incident`
- `Outcome`

Outcome values:

- `Recovered`
- `Uncertain`

Actions:

- `Add Note`

### Recovery History Tab

Table columns:

- `Time`
- `Session`
- `Stream`
- `Phase`
- `Action`
- `Verification`
- `Outcome`
- `Policy`

Phase values (watchdog-emitted log phases, shown as a diagnostic record, not the operator health rollup):

- `Suspect`
- `Validate`
- `Recover`
- `Verify`

## Operations Page

Page header:

- Eyebrow: `Operator resolution`
- Title: `Operations`
- Description: `Review interrupted command outcomes before continuing guarded lifecycle work.`
- Header action: `Refresh`

Toolbar:

- `{count}`
- `uncertain`
- load error shown as alert text

Loading state:

- `Loading operations`

Empty state:

- `No uncertain operations`

### Operations Table

Columns:

- `Operation`
- `Command`
- `Scope`
- `Session`
- `Stream`
- `Outcome`
- `Finished`
- blank action column

Row fields:

- operation id
- optional error code
- command
- scope
- session name/id
- stream label or `-`
- state badge
- finished timestamp or `-`
- action: `Resolve`

`Scope` renders the affected dataflow through its owning session, never a raw `dataflow_id`:

- whole-dataflow operations (`start`, `stop`): `Session {name}`
- stream-scoped operations (`reconnect`, `restart`, `reset-stream`): `Session {name} · {stream}`

Blocked-operation copy (only one operation may be active per dataflow) names the session holding it, not the dataflow id:

- `Another operation is running for {session}. Wait for it to finish.`

### Resolution Panel

Panel title:

- `Resolution`

Read-only fields:

- `Command`
- `Scope`
- `Session`
- `Stream`
- `Error`

Fallback values:

- Stream: `-`
- Error: `-`

Form fields:

- `Outcome`
  - options:
    - `Succeeded`
    - `Failed`
  - required; the backend resolve call requires an explicit outcome
- `Resolved by`
- `Resolution note`

Submit action:

- `Record Resolution`

### Command Diagnostics

Read-only southbound command history for an operation, sourced from the runtime command surface (`runtime command list/show`). Secondary to the operator resolution workflow.

- operation id
- one or more `command_id` values
- runtime id
- command status

API error fallback copy:

- `Unable to load operations.`
- `Unable to resolve operation.`

## System Health Page

Page header:

- Eyebrow: `Infrastructure`
- Title: `System Health`
- Description: `Inspect session monitors, stream ownership, communication, and storage.`

### System Health Tabs

There are 3 tabs.

| Order | Tab id | Label |
|---:|---|---|
| 1 | `session-monitors` | Session Monitors |
| 2 | `streams` | Streams |
| 3 | `storage` | Storage |

### Control Plane Daemon

Card: `Daemon`

- `Status`: running/stopped, pid, serving URL
- `Doctor`: diagnostic check results

Actions:

- `Shutdown`, with a `Cascade` option to stop all owned runtimes
- `Force Stop Session`: escape hatch for a stuck runtime

Note:

- Runtime agents self-terminate after a lease window (~30 min) without daemon contact.

Card: `Backend Processes`

A coarse liveness signal for the daemon's child processes (runtime hosts and their watchdog processes). This is a process/child-process health readout, not hardware or ownership detail.

- overall signal: `OK` / `Attention`
- per-process rows: process kind (runtime host / watchdog), session, alive/not-alive, last contact

It answers "are the backend processes doing ok?" — it is not the operator lifecycle or reconciliation surface.

### Session Monitors Tab

Table columns:

- `Monitor ID`
- `Session`
- `Process`
- `Comms`
- `Last Report`
- `Reconciliation`
- `Diagnostic ID`

Sample process values:

- `Running`
- `Stopped`

Comms values:

- `Current`
- `Delayed`
- `Unreachable`
- `Stopped`

Reconciliation values:

- `Reconciled`
- `Needs action`
- `Uncertain`

`runtime_ownership` is a backend process/child-process relationship, not a hardware or operator concept. Its detailed state (`starting/running/adopted/stopping/stopped/uncertain`) is **not** surfaced as an operator state machine here. This column is only a coarse signal of whether the backend reconciled its processes cleanly (`Reconciled`), needs operator input (`Needs action`), or could not determine the outcome (`Uncertain`).

Diagnostic fields may expose backend ids such as dataflow/watchdog/runtime ids when needed, but they should not replace the user-facing session and monitor labels.

### Streams Tab

Table columns:

- `Session`
- `Stream`
- `Device`
- `Owner`
- `Desired`
- `Actual`
- `Stream Status`
- `Last Data`

Sample desired/actual values:

- `Active`
- `Stopped`
- `Starting`
- `Ending`

### Storage Tab

Card: `Database`

- `State`
- `Location`
- `Size`

Card: `Permanent Records`

- `Incidents`
- `Data gaps`
- `Recovery records`
- `Session notes`

Card: `Output Destinations`

Table columns:

- `Path`
- `Accessible`
- `Writable`
- `Free Space`

## Shared Status Labels

### Session Lifecycle

- `Draft`
- `Scheduled`
- `Starting`
- `Active`
- `Ending`
- `Completed`

### Session Health

- `Healthy`
- `Recovering`
- `Needs action`
- `Unknown`

### Stream Status

The frontend shows two states. Backend `suspect` is shown as `Unhealthy` — there is no operator-facing `Suspect` badge.

- `Healthy`
- `Unhealthy`

### Session Monitor Comms

- `Current`
- `Delayed`
- `Unreachable`
- `Stopped`

### Device Availability

- `available`
- `not_found`

Use title case on labels if displayed as badges:

- `Available`
- `Not found`

### Device Status

- `free`
- `claimed`

Displayed labels:

- `Free`
- `Claimed`

### Recovery Policy Mode

- `Recommend`
- `Automate`

### Operation State

- `Queued`
- `Claimed`
- `Dispatched`
- `Running`
- `Verifying`
- `Succeeded`
- `Failed`
- `Uncertain`

## Current Mockup Drift To Fix

These are known differences between the current Vue mockup and this target inventory:

- Primary nav currently has `Device Templates`; replace it with `Devices` and add `Templates`.
- Primary nav currently has `Recovery Policies`; remove it from top-level navigation.
- Device/template catalog currently mixes physical connection data into templates; move physical device/config fields to `Devices`.
- Create Session currently says users can select a device template or manually configure a Morelia device; change this to choosing free configured devices or starting from a session template.
- Current UI uses `Device Flow`; replace with `Stream`.
- Current UI uses `Watchdog`; replace user-facing labels with `Session Monitor`.
- Current UI uses `Aggregate health` or generic `Health`; use `Session Health` when referring to the session rollup.
- Current recovery mode copy includes `Approve` and `Observe`; modes should be only `Recommend` and `Automate`.
- Current recovery phase copy includes `Detect`, `Diagnose`, and `Resume`. Recovery phase is now treated as a watchdog-emitted diagnostic log (`Validate`, `Recover`, `Verify`, plus raw `Suspect` in history), not an operator health enum; the operator rollup resolves to `Healthy` or `Needs action`, and backend `suspect` renders as `Unhealthy`.
- Current recovery UI splits `Recovery Policy` and `Mode`; there is now a single policy choice of `Recommend` or `Automate` with no version.
- Current device availability uses five values; the frontend now shows only `available` and `not_found`.
- System Health currently has `Watchdogs` and `Dataflows` tabs; replace with `Session Monitors` and `Streams`.
- Some source strings contain mojibake for dashes, bullets, arrows, and ellipses. Normalize copy during implementation.
