"""Record one recovery boundary as a versioned RecoveryGap row.

Callers (the runtime host's Morelia driver, and the whole-watchdog respawn
path) call :func:`record_boundary` right after reconstructing a sink. Instead of
overloading ``previous_segment_id`` / ``next_segment_id`` with undocumented
offset-only JSON, boundaries are now described through the typed, versioned
columns added in packet 10:

- ``boundary_kind`` selects the payload shape (``same_file`` / ``segmented`` /
  ``remote`` / ``plot``);
- ``output_id`` / ``previous_output_id`` / ``next_output_id`` carry component
  identity;
- ``pre_offset`` / ``post_offset`` carry structured byte+row positions;
- ``boundary_payload`` carries any remaining boundary-kind-specific metadata
  (e.g. sample/byte counts, the partial-final-row decision).

Recording is idempotent per ``recovery_id``: one recovery episode yields at most
one gap, so a repeated post-recovery report cannot write the boundary twice.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.domain.enums import GapConfidence
from app.models.recovery_gap import RecoveryGap
from app.repositories.recovery_gaps import RecoveryGapRepository

_repo = RecoveryGapRepository()

# Versioned boundary payloads carry this schema version so downstream readers
# can evolve the shape without guessing.
BOUNDARY_VERSION = 1

# Recognized boundary kinds (see RecoveryGap docstring / audit section 7).
SAME_FILE = "same_file"
SEGMENTED = "segmented"
REMOTE = "remote"
PLOT = "plot"


def record_boundary(
    *,
    session_id: int,
    dataflow_id: str,
    reason: str,
    boundary_kind: str = SAME_FILE,
    output_id: str | None = None,
    previous_output_id: str | None = None,
    next_output_id: str | None = None,
    pre_offset: Mapping[str, Any] | None = None,
    post_offset: Mapping[str, Any] | None = None,
    boundary_payload: Mapping[str, Any] | None = None,
    gap_start: Mapping[str, Any] | None = None,
    gap_end: Mapping[str, Any] | None = None,
    confidence: GapConfidence = GapConfidence.UNCERTAIN,
    partial_final_row: bool = False,
    incident_id: str | None = None,
    device_id: str | None = None,
    sink_id: str | None = None,
    recovery_id: str | None = None,
    policy: str | None = None,
    boundary_version: int = BOUNDARY_VERSION,
) -> RecoveryGap:
    """Save a recording interruption so missing or incomplete data can be located later.
    The returned ``RecoveryGap`` database record identifies the affected device
    and output, with any known times and file positions before and after the gap.

    For recording that resumes in the same file, supply ``output_id``. For
    recording that resumes in a new file, supply ``previous_output_id`` and
    ``next_output_id``. Set ``boundary_kind`` to match. File positions go in
    ``pre_offset`` and ``post_offset`` as ``{"byte": .., "row": ..}`` mappings;
    the older segment ID fields stay NULL. ``boundary_payload`` holds extra
    details such as sample counts, and ``boundary_version`` identifies the
    format of those details.

    Set ``partial_final_row`` if the last row before the gap may be incomplete.
    This records the condition without changing the file. Confidence defaults
    to UNCERTAIN. If ``recovery_id`` already has a gap, return that record unchanged.
    """
    # Recovery reports can arrive more than once for the same interruption.
    # Reuse the saved gap so the recording history does not show duplicate gaps.
    if recovery_id is not None:
        existing = _repo.find_by_recovery_id(recovery_id)
        if existing is not None:
            return existing

    payload: dict[str, Any] = dict(boundary_payload) if boundary_payload else {}
    if partial_final_row:
        payload["partial_final_row"] = True

    return _repo.create(
        session_id=session_id,
        dataflow_id=dataflow_id,
        reason=reason,
        incident_id=incident_id,
        device_id=device_id,
        sink_id=sink_id,
        recovery_id=recovery_id,
        policy=policy,
        confidence=confidence,
        boundary_kind=boundary_kind,
        boundary_version=boundary_version,
        output_id=output_id,
        previous_output_id=previous_output_id,
        next_output_id=next_output_id,
        pre_offset=pre_offset,
        post_offset=post_offset,
        boundary_payload=payload if payload else None,
        gap_start=gap_start,
        gap_end=gap_end,
    )


def record_same_file_boundary(
    *,
    output_id: str,
    pre_offset: Mapping[str, Any],
    post_offset: Mapping[str, Any],
    **kwargs: Any,
) -> RecoveryGap:
    """Record a same-file resume boundary (one component, pre/post offsets)."""
    return record_boundary(
        boundary_kind=SAME_FILE,
        output_id=output_id,
        pre_offset=pre_offset,
        post_offset=post_offset,
        **kwargs,
    )


def record_segmented_boundary(
    *,
    previous_output_id: str,
    next_output_id: str,
    **kwargs: Any,
) -> RecoveryGap:
    """Record a segmented boundary linking two physical components by output id.

    This is the boundary that pairs with
    :func:`app.output.managed_file.allocate_continuation`: ``previous_output_id``
    is the closed predecessor and ``next_output_id`` the freshly allocated
    continuation.
    """
    return record_boundary(
        boundary_kind=SEGMENTED,
        previous_output_id=previous_output_id,
        next_output_id=next_output_id,
        **kwargs,
    )
