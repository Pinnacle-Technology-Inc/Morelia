# Guarded Experiment Dashboard

## Purpose

Build a local dashboard that lets scientists configure and supervise acquisition sessions without continuously watching the hardware.

The priority is protecting data validity. The dashboard monitors acquisition state, surfaces work that needs attention, coordinates guarded recovery, and records what happened. It does not analyze scientific data.

## Scope

The MVP supports:

- Creating manual and daily scheduled sessions.
- Selecting persisted device configs and assigning sinks.
- Reusing device templates and exporting session templates.
- Monitoring device, sink, stream, worker, watchdog, and communication health.
- Showing sessions, incidents, and operations that need attention.
- Starting, stopping, reconnecting, restarting, and resetting streams through guarded operations.
- Choosing `Recommend` or `Automate` recovery policy.
- Recording incidents, gaps, notes, policy changes, operation outcomes, and recovery outcomes.

Not included initially: authentication, external alerts, scientific analysis, cloud storage, arbitrary recovery scripts, remote internet access, or broad device/sink support beyond the first production slice.

## User Workflows

- Configure a reusable device template.
- Promote discovered hardware into a persisted device config.
- Create a session from free device configs, sinks, and recovery policy.
- Start, watch, recover, stop, and complete a session.
- Duplicate a session or export a reusable session template without copying runtime history.
- Monitor a device stream owned by another responsible session when live fan-out is available.
- Review incidents, gaps, output segments, and uncertain operations after a run.

## System Model

- An **experiment** optionally groups related sessions.
- A **session** is a bounded acquisition period.
- A **device flow** is the dashboard-facing unit of one device plus its sinks or mirror outputs.
- A **dataflow** is the runtime unit driven by one responsible session.
- A **runtime agent** owns one dataflow and wraps the Morelia Watchdog.
- The dashboard is one control surface; the terminal CLI is another. Both must go through the same backend control plane for state-changing work.

```text
Vue dashboard / CLI
  -> Flask control plane + SQLite
  -> runtime agent
  -> Morelia Watchdog
  -> Morelia DataFlow / hardware / sinks
```

Scientific payload data is not stored in SQLite. SQLite stores configuration, ownership, operations, incidents, gap history, output segment metadata, policies, notes, and event history.

## Device, Template, And Session Model

The dashboard uses a three-tier configuration model:

```text
device template -> device config -> session -> runtime manifest
```

- **Device template:** reusable named parameter set, such as gains, filters, and TTL. It has no port, no sink, and no physical binding. Templates are mutable; editing a template updates it in place.
- **Device config:** persisted physical device instance with `device_type`, opaque `hardware_id`, current port, parameters, and optional nickname. Identity is `device_type + hardware_id`; port is an attribute, not identity.
- **Session config:** composition of one or more device configs, each with assigned sinks or mirror subscriptions, plus recovery policy.
- **Runtime manifest:** immutable snapshot resolved at session start. Running sessions do not change when templates or free device configs are edited later.

Device templates seed device configs. Sessions run from device configs, not directly from mutable templates.

Sinks are assigned per device inside a session config. They are not reusable templates in v1.

## Session Lifecycle

```text
Draft -> Scheduled -> Starting -> Active -> Ending -> Completed
```

- **Draft:** user is editing the session before monitoring starts.
- **Scheduled:** user has configured the session to start later.
- **Starting:** backend is validating, creating output segments, and starting runtime collection.
- **Active:** acquisition is running or being monitored.
- **Ending:** a stop/completion workflow is in progress.
- **Completed:** the session is done and can be archived, but its history remains queryable.

Started sessions cannot be deleted. They can only be completed and archived.

## Dashboard Health States

Session health is an operator-facing disposition:

```text
Healthy | Recovering | Needs action | Unknown
```

- **Healthy:** no operator action is needed.
- **Recovering:** a confirmed software-fixable issue is being recovered under `Automate`, or an approved recovery operation is running.
- **Needs action:** the system needs human approval, a physical intervention, an operation resolution, or a failed recovery follow-up.
- **Unknown:** the watchdog/runtime cannot be reached, so hardware condition cannot be observed. This means the monitor went dark, not that the hardware failed.

An unresolved `Unknown` ages into `Needs action` after `unknown_timeout`, with the requested action "investigate why the monitor went dark."

## Device List And Template List

The dashboard Device List calls the backend daemon discovery API. Discovery is read-only: it must not start collection, construct a Watchdog, or hold serial ports after the scan.

Each discovered row should show:

- scan time and scan id
- device type
- port
- hardware id or serial when available
- display label
- availability
- pool status
- owning session/dataflow/runtime when claimed
- warnings for per-port scan errors

Availability describes latest discovery evidence:

```text
available | owned | unopenable | not_found | unknown
```

Pool status describes control-plane ownership:

```text
free | claimed
```

Template List reads from SQLite, not arbitrary folders. It supports create/import, edit, rename, delete, show, and export workflows. Rename and delete must warn when existing sessions or configs reference the template.

## Critical Rules

- One physical device config may be driven by only one active dataflow at a time.
- One dataflow is owned by exactly one responsible session.
- One runtime agent controls one dataflow.
- One device may write to multiple sinks or mirror outputs; one sink belongs to one device flow.
- A sink failure makes its device flow unhealthy.
- Device and sink configuration cannot change after session start; the runtime manifest is the immutable record of what ran.
- Editing a device config is allowed only while it is free.
- Policy defaults to `Recommend`; there is no true "no policy" state.
- Only one state-changing operation may run on a dataflow or target stream at a time.
- Startup must fail closed on duplicate output paths, non-writable destinations, unsafe manifests, or ownership conflicts.

