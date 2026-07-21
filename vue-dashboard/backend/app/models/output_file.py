from datetime import UTC, datetime

from app.database import db


class OutputFile(db.Model):
    """Metadata row for one physical output component of a logical sink output.

    A *logical sink output* is one operator-visible recording for one sink. It
    may own several *physical components* (this table's rows): CSV normally maps
    one logical output to one component, but an error-interrupted EDF/PVFS
    logical output can own multiple linked segments that a finalizer later
    merges into one published artifact.

    Identity model
    --------------
    - ``output_id``      -- unique id of this physical component.
    - ``logical_sink_id``-- stable id shared by every component of one logical
      output; the allocator packet owns minting it.
    - ``segment_index``  -- monotonic ordinal of this component within the
      logical output (0 for the first / only component).
    - ``previous_output_id`` -- ``output_id`` of the predecessor component that
      this one continues after a recovery boundary (NULL for the first).
    - ``final_output_id`` -- ``output_id`` of the published merged artifact once
      finalization commits (NULL until then).

    Lifecycle model (source health is tracked elsewhere and never overloaded here)
    ------------------------------------------------------------------------------
    - ``acquisition_state`` -- ``open`` -> ``interrupted`` -> ``complete``. A user
      stop transitions it to ``complete`` once all writers close.
    - ``artifact_state``    -- ``not_required``, ``merge_pending``, ``merging``,
      ``merged``, ``merge_failed``. Together ``merging``/``merged`` express the
      packet's *finalizing*/*finalized* notions.
    - ``termination_reason``-- why writing to this component ended: ``clean``,
      ``recovery``, ``watchdog_crash``, ``forced``, or ``writer_failure``.
    - ``delivery_state``    -- for service sinks: delivery/replay disposition
      (e.g. ``pending``, ``delivering``, ``delivered``, ``degraded``, ``failed``).
    - ``byte_loss`` / ``sample_loss`` -- counters for evidence of lost output; a
      non-zero value is the durable *loss*/*degraded* signal.

    Finalizer fencing
    -----------------
    - ``finalization_id``       -- id of the merge attempt that owns this row.
    - ``finalizer_fence_token`` -- monotonic token fencing stale/concurrent merge
      attempts so a superseded finalizer cannot publish or delete evidence.
    - ``finalized_at``          -- when finalization committed.

    ``status``/``byte_offset``/``row_offset`` retain their 4.3 meaning so the
    recovery boundary path keeps working unchanged.
    """

    __tablename__ = "output_files"

    id          = db.Column(db.Integer, primary_key=True)
    output_id   = db.Column(db.String(36), nullable=False, unique=True, index=True)
    logical_sink_id = db.Column(db.String(36), nullable=False, index=True)
    segment_index   = db.Column(db.Integer, nullable=False, default=0)
    previous_output_id = db.Column(db.String(36), nullable=True)
    final_output_id    = db.Column(db.String(36), nullable=True)
    session_id  = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=True, index=True)
    dataflow_id = db.Column(db.String(255), nullable=False, index=True)
    device_id   = db.Column(db.String(255), nullable=True)
    sink_id     = db.Column(db.String(255), nullable=True)
    sink_type   = db.Column(db.String(64), nullable=False)
    path        = db.Column(db.String(1024), nullable=False, unique=True, index=True)
    schema_hash = db.Column(db.String(64), nullable=True)
    status      = db.Column(db.String(16), nullable=False, default="open")
    acquisition_state  = db.Column(db.String(16), nullable=False, default="open")
    artifact_state     = db.Column(db.String(16), nullable=False, default="not_required")
    termination_reason = db.Column(db.String(32), nullable=True)
    delivery_state     = db.Column(db.String(16), nullable=True)
    byte_offset = db.Column(db.Integer, nullable=False, default=0)
    row_offset  = db.Column(db.Integer, nullable=False, default=0)
    byte_loss   = db.Column(db.Integer, nullable=False, default=0)
    sample_loss = db.Column(db.Integer, nullable=False, default=0)
    finalization_id       = db.Column(db.String(64), nullable=True)
    finalizer_fence_token = db.Column(db.BigInteger, nullable=True)
    finalized_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at  = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (
        # A component ordinal is unique within one logical sink output.
        db.UniqueConstraint(
            "logical_sink_id", "segment_index", name="uq_output_files_logical_segment"
        ),
        # A physical path is unique within one logical sink output.
        db.UniqueConstraint(
            "logical_sink_id", "path", name="uq_output_files_logical_path"
        ),
        # A component can never be its own predecessor.
        db.CheckConstraint(
            "previous_output_id IS NULL OR previous_output_id <> output_id",
            name="ck_output_files_no_self_predecessor",
        ),
    )
