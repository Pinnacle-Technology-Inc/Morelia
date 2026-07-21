# Packet 22A — Render sink state in CLI status output

Status: ready  
Size: S  
Depends on: 05, 22

## Purpose

Update session preview, status, and watch output so operators can distinguish source, individual sink, and transport/finalization conditions.

## Prior state

CLI output assumes one sink and source-centric health, so a remote destination outage or file finalization can be hidden or mistaken for source failure.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “CLI” and release-critical scenarios 2–5.
- `app/cli/session_cmd.py` — preview/status/watch rendering.
- `app/api/schemas.py` — canonical sink configuration/status shapes.
- `tests/test_pinnacle_session_preview.py` — preview rendering cases.
- `tests/test_pinnacle_session_cmd.py` — status/watch command tests.

## Exact edit set

- `app/cli/session_cmd.py`
- `tests/test_pinnacle_session_preview.py`
- `tests/test_pinnacle_session_cmd.py`

## Scope boundaries

Do not change API aggregation, runtime recovery policy, or create-quiz behavior. Never print raw Plot samples, resolved tokens, or unbounded diagnostics.

## Contract / invariant

CLI groups ordered sinks beneath each source and labels source health, sink health, delivery/transport state, buffering/loss, component, and finalization independently.

## Acceptance criteria

1. Preview shows canonical non-secret configuration for every selected sink and identifies file-conflict targets by source nickname plus `sink_name`.
2. Status/watch visibly distinguish healthy source with degraded sink, buffering, permanent loss, stale status, active component, and finalizing/finalized output.
3. Output ordering is stable, diagnostics are bounded/redacted, and legacy one-sink responses remain readable during rollout.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_pinnacle_session_preview.py tests/test_pinnacle_session_cmd.py
```

## Failure handling

If a response omits new fields during rolling upgrade, render the sink as unknown/legacy rather than healthy and continue showing the remaining sources/sinks.

## Handoff note

Capture representative healthy, degraded, loss, and finalizing CLI output for the operator runbook.