## Shared Monitoring And Ownership

The first session that drives a dataflow is the responsible owner and sole lifecycle controller for that dataflow.

Other sessions may monitor individual device streams through live fan-out. Monitoring does not claim or drive the device. A monitoring session can aggregate mirrored device streams from several different dataflows.

Stopping the responsible session stops the owned dataflow. Any monitoring sessions that depend on that live stream must show the mirror as stopped or needing attention rather than silently continuing as if collection still exists.

Session duplication follows these rules:

- Creating a new runnable session snapshots composition settings, then asks the user to resolve current device configs, sink destinations, and policy overrides.
- Exporting a session template from an active or completed session uses the runtime manifest snapshot so the artifact represents what actually ran.
- Runtime state, operation ids, runtime host ports/tokens, incidents, output segment ids, gaps, recovery history, and generated filenames are never copied into reusable templates.

## Recovery Policy

Policy modes:

```text
Recommend | Automate
```

- **Recommend:** software-fixable faults produce an explicit approval action; hardware or physical faults produce instructions. The system reports and waits.
- **Automate:** software-fixable faults may recover automatically when policy and preconditions allow it. Hardware or physical faults still become `Needs action`.

New or changed policies default to `Recommend`, but users may explicitly enable `Automate`.

The control plane owns policy, operation tracking, incident history, output safety, and cross-session impact checks. The runtime/watchdog may execute automatic recovery only when the control-plane recovery decision hook permits it. In `Recommend`, it must report and wait for an explicit guarded command.

Recovery follows:

```text
Suspect(+reason) -> Validate -> Recover -> Verify -> Healthy | Needs action
```

- `suspect` is a confirmation window, not an operator-facing action.
- If suspect resolves to healthy inside `suspect_window`, the dashboard does not interrupt the user.
- If suspect confirms as unhealthy, incident timing starts at the suspect moment.
- Validate checks preconditions such as ownership, command conflicts, output safety, sink writability, and policy.
- Verify is the single gate back to `Healthy`. A successful command is never trusted as a successful recovery on its own.

Verification may check device health, sink access, data rate, record format, timestamps, sequence continuity, and output segment safety.

Guarded recovery commands are a fixed catalog, not arbitrary scripts:

```text
start | stop | reconnect | restart | reset-stream
```

Whole-dataflow commands are `start` and `stop`. Recovery commands target a specific stream and must carry the target device plus a recovery id.

## Operations And Incidents

All state-changing actions become durable operations:

```text
request_key -> operation_id -> command_id
```

- `request_key` deduplicates or correlates a user/API request.
- `operation_id` is the dashboard-facing action id shown for start, stop, recover, watch, incident, and history workflows.
- `command_id` is lower-level runtime dispatch history and is mainly diagnostic.

Operation states:

```text
queued -> claimed -> dispatched -> running -> verifying -> succeeded
                                                     -> failed
                                                     -> uncertain
```

An unresolved `uncertain` operation blocks risky follow-up commands in the same conflict domain until an operator resolves it with a note.

Open an incident when a stream confirms unhealthy, a runtime becomes unreachable, an operation fails or becomes uncertain, output safety fails, or an operator starts manual recovery.

Acknowledging an incident only records operator awareness. It does not change runtime state or approve recovery.

Each incident should show the related session, dataflow, device or sink when known, runtime, operation, recovery id, reason, severity, policy version, timestamps, notes, status, and outcome.

## Output Safety

Output safety is a release blocker.

- Existing files are never overwritten or deleted by start or recovery.
- Output collisions fail before data collection starts.
- Non-writable destinations block startup.
- The system allocates a unique logical output segment per start and recovery.
- Segment metadata is persisted before a runtime opens or appends to files.
- Managed CSV recovery may append to the same session output path only when ownership, schema, and active runtime safety can be proven.
- If append safety cannot be proven, recovery must fail closed or allocate a new physical file.
- Recovery boundaries and gaps are recorded explicitly.
- If sample continuity cannot be proven, the gap is marked `uncertain`.
- Low storage produces a warning before it becomes a failed start or recovery.

Default filename:

```text
{session}_{device}_{sink}_{timestamp}.{extension}
```

## Monitoring And Communication

The watchdog/runtime reports on two independent axes:

- **Stream status:** whether the data stream is healthy.
- **Comms status:** whether the control plane can reach the runtime/watchdog.

Stream status:

```text
healthy | suspect | unhealthy
```

- **healthy:** stream is behaving normally.
- **suspect:** something looks wrong and is being confirmed inside a bounded window.
- **unhealthy:** confirmed, diagnosed fault. This feeds recovery validation; it does not map directly to `Needs action`.

Comms status:

```text
current | delayed | unreachable | stopped
```

- **current:** report received on time.
- **delayed:** one expected report missed; dashboard should avoid alarming on a single missed report.
- **unreachable:** repeated reports or probes missed; dashboard shows `Unknown`.
- **stopped:** intentional shutdown reported.

`suspect_window` and `unknown_timeout` are separate configurable values. They are tuned against different cadences and should not share a number by default.

After backend restart, the control plane must reattach to matching live runtime agents or reach a known failed/uncertain state. It must never double-spawn runtime agents for the same dataflow.
