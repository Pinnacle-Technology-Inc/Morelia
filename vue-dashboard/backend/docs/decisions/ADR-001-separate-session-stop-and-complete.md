# ADR-001: Separate restartable Stop from terminal Complete

## Status

Accepted as the target lifecycle contract. Not yet implemented.

## Date

2026-07-22

## Context

The current backend treats a successful Stop as the session completion boundary. `services.sessions.stop` and `stop_managed` transition an active session through `ending` to `completed`, finalize the current outputs, release runtime/device resources, and leave no lifecycle state from which the same session can be started again.

The product needs two distinct operator intents:

1. Temporarily conclude the current dataflow while preserving the session configuration and allowing another acquisition under the same session later.
2. Declare the whole session finished, move it into archive/history, and prevent future operational changes.

Conflating these intents makes an ordinary Stop irreversible and makes the existing Complete control impossible to define honestly.

## Decision

Stop and Complete are separate guarded lifecycle commands.

### Stop

- Stop concludes the **current dataflow/acquisition**, not the session.
- It performs the safe shutdown and output-finalization responsibilities currently associated with Stop.
- It releases runtime ownership, device claims, and other resources belonging to the concluded dataflow.
- The session enters a restartable post-stop lifecycle state.
- A later Start is allowed and creates new runtime/dataflow, acquisition, operation, and output identities. It must not append to or reopen the concluded acquisition as though it never stopped.
- Configuration and history remain associated with the session.

### Complete

- Complete is the explicit terminal action for the **session**.
- It moves the session into the Completed/archive state.
- A Completed session remains queryable as history but is operationally read-only.
- Start, Stop, Recover, and configuration mutations are forbidden after completion. Deletion behavior remains governed by the existing rule that started historical sessions are not deleted.
- Completion must be represented by its own guarded operation/API path rather than by relabeling Stop.

## Current compatibility state

Until the lifecycle migration is implemented, the current backend behavior remains authoritative at runtime: Stop still produces `completed`. Frontend copy and controls must not claim that the current Stop is restartable.

The migration must change the domain enum/state machine, persistence and serialization, services, guarded-operation contract, API schemas/routes, frontend filters/actions, reconciliation logic, and tests as one coordinated behavior change.

## Alternatives considered

### Keep Stop equivalent to Complete

Rejected for the target design because users must be able to conclude one dataflow and later start another under the same session.

### Keep Stop terminal and add a separate Pause command

Rejected because the intended action is a real dataflow conclusion with output finalization and resource release, not suspension of the same running acquisition.

### Treat archival as an independent flag unrelated to Completed

Not selected for the target contract. The accepted product meaning is that Complete moves the session to archive and it is not operated again. A separate storage/indexing flag may still exist internally, but it must not create another operator-visible mutable state after Completed.

## Consequences

- The current `draft → scheduled → starting → active → ending → completed` lifecycle is insufficient; it needs a restartable post-stop state.
- Sessions may own multiple historical dataflow/acquisition generations over time, while only one current owned dataflow may run at once.
- Output, runtime, command, and recovery identities must remain generation-specific.
- List filters must distinguish restartable stopped sessions from terminal completed/archived sessions.
- Stop and Complete need distinct confirmation copy, permissions, operation records, observability, and negative tests.
- Reconciliation must never turn an uncertain Stop into terminal Completed unless a separate Complete command was durably requested and proven.

## Unresolved implementation decisions

1. Name and exact wire value of the restartable post-stop lifecycle state.
2. Whether Complete is allowed only after Stop, or may atomically stop an active dataflow and then complete the session.
3. Whether any non-operational metadata actions, such as adding notes, remain legal on archived history.

These choices refine the implementation but do not reopen the accepted distinction between restartable Stop and terminal Complete.
