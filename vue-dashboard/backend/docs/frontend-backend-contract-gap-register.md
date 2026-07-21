# Frontend–Backend Contract Gap Register

Date: 2026-07-21  
Scope: session/stream health, device availability, uncertain-operation resolution, session-template planning, and the related device-test provenance failures.

## 1. Executive conclusion

The frontend/backend merge is **not ready for packetization as one combined integration change**. Five independent gaps remain, and the highest-impact gap is an authority contradiction: the current architecture plan, backend serializer, and backend test all require transient `suspect` stream status to be serialized as `healthy`, while the newer product decision requires a visible yellow `Suspect` state. Changing only the frontend cannot recover evidence that the backend has already removed.

Operation resolution is also incomplete as a state transition. The API records who resolved an uncertain operation and why, but it does not accept the operator's required `succeeded` or `failed` outcome and therefore leaves the operation in `uncertain`.

Device availability is implemented in the backend as the agreed three-state vocabulary (`available`, `unopenable`, `not_found`), but the UI inventory and frontend mappings omit `unopenable`. Session-template CRUD exists, while the agreed non-mutating assignment-planning endpoint does not.

The earlier combined device test result of **9 passed, 3 failed** is retained as reported evidence, not re-verified evidence. This environment could not execute the repository virtual environment (`Access is denied`), and no system Python launcher was available. The exact failing test node IDs therefore remain to be captured before implementation packets are finalized.

## 2. Authority and repository health

### Authority

| Concern | Intended authority | Current-state authority | Verification authority | Finding |
|---|---|---|---|---|
| Health/status vocabulary | New product decision recorded in the 2026-07-21 contract discussion | `app/services/session_status.py`, API schemas, Vue adapters | `tests/test_session_status_api.py`, health-state tests | New intent conflicts with the checked-in architecture and tests. |
| Device availability | `docs/backend-control-plane-architecture-plan.md` | discovery service and API schemas | discovery/device API tests | Backend consistently uses three states; frontend inventory is stale. |
| Operation resolution | Architecture CLI contract plus new product decision | operation API/service/model | operation-resolution API/CLI tests | Existing implementation records an audit acknowledgement, not an outcome transition. |
| Template planning | New product decision: shared non-mutating planner used by CLI and UI | No production route/service identified | No planner contract tests identified | Intended behavior has not yet been promoted into a checked-in authoritative backend contract. |

### Repository health

**Observed:** the backend worktree is heavily modified and contains numerous untracked production files, tests, migrations, documentation files, and instance templates. This makes historical attribution and clean failure classification difficult. The new gap register should be committed with the eventual contract changes rather than left as an untracked handoff artifact.

**Observed:** `tests/` itself is currently untracked in backend `git status`, so test visibility to version control must be resolved before packet readiness can be declared.

## 3. Critical observable scenarios

### Scenario A — operator reads live health and device availability

- Initial durable state: a session exists; the newest runtime report contains a `suspect` stream, or a discovery scan contains an `unopenable` device.
- Initiating event: the UI requests session status or the device pool.
- Expected transition: none; this is read-only.
- Expected result: the API preserves `suspect`; the UI shows a yellow `Suspect` badge. The API and UI preserve `unopenable` as a distinct availability state.
- Forbidden result: `suspect` is silently rewritten to `healthy`; `unopenable` disappears, is shown as `available`, or is shown as `not_found`.

### Scenario B — operator resolves an uncertain operation

- Initial durable state: an operation is terminal `uncertain`, unresolved, and blocks conflicting risky commands.
- Initiating event: the operator submits `outcome=succeeded|failed`, identity, and a resolution note.
- Expected transition: `uncertain -> succeeded|failed`; resolution audit fields are stored atomically; the conflict lock is released according to the terminal-state rules.
- Expected result: API, CLI, and UI return the chosen terminal outcome and retained audit evidence.
- Forbidden result: the request records `resolved_at` while the operation remains `uncertain`, or releases the lock without a durable chosen outcome.

### Scenario C — UI or CLI plans a session from a template

- Initial durable state: a reusable session template exists; the device pool may contain free, claimed, unconfigured, missing, or unopenable devices.
- Initiating event: a client requests a plan for the named template.
- Expected transition: none; planning is non-mutating.
- Expected result: both clients receive the same proposed device assignments, unresolved requirements, and reasons an assignment cannot be made.
- Forbidden result: planning claims hardware, creates a session, edits a template, opens a serial port, or gives CLI and UI different assignment logic.

## 4. Boundary map

