# System Audit — Implementation Roadmap (Patch Period)

## Status

**This is the working reference during the codebase-patching period.** It turns
the gaps in [`system-audit.md`](./system-audit.md) into an ordered, dependency-
aware task plan that closes the code↔plan gap against
[`backend-control-plane-architecture-plan.md`](./backend-control-plane-architecture-plan.md).

- **Date:** 2026-07-02; last re-audited against the code 2026-07-13.
- **Design authority:** the architecture plan (the "why").
- **Current-state authority:** the system audit (the "what exists").
- **Execution authority:** this doc (the "what to build, in what order").
- **This doc now tracks only outstanding work.** Completed milestones are removed
  as they land. **Done and removed:** M1, M2, M3 and M5 in full; M4 except 4c;
  M6 except 6d; migration packets 02–04 (runtime/watchdog identity schema,
  direct-ingest event identity + active-watchdog fencing, watchdog SQLite outbox).
  Their status detail lives in git history and the code itself.

## Outstanding work — priority order

1. **0a** — hardware verification + retire the fake tests. 🎯 The real gate on
   calling the first slice done.
2. **Safe-stop guardrail** — 🎯 correctness follow-up; clean-stop proof, and a
   prerequisite for 6c's `--force` semantics.
3. **Migration packets 05–12** — continue the runtime_host/watchdog-process
   split; **05** (watchdog process entrypoint) is next.
4. **6d** — southbound command log + `runtime command list/show`.
5. **4c** — stealable soft device reservations.
6. **M7** (7a–7d) + Phase 8 — deferred beyond the first slice (see *Out of scope*).

## Ground rules for this patch period

- **First slice was `pod8206hr` + `pod8401hr` with managed `csv`.** That unlocked
  the control plane. **All-sink support is now implemented** (csv/edf/pvfs/influx/
  quest/plot) — see [`docs/sinks/support-matrix.md`](./sinks/support-matrix.md)
  and [`docs/sinks/operator-runbook.md`](./sinks/operator-runbook.md). Task **7d**
  below is historical for EDF; do not treat it as still deferred.
- **Verification:** hermetic suite for contracts; hardware opt-in via
  `RUN_HARDWARE=1` (`tests/hardware/`). Pure-logic tests that use neither fakes nor
  hardware may remain.
- **Morelia source is available** (editable install at `C:\Users\ahoang\Morelia\src`
  — all five `PodDevice_*` classes), so param schemas can be pinned from property
  maps.
- Legend: 🎯 critical path to the first slice · ○ parallel/UX · ⏸ deferred.

## North star — first-slice acceptance path (hardware lane)

The end-to-end happy path a real `pod8206hr` / `pod8401hr` must pass — this is the
target 0a verifies:

```text
pinnacle start                    # start the daemon
pinnacle device list              # discover devices; note the device id (serial)
pinnacle device config 21172      # questionnaire → create a port-bound device config
pinnacle device template export <device-id-or-nickname> <output-name>
pinnacle session create           # questionnaire → compose configs + sink + policy
pinnacle session start            # start collection; AUTO-attaches `session watch`
                                  #   (opt out with --watch=false)
pinnacle session status           # runtime/stream/health for the session
pinnacle session stop             # stop collection, finalize output
```

Two distinct `start`s: `pinnacle start` (daemon) vs `pinnacle session start`
(collection). `session start` auto-invokes `session watch` unless `--watch=false`.

## 0a — Retire fake tests + establish the hardware gate *(🎯 highest priority)*

Unblocked: 4d has landed, so `MoreliaRuntime` is the working alternative the fake
driver was standing in for (the fake driver couldn't be deleted until the real one
worked, since it was the only alternative). Steps, across the ~80 tests that
currently depend on `FakeRuntime`/`FakeDiscoveryProvider`:

1. **Add the marker infrastructure.** Register `hardware` in `pytest.ini`/
   `pyproject.toml` markers and a `conftest.py` autoskip: skip `@pytest.mark.hardware`
   unless `PINNACLE_HARDWARE_TESTS=1`.
2. **Delete outright:** `tests/test_fake_runtime.py`,
   `tests/test_fake_runtime_output_safety.py` (they characterize the fake's own
   scripted behavior — nothing left to characterize).
