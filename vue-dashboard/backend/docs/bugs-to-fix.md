# Bugs to Fix

## Pinnacle startup aborts when a persisted dataflow cannot reopen its devices

### Status

Confirmed on Windows on 2026-07-22. Not yet fixed.

### Summary

When Pinnacle restarts with a session that still has a runtime-host identity, startup reconciliation probes the recorded runtime port. If that host is gone, reconciliation attempts to spawn a replacement runtime. When one of the replacement runtime's configured COM devices is absent, unavailable, or busy, the replacement fails during preflight. That exception currently escapes synchronous application startup and prevents the entire Pinnacle control plane and dashboard from starting.

One unavailable dataflow should not make the control plane unavailable.

### Observed failure

The confirmed incident involved:

- Dataflow ID: `200bd7f5b170458eb31084ee31b6be7c`
- Recorded runtime port: `56890`
- Configured devices: COM4 (`pod8206hr:21145`) and COM3 (`pod8401hr:0002A`)
- Initial reconciliation result: the recorded runtime did not answer and there was no active runtime ownership
- Replacement result: a new runtime host was spawned, but its watchdog exited before reporting `READY`
- Root exception: `ConnectionRefusedError: [WinError 10061]`

Historical runtime events for the same dataflow already contained repeated serial failures on COM3 and COM4:

```text
SerialException: Cannot configure port, something went wrong.
Original message: PermissionError(13, 'Access is denied.', None, 5)
```

At investigation time, no Pinnacle runtime host, watchdog, Morelia worker, or queue-server Python process remained alive. Windows reported COM3, COM4, and COM5 with status `Unknown`, while COM1 was `OK`. This means a surviving orphan process was not blocking the observed restart at that time; the configured USB serial devices were unavailable or unhealthy.

### Failure chain

1. Startup finds a session with a persisted `runtime_port`.
2. Reconciliation probes that port and receives no response.
3. With no active ownership row, reconciliation falls through to a fresh replacement spawn.
4. The replacement watchdog begins Morelia hardware preflight.
5. Opening the configured COM port raises `SerialException`.
6. `PortIO.is_port_in_use()` converts every `SerialException` into `True`.
7. `BasicPodProtocol` interprets `True` as proof that another Morelia process owns the port and attempts to register with its deterministic local queue server.
8. No queue server is listening, so `PacketManager.register_control_queue()` eventually raises `ConnectionRefusedError`.
9. The watchdog exits before `READY`, followed by the runtime host exiting before reporting its port.
10. The replacement-spawn exception escapes `HostSupervisor.reconcile()` during `create_app()`, aborting the whole Pinnacle daemon.

The persisted runtime identity initiates the recovery path, but it is not itself the resource blocking execution. The immediate hardware failure and the unhandled reconciliation exception cause startup to abort.

### Expected behavior

If a replacement runtime cannot open its configured devices, Pinnacle should:

- terminate and reap every partially started runtime, watchdog, worker, and queue-server process;
- release all hardware leases acquired by the failed attempt;
- clear or stop ephemeral runtime identity and ownership state for that failed attempt;
- preserve the session, dataflow configuration, output references, and event history;
- mark the dataflow as `blocked`, `device_unavailable`, `interrupted`, or another explicit actionable state;
- record the specific device and underlying serial error;
- continue starting the control plane and dashboard; and
- allow an operator to retry or resume the dataflow after restoring the device.

A suitable user-facing message would be:

```text
Pinnacle started. Dataflow 200bd7f5b170458eb31084ee31b6be7c could not
resume because COM3 and COM4 are unavailable. Its failed runtime state was
cleaned up. Reconnect the devices and retry the dataflow.
```

### Why not clear the entire dataflow?

Automatically deleting or completing the session and dataflow is unsafe. A COM port can be unavailable temporarily because:

- USB enumeration has not finished during startup;
- a cable was briefly disconnected;
- Windows is reinitializing the device or driver;
- another application temporarily owns the port; or
- Windows assigned the device a different COM number.

Deleting persistent configuration would discard operator intent and diagnostic evidence because of a potentially transient hardware condition. Marking the experiment completed would also falsely imply a normal shutdown.

Cleanup must distinguish between state categories:

| State | Action after failed replacement startup |
| --- | --- |
| Runtime PID, port, token, and active ownership | Clear or mark stopped |
| Partial watchdog, workers, and queue servers | Terminate and reap |
| Hardware leases | Release |
| Session and dataflow configuration | Preserve |
| Output references and historical events | Preserve |
| Experiment execution status | Mark blocked or interrupted with a reason |
| Control plane and dashboard | Continue starting |

Complete deletion should require an explicit operator action.

### Required fixes

#### 1. Make Morelia serial ownership detection evidence-based

`PortIO.is_port_in_use()` must not treat every `SerialException` as proof that another Morelia process owns the port.

The initialization path should distinguish at least:

- device absent or disconnected;
- access denied or port busy;
- device/driver configuration failure; and
- an existing Morelia owner with a reachable, authenticated, identity-matching queue server.

Before registering with an existing queue server, verify that the expected server is reachable and belongs to the expected device. If that cannot be proven, return or raise a typed hardware-availability error containing the original serial failure instead of surfacing a misleading loopback `ConnectionRefusedError`.

Relevant code:

- `src/Morelia/Devices/SerialPorts/SerialComm.py`: `PortIO.is_port_in_use()`
- `src/Morelia/Devices/BasicPodProtocol.py`: constructor ownership branch
- `src/Morelia/Devices/SerialPorts/queue_manager.py`: queue-server initialization and registration

#### 2. Isolate replacement-spawn failures during Pinnacle reconciliation

`HostSupervisor.reconcile()` should catch a failure to spawn one replacement runtime. It should clean up the failed attempt, persist an actionable failure state, add the dataflow to the reconciliation report, and continue reconciling other sessions.

Application creation must not fail solely because one previously active dataflow cannot reopen its hardware.

Relevant Pinnacle code:

- `vue-dashboard/backend/app/control/supervisor.py`: `HostSupervisor.reconcile()` and `spawn()`
- `vue-dashboard/backend/app/__init__.py`: startup reconciliation during `create_app()`
- `vue-dashboard/backend/app/cli/lifecycle.py`: daemon startup and teardown

#### 3. Verify Ctrl+C cleanup semantics

The current daemon lifecycle intends to run `stop_all(force=True)` from a `finally` block for a normal Ctrl+C unwind. Add an end-to-end regression test proving that Ctrl+C:

- stops runtime hosts and watchdog process trees;
- releases hardware leases;
- leaves no active ownership row;
- leaves the session recoverable; and
- permits the next Pinnacle start even when the physical device is subsequently absent.

`pinnacle shutdown` remains the preferred explicit daemon command, but ordinary Ctrl+C must be safe and supported. Force-closing the terminal or externally killing the process is a separate crash-recovery scenario.

### Acceptance criteria

- Pinnacle starts its control plane and dashboard when one persisted dataflow references a missing COM device.
- The affected dataflow is visible with an actionable blocked/interrupted status and the correct device-level cause.
- A failed replacement leaves no live descendants, runtime identity, active ownership, or hardware lease.
- Other valid dataflows are still adopted or restarted.
- Reconnecting the device and retrying resumes the preserved dataflow without recreating its configuration.
- A missing COM port does not produce a misleading queue-server connection error as the primary diagnostic.
- Tests cover absent devices, busy devices, unavailable queue servers, partial-spawn cleanup, multiple-session reconciliation, and Ctrl+C restart behavior.


- have no or less restriction on hardware_id
- change the device scan and choice  in session create and block any device that doesnt exist
