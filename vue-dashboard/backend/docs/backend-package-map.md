# Backend Package Map

This backend is being refactored toward clearer control-plane layers without
renaming `app/runtime_host`. The runtime host remains the process that owns one
dataflow and accepts lifecycle commands.

## Overall Structure
```text
Vue Dashboard
Terminal CLI
        |
        v
+-----------------------------+
| Control Plane Daemon        |
|                             |
| Flask API                   |
| Application Services        |
| SQLite Repositories         |
| Alembic Migrations          |
| Dataflow Control Supervisor |
| Dataflow Control Client     |
+-----------------------------+
        |
        v
+-----------------------------+
| Dataflow Control Host       |
|                             |
| Lifecycle Safety Gatewa     |
| Runtime Control Driver      |
| Manifest Factory            |
| Recovery Policy Controller  |
| Output Manager              |
+-----------------------------+
        |
        v
+-----------------------------+
| Morelia Watchdog / DataFlow |
|                             |
| Watchdog                    |
| DataFlow                    |
| Devices                     |
| Sinks                       |
+-----------------------------+
```
## Current Package Boundaries

| Package | Owns | Rule |
| --- | --- | --- |
| `app/api` | Flask route adapters | Translate HTTP to service calls; no business rules. |
| `app/services` | Use cases and control-plane decisions | Validate intent, coordinate repositories/adapters, raise domain errors. |
| `app/repositories` | SQLAlchemy reads/writes | No Flask imports and no workflow decisions. |
| `app/models` | ORM persistence shapes | Tables and JSON columns only. |
| `app/domain` | Stable domain vocabulary/errors | New code should import enums/errors from here. |
| `app/contracts` | Cross-process contract import surfaces | Runtime command, manifest, acknowledgement, and report shapes. |
| `app/adapters` | External-system clients | New south-bound clients should enter here. |
| `app/runtime_host` | Per-dataflow host process | Keep this name; it owns lifecycle safety and command handling. |
| `app/runtime_child` | Driver interface and implementations | Fake runtime now; Morelia driver later. |
| `app/control` | Runtime host supervision | Spawn/reconcile runtime host processes from persisted session state. |
| `app/watchdog` | Existing v1 command protocol implementation | Compatibility namespace until callers move to `app/adapters`/`app/contracts`. |

## Current Codebase Structure

```text
backend/
  app/
    domain/
      enums.py                 # SessionStatus, PolicyMode, StreamStatus, incidents/gaps
      errors.py                # typed domain exceptions
      # later: ids.py, entities.py, value_objects.py if they become real concepts

    database.py                # db extension, migrations extension, transaction()

    models/
      session.py
      device_template.py
      incident.py
      recovery_gap.py
      # later: device.py, runtime.py, operation.py, output_segment.py, event.py

    repositories/
      sessions.py
      device_templates.py
      incidents.py
      recovery_gaps.py
      # later: devices.py, runtimes.py, operations.py, outputs.py, events.py

    services/
      sessions.py
      device_templates.py
      session_config.py
      registry.py              # current device/sink type registry
      # later: device_discovery.py, manifest_resolver.py, operations.py,
      #        recovery.py, incidents.py, output_segments.py, events.py

    control/
      supervisor.py            # current runtime supervisor / startup reconciler seed

    adapters/
      runtime_client.py        # south-bound Runtime Host HTTP client surface
      # later: morelia_discovery_provider.py

    api/
      schemas.py               # HTTP API schemas
      sessions.py              # session routes
      store.py                 # legacy/in-memory support
      # later: config_routes.py, device_routes.py, runtime_routes.py,
      #        operation_routes.py, incident_routes.py

    contracts/
      runtime_protocol.py      # runtime command/report/manifest import surface
      # later: api_models.py, events.py, errors.py

    runtime_host/
      __main__.py              # executable host entrypoint
      lifecycle.py             # command gateway + lifecycle lock
      manifest.py              # runtime manifest
      server.py                # Runtime Host HTTP server/status reporter

    runtime_child/
      driver.py                # RuntimeControlDriver and report contracts
      fake.py                  # FakeRuntime driver
      # later: Morelia-backed driver, recovery policy, output manager

    watchdog/
      messages.py              # existing v1 command envelope
      commands.py              # command preparation/correlation
      adapters.py              # existing HTTP adapter implementation
      dispatcher.py
      receiver.py

    errors.py                  # Flask problem+json adapter
    health/
      routes.py

  migrations/
    env.py
    versions/
      0001_baseline_schema.py
      0002_sessions.py
      0003_runtime_endpoint.py
      0004_device_templates.py
      0005_incidents_and_recovery_gaps.py
```


## Canonical Surfaces

These modules are the package names new backend code should use:

- `app.domain.enums` owns the backend's enum definitions.
- `app.domain.errors` owns the backend's typed domain exceptions.
- `app.contracts.runtime_protocol` exposes runtime command/report/manifest types.
- `app.adapters.runtime_client` exposes the existing watchdog HTTP adapter with
  clearer aliases.

## Next Passes

- Wire runtime reports/recovery events into `IncidentRepository` and
  `RecoveryGapRepository`.
- Add API and CLI read/ack surfaces for incidents and recovery gaps.
- Add output segment persistence before recovery gap recording needs concrete
  previous/next segment rows.
- Keep existing imports stable until a file is touched for feature work, then
  migrate that file to the clearer import surface.