3. **Convert to hardware-gated:** mark `tests/test_stage7_end_to_end.py`
   `@pytest.mark.hardware`; add a new hardware smoke test driving `session start`/
   `session recover` against a real pod8206hr/pod8401hr.
4. **Keep, but drop the shared production fake** in favor of a small local stub
   defined in-file (mirror `test_morelia_runtime.py`'s local `FakePod8206HR`/
   `FakeWatchdog`): `test_runtime_host_contract.py`, `test_runtime_host_lifecycle.py`,
   and the `FakeDiscoveryProvider` dependents `test_device_discovery.py`,
   `test_device_config_api.py`.
5. **Fix `test_morelia_runtime.py`'s `FakeWatchdog`** to match the real (post-4d)
   `Watchdog` API — the `recovery_policy`/`stream_command` invention is now stale —
   and add Pod8401HR coverage.
6. **Retire the fake driver itself** (`--driver=fake` / `FakeRuntime`) once the
   above is green with hardware.
7. **Run the hardware lane** and confirm the default no-hardware run stays green.

**Hardware test-run procedure:** set `PINNACLE_HARDWARE_TESTS=1` and attach a real
pod8206hr and/or pod8401hr before running `venv/Scripts/python.exe -m pytest -q` —
`@pytest.mark.hardware` tests skip automatically when the env var is unset, so the
default (no-hardware) run stays green. `RUNTIME_DRIVER=morelia` and `MORELIA_SRC`
(or a pip-installed `ptech_morelia`) must also be resolvable for anything that
spawns a runtime host against real hardware.

## Safe-stop completion guardrail *(🎯 correctness; prerequisite for 6c `--force`)*

**Confirmed against `services/sessions.py:311`** (`stop_managed`): it transitions
to `ENDING`, dispatches stop, then **immediately** marks the operation `SUCCEEDED`,
sets the session `COMPLETED`, and releases claims (lines ~374–382) with no proof
the runtime actually stopped.

Current risk: `session stop` can mark a session `completed` before the control
plane has durable proof the runtime stopped. User-visible symptom:
`session.status == completed` while the latest runtime `phase` still reads
`running`. That can be transient event-ingest lag, but if it persists it means
lifecycle bookkeeping has moved ahead of runtime evidence.

Guardrail to add:

1. Keep the `ENDING` + dispatch step.
2. Before marking the stop operation `succeeded` or the session `completed`,
   require **one** stop proof:
   - runtime `/status` reports `phase in {"stopped", "closed"}`;
   - latest ingested runtime report for the dataflow has `phase="stopped"` and
     `comms="stopped"`;
   - the runtime process exited after acknowledging stop.
3. Only after proof: release device claims and clear `runtime_port`/`runtime_token`.
4. If proof is missing, mark the operation `failed`/`uncertain`, **keep** the
   runtime identity + claims, and leave the session retryable (`ending` or restored
   to `active`).
5. **Do not** paper over it by hiding `phase` in the status API — `status` is
   durable session lifecycle; `phase` is latest runtime evidence. The root fix is
   making `completed` require stop evidence.

## Migration packets 05–12 — runtime_host / watchdog-process split

Goal: keep the daemon-facing `runtime_host` contract stable, move the hardware-
owning Morelia `Watchdog` runtime into a supervised watchdog process, and have that
process write telemetry to a local SQLite outbox and ingest directly to the control
plane. The full task breakdown, the `runtime_id`/`watchdog_id` identity model, and
the global invariants (active-watchdog fencing, respawn claim policy, stop proof)
are the authoritative source in
[`docs/migration/README.md`](./migration/README.md) as packets 02–12. Do not
maintain a second, divergent task list here.

Packets 02–04 have landed (identity schema, direct-ingest event identity +
fencing, SQLite outbox). Remaining:

