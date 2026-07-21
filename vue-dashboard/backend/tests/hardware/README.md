# Hardware checkpoint tier (`tests/hardware/`)

A separate, opt-in test tier whose oracle is the **real system**, not a fake.
Use it at packet checkpoints to catch drift while it's cheap — 1–3 packets of
suspects — instead of after a big green chunk collapses on hardware.

## Why this exists

The fast suite (`tests/test_*.py`) invents its own envelopes and fakes the
process boundary (`gate=None`, in-process `test_client`). It proves the code is
*self-consistent*, not *correct*. This tier records what a **real watchdog**
sends over **real HTTP** and asserts the packet-3 contract against that. A green
here means "reality agrees with the spec."

## The pieces

| File | Role |
|---|---|
| `capture.py` | WSGI middleware that tees real ingest traffic to a JSONL fixture (raw bytes, before Flask parses — catches malformed / old-version bodies too) |
| `fault_menu.py` | The 7 physical faults (kill / respawn / double-send / counter-reset / outage). One function, `expected_after_respawn`, is **yours to implement** |
| `checkpoint.py` | Driver: stands up a real bound plane + real watchdog subprocess, walks the fault menu, writes the capture |
| `test_packet3_replay.py` | The 3 packet-3 ACs, replayed against the capture. Skips-with-a-finding until the contract is real |

## Running a checkpoint

1. **Capture real traffic** (needs hardware / Morelia importable):

   ```
   venv\Scripts\python.exe -m tests.hardware.checkpoint --session-id <id>
   ```

   Writes `fixtures/packet3_capture.jsonl`.

2. **Replay the ACs against it:**

   ```
   $env:RUN_HARDWARE = "1"; venv\Scripts\python.exe -m pytest tests/hardware -v
   ```

Without `RUN_HARDWARE=1` the whole tier is skipped, so it never affects the fast
suite.

## Multi-sink release evidence (packet 30)

Ordinary CI never requires hardware. For a Pod8206HR / Pod8401HR release lane,
capture a multi-sink matrix and record it on `fixtures/latest_run_meta.json`:

```json
{
  "mode": "watchdog",
  "sink_matrix": [
    {"sink_id": "pod8206hr:1:csv", "sink_type": "csv"},
    {"sink_id": "pod8206hr:1:edf", "sink_type": "edf"},
    {"sink_id": "pod8206hr:1:influx", "sink_type": "influx"},
    {"sink_id": "pod8206hr:1:plot", "sink_type": "plot"}
  ],
  "failure_injection": "watchdog-kill",
  "artifacts": ["path/to/capture.jsonl"],
  "pass": true
}
```

Then:

```
$env:RUN_HARDWARE = "1"
venv\Scripts\python.exe -m tests.hardware.checkpoint --template <multi-sink> --kill watchdog
venv\Scripts\python.exe -m pytest tests/hardware/test_crash_recovery.py -v
```

`test_multi_sink_matrix_evidence_recorded_when_present` SKIPs when `sink_matrix`
is absent (legacy CSV captures) and FAILs when present but incomplete / secret-
bearing. Device, sink matrix, failure injection, artifacts, and pass/fail are
the packet-31 support-matrix inputs.

Automated (non-hardware) packet-30 gates live in:

- `tests/test_multi_sink_runtime.py` — five release-critical scenarios
- `tests/test_service_sink_outages.py` — Influx/Quest outbox bounds + replay

## What the skips mean (they're the point)

Run the replay **today**, before packet 3 exists, and it will skip with:

> packet 3 envelope is not real yet — the live watchdog never emits
> ['report_id', 'watchdog_id', ...]

That skip is a finding: packet 3's edit set doesn't touch `driver.py` /
`server.py`, but its contract needs those fields on the wire. The harness surfaces
that cross-process gap before you write a line of the packet — instead of after
400 green tests fall over on hardware.

## The one decision that's yours

`fault_menu.expected_after_respawn()` encodes the dedupe key — `report_id`
alone, or `(watchdog_id, report_id)` — which depends on how Morelia mints
`report_id` (UUID vs per-process counter). Read the vendored `Watchdog/` code,
then implement it. That choice shapes AC3, and no generated test can make it for
you.
