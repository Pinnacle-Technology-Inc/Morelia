# Packet 05 — Add sink selection to the create quiz

Status: ready  
Size: M  
Depends on: 03, 04

## Purpose

Let operators add, edit, remove, order, and validate sinks while creating a session or section template from the CLI.

## Prior state

Guided creation prompts for one CSV-oriented sink and cannot build repeated sink types or the template sink contract.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “CLI”, “Template import/export”, and gap SINK-25.
- `app/cli/session_cmd.py` — `_prompt_sink`, `_prompt_template_flow_sink`, guided create, and template flows.
- `app/services/registry.py` — discoverable sink choices and parameter metadata.
- `tests/test_pinnacle_session_create_guided.py` — guided session cases.
- `tests/test_pinnacle_session_template_export.py` — template prompt/export cases.
- `tests/test_pinnacle_session_cmd.py` — command behavior and error rendering.

## Exact edit set

- `app/cli/session_cmd.py`
- `tests/test_pinnacle_session_create_guided.py`
- `tests/test_pinnacle_session_template_export.py`
- `tests/test_pinnacle_session_cmd.py`

## Scope boundaries

Do not contact Influx or Quest, resolve environment variables, open output files, or add runtime/status behavior. Never prompt for an Influx token value.

## Contract / invariant

The quiz builds the exact canonical `sinks[]` payload. Retry/edit identity is `(source nickname, sink_name)`, not sink type, so repeated types remain addressable.

## Acceptance criteria

1. Guided session and template creation support add/edit/remove/reorder for all registered types and require at least one sink.
2. Type-specific prompts collect only public configuration, including an Influx token environment-variable name.
3. Validation failures return to the affected sink without discarding valid siblings or changing their order.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_pinnacle_session_create_guided.py tests/test_pinnacle_session_template_export.py tests/test_pinnacle_session_cmd.py
```

## Failure handling

If prompt mocking becomes coupled to implementation order, introduce named prompt helpers instead of weakening behavior assertions.

## Handoff note

Capture the final prompt sequence and one multi-sink transcript for rollout documentation.