| Packet | Task | Status |
|---|---|---|
| 05 | Add watchdog process entrypoint | 🔲 **next up** — `watchdog_process/__init__.py` present but no process entrypoint / outbox-flush loop yet. Wires the host-to-watchdog IPC surface packets 06–09 build on. |
| 06 | Make `runtime_host` supervise watchdog process | 🔲 not started |
| 07 | Fence commands with active watchdog identity | 🔲 not started |
| 08 | Add respawn claim policy | 🔲 not started |
| 09 | Require stop proof before completion | 🔲 not started |
| 10 | Update status, monitoring, incidents, and gaps | 🔲 not started |
| 11 | Add migration test gates | 🔲 not started |
| 12 | Promote device nickname to device-config alias | 🔲 not started |

Do not include `runtime command list/show` (6d) in this migration unless 6d has
already landed. The split should expose enough in `/status` and logs to debug the
watchdog process first; durable command history can trail as its own operator-
surface task.

## 6d — Southbound command log + `runtime command list/show` *(○)*

No `runtime_command` model today; `runtime` CLI has only `list`/`reconcile`.

1. New `runtime_command` model + migration: one row per command dispatched to a host
   (start/stop/recover), with `dataflow_id`, `command`, `target_device_id`, `command_id`,
   timestamps, ack/result.
2. Repository + write calls at each `supervisor.dispatch(...)` site in `services/sessions.py`.
3. `GET /runtimes/commands` (+ `/<id>`) read route.
4. `runtime command list/show` CLI in `runtime_cmd.py`, matching the `operation`/`incident` shape.

## 4c — Stealable soft reservations *(○)*

`device_configs.claim()` has no `force` param and there is no `DeviceClaimConflict`
error today.

1. Add a typed `DeviceClaimConflict` (`domain/errors.py`) raised by `device_configs.claim()`
   when a config is already claimed.
2. Add a `force=False` parameter to `claim()` that steals an existing claim (releasing the
   prior holder) when `True`.
3. Surface `--force` on the relevant `session`/`device` command and map the conflict to a
   typed problem response.

## M7 — Deferred (do not start without a scope decision)

- **7a** — Producer/Consumer split + publisher→subscriber-list **seam, dormant**
  (owner = subscriber #0) so monitoring is not a later rewrite. ⏸ (seam in v1)
- **7b** — Monitor feature: `monitor_subscription` row, `monitor` command,
  hardware-free subscriber agent, owner-direct dispatch + shared safe-sink-writer. ⏸
- **7c** — Broaden registry to models 46/50/52 (real param schemas from Morelia maps). ⏸
- **7d** — Output-safe non-`csv` sinks (EDF/PVFS + service/plot): **done** via
  [`docs/sinks/`](./sinks/README.md) packets 14–28/30. Retained here only as a
  historical checklist item; use the support matrix for current readiness.

## Out of scope for this roadmap (deferred beyond the first slice)

Tracked so they are not silently dropped; **not** part of the first-slice patch work.

- **Plan Phase 8 — schedules, session duplication, shared-dataflow supervision.**
  Not started. Revisit after the first slice + operation safety are proven.
- **Monitor *feature*** (7b) — only the dormant publisher→subscriber **seam** (7a)
  is in-scope-adjacent; the live monitor feature is deferred.
- **Device breadth 46/50/52** (7c). Non-`csv` sinks (historical 7d) are shipped —
  see [`docs/sinks/support-matrix.md`](./sinks/support-matrix.md).
- **Vue dashboard controls** — CLI remains first-class; live Plot is available in
  the Vue session detail page ([`docs/sinks/operator-runbook.md`](./sinks/operator-runbook.md) §6).

## Verification for outstanding work (hardware lane)

- **0a / full slice:** the North-star acceptance path passes on a real `pod8206hr`
  and a real `pod8401hr`; `@pytest.mark.hardware` tests run green with hardware
  attached, and the default no-hardware run stays green.
- **Safe-stop:** a `session stop` cannot reach `completed` without stop proof; a
  missing proof leaves the session retryable with claims intact.
- **M8 (packets 05–12):** `runtime_host /status` stays reachable while the watchdog
  process is healthy, stopped, or crashed; watchdog-process restart attempts do not
  duplicate event identity for the same dataflow (packet 03, done); clean stop is
  not marked complete without stop proof (packet 09); watchdog-process stderr is
  available through the runtime diagnostic path.