```text
runtime report
  -> event persistence
  -> session_status._latest_report
  -> GET /api/v1/sessions/{id}/status
  -> frontend status adapter/badge

device scan + persisted device config
  -> discovery/device-pool join
  -> DevicePoolRowSchema
  -> frontend availability adapter/badge

UI or CLI resolution form
  -> POST /api/v1/operations/{id}/resolve
  -> ResolveOperationSchema
  -> operations.resolve_uncertain_operation
  -> operation state + audit fields + conflict behavior

UI or CLI template flow
  -> proposed POST /api/v1/session-templates/{name}/plan
  -> shared non-mutating planner service
  -> device/template repositories
  -> assignment proposal (no claims or writes)
```

The health boundary currently loses information in `session_status._hide_suspect`. The operation boundary currently loses the chosen outcome because the request schema has no outcome field. The template-planning boundary is absent.

## 5. Contract-coverage matrix

| Behavior | Intended source | Production path | Boundary crossed | Positive proof | Negative proof | Runtime proof | Status |
|---|---|---|---|---|---|---|---|
| Preserve and display `suspect` | 2026-07-21 product decision | `_hide_suspect` currently rewrites it | watchdog report → API → Vue | Vue has a `Suspect` badge and adapter mapping | Backend test proves the opposite behavior: suspect becomes healthy | Hardware fixtures contain raw suspect reports, but no current end-to-end UI proof | `contradicted` |
| Preserve three availability states | architecture lines 692–705 | schemas accept all three | scan/config join → API → Vue | backend schema and discovery code include all three | frontend inventory/mappers omit `unopenable` | no browser/runtime proof captured | `partially_verified` |
| Resolve uncertain op to selected outcome | architecture CLI example line 1164 and 2026-07-21 decision | resolve route/service | UI/CLI → API → DB/locking | audit metadata is persisted and API-tested | no outcome input or state-transition proof | none | `contradicted` |
| Non-mutating template assignment plan | 2026-07-21 product decision | no route/service | client → planner → repositories | template CRUD exists | no mutation-safety or CLI/UI parity proof | none | `unverified` |
| Device provenance tests are green | test suite | device config/template services | filesystem/DB provenance | earlier run reportedly had 9 passing tests | three failures reportedly remain | current rerun unavailable | `unknown` |

## 6. Human decisions and unresolved questions

| Decision | Status | Effect |
|---|---|---|
| Show `Suspect` as yellow rather than hiding it | `confirmed` in the 2026-07-21 contract discussion | Architecture, serializer, tests, UI inventory, and adapters must converge. |
| Device availability has exactly `available`, `unopenable`, `not_found`; unrelated states are omitted | `confirmed` | UI inventory and mappings must add `unopenable`; pool ownership remains a separate axis. |
| Resolution requires explicit `succeeded` or `failed` | `confirmed` | API schema and service must perform a real terminal transition while retaining audit metadata. |
| Template flow uses one shared backend non-mutating planner | `confirmed` | CLI-specific assignment logic should move behind or call the planner; this is planning, not template validation. |
| Exact planner response fields and deterministic tie-breaking | `unresolved` | Must be defined before its implementation packet is executable. |
| Whether historical raw reports must expose previously hidden suspect values | `unresolved` | Could change migration/backfill and compatibility scope; live behavior can be changed independently if history remains raw in persisted events. |

## 7. Gap register

| ID | Gap | Type | Evidence | Impact | Confidence | Required proof | Suggested owner |
|---|---|---|---|---|---|---|---|
| C-01 | Backend status serialization rewrites `suspect` to `healthy` despite the newer visible-Suspect decision. | specification + implementation + integration | `app/services/session_status.py:94-109`; `tests/test_session_status_api.py:87-92`; architecture lines 1191 and 1509 | Operators cannot see the confirmation window and the frontend cannot reconstruct it. | high — code and regression test explicitly enforce the old rule | API test preserving suspect plus browser/component proof of yellow rendering | backend status owner + frontend UI owner |
| C-02 | UI inventory and frontend availability mappings omit `unopenable`. | documentation drift + integration | UI inventory lines 756-762 and 1282-1287; backend schemas lines 560-581; architecture lines 692-705 | A present but inaccessible device is indistinguishable or omitted. | high — checked-in contracts directly disagree | adapter/component tests for all three states and a device-pool API fixture | frontend contract owner |
| C-03 | Operation resolution accepts only `resolved_by` and `resolution_note`; it does not accept or apply an outcome. | state ownership + implementation | `ResolveOperationSchema`; operations route; `resolve_uncertain_operation`; architecture CLI line 1164 | Operation can be marked resolved while remaining `uncertain`, producing ambiguous UX and state semantics. | high — request and service signatures are explicit | atomic transition tests for both outcomes, invalid outcomes, retry/idempotency, and conflict release | backend operations owner |
| C-04 | The shared session-template assignment planner endpoint and service do not exist. | specification + implementation + integration | session-template API exposes only CRUD; CLI contains template resolution/prompt logic | UI cannot share the CLI's assignment behavior; logic may diverge. | high — route search and API module show no planner path | typed request/response contract, no-write assertions, assignment and unresolved-requirement tests, CLI/UI parity test | backend template/device owner |
| C-05 | Three reported provenance test failures have no captured node IDs, current traceback, or assigned disposition. | test coverage + repository hygiene | reported result: 9 passed, 3 failed; references include `source_template_id` and `.toml` suffix drift; rerun blocked in this environment | Contract work may be built on stale fixtures or a real provenance regression. | medium — failure count was reported, but current execution was not reproduced | rerun exact command, capture node IDs/tracebacks, classify fixture drift vs production defect | backend test/provenance owner |

