# Packet 00A — Capture repository provenance

Status: ready  
Size: XS  
Depends on: none

## Purpose

Create a reproducible starting record for the dirty backend and Morelia worktrees before implementation begins.

## Prior state

The audit observed untracked backend documentation/tests and a dirty Morelia checkout on branch `test-window-object-changes` near commit `80a1662`. Commit-only descriptions would omit behavior that later packets depend on.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Repository health”, gap SINK-16, and the orphaned Morelia finding.
- `pyproject.toml` — backend dependency declarations.
- `app/control/supervisor.py` — how the Morelia runtime source is selected/loaded.

Read-only evidence commands:

```powershell
git status --short
git rev-parse HEAD
git remote -v
git -C C:\Users\ahoang\Morelia status --short
git -C C:\Users\ahoang\Morelia rev-parse HEAD
git -C C:\Users\ahoang\Morelia remote -v
```

## Exact edit set

- `docs/sinks/repository-provenance.md`

## Scope boundaries

Do not clean, reset, stage, commit, switch, or overwrite either worktree. Do not claim an immutable Morelia revision represents local modifications.

## Contract / invariant

The provenance record identifies both base commits, branches/remotes, relevant dirty paths, intended packet-owned paths, and how the exact Morelia runtime used for tests will be reproduced or archived.

## Acceptance criteria

1. The record distinguishes pre-existing user changes from future packet changes in both repositories.
2. Morelia runtime evidence includes the base commit plus a reviewable patch/hash or a later immutable commit after packet 23.
3. Intended documentation/tests are selectively tracked during implementation; unrelated local artifacts are never swept into a change.

## Verification

Re-run the read-only evidence commands and confirm the record matches their output. Then verify:

```powershell
git diff -- docs/sinks/repository-provenance.md
```

## Failure handling

If provenance cannot be made reproducible without choosing what to retain from a dirty worktree, stop before code edits and ask the repository owner to classify those paths.

## Handoff note

Give packet 00 the recorded backend baseline and packet 23 the Morelia base commit, pre-existing dirty-path list, and required final patch/commit evidence.