## 8. Contradictory and orphaned findings

- **Contradiction:** the architecture plan says suspect streams render healthy until confirmed, while the newer product decision requires visible yellow `Suspect`. Disposition: requires a contract-change packet; do not patch only the Vue badge.
- **Contradiction:** the UI inventory says the backend resolution call requires an outcome, but the backend schema does not accept one. Disposition: requires a backend state-transition packet followed by frontend adaptation.
- **Stale documentation:** the UI inventory describes only `available` and `not_found`; the backend architecture and implementation use three states. Disposition: documentation/frontend correction.
- **Orphaned design:** the shared template planner exists only as a conversation decision. Disposition: record a typed API contract before implementation.
- **Orphaned failures:** the three provenance failures lack a checked-in owner and current traceback. Disposition: reproduce and classify before folding them into any feature packet.

## 9. Packet-readiness decision

**Decision: `not_ready_for_packetization` as a combined frontend/backend merge.**

Missing discovery work:

1. Promote the visible-Suspect decision into the authoritative architecture and decide compatibility for historical status responses.
2. Define the operation resolution outcome field, transition/idempotency semantics, and lock-release behavior.
3. Define the planner request/response schema, assignment tie-breaker, and explicit no-write guarantees.
4. Reproduce and classify the three device provenance failures with exact node IDs and tracebacks.
5. Ensure relevant tests and this register are visible to version control.

Once these items are resolved, each behavior below can be packetized independently.

## 10. Candidate packet boundaries

1. **Health contract convergence:** update architecture/UI inventory, stop hiding suspect, update API tests, and verify yellow rendering.
2. **Availability contract convergence:** add `unopenable` to UI inventory/adapters/badges and verify all three states without changing pool ownership status.
3. **Operation outcome resolution:** extend schema, perform atomic terminal transition, preserve audit fields, update CLI/UI, and prove conflict release/idempotency.
4. **Template planner contract and service:** specify and add the non-mutating endpoint, then route CLI and UI through it.
5. **Device provenance test repair:** separately classify and repair fixture/production drift; do not bundle it with planner or availability behavior.

## 11. Remaining unknowns and cheapest resolution

| Unknown | Cheapest useful resolution |
|---|---|
| Does persisted event history retain raw `suspect` even though the status view hides it? | Seed one suspect report, inspect the stored event payload and status response side by side. |
| What exactly releases an uncertain-operation conflict after outcome resolution? | Add one service/API test that resolves to each outcome and immediately attempts the previously blocked command. |
| How should the planner choose among several equivalent free devices? | Confirm a deterministic ordering rule (for example explicit template preference, then stable config ID) and freeze it in a contract fixture. |
| Which planner failures are warnings versus blockers? | Review one representative template against free, claimed, unopenable, not-found, and unconfigured pool rows and classify each expected result. |
| Are the three provenance failures fixture drift or defects? | Run the original combined command in the backend environment and save the full pytest node IDs and tracebacks. |

## Evidence index

- `../frontend/guarded-experiment-dashboard-ui-inventory.md`: health at 579 and 1271; availability at 756-762 and 1282-1287; operation resolution form at 1099-1114.
- `docs/backend-control-plane-architecture-plan.md`: health at 84-91, 1191, and 1509; availability at 692-705; operation CLI contract at 1164.
- `app/services/session_status.py`: suspect rewrite at 94-109.
- `app/api/schemas.py`: resolution request at 169-171; availability schemas at 560-581.
- `app/api/operations.py` and `app/services/operations.py`: current resolution path.
- `app/api/session_templates.py`: current CRUD-only session-template surface.
- `tests/test_session_status_api.py`: old suspect-hidden regression at 87-92.
- `tests/test_operation_resolution_api.py`: current audit-only resolution coverage.

