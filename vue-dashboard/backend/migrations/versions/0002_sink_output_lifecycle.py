"""Persist sink output lifecycle: logical output vs physical component.

Extends ``output_files`` so one logical sink output can own several linked
physical components with explicit acquisition, artifact/finalization, delivery,
and loss state; and extends ``recovery_gaps`` with a versioned boundary payload
so boundaries no longer overload the offset-only segment-id strings.

Existing rows are preserved: every legacy ``output_files`` row becomes the sole
component of its own logical output (``logical_sink_id = output_id``,
``segment_index = 0``) and its acquisition state is derived from ``status``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- output_files: add lifecycle columns (nullable / server-defaulted) ---
    with op.batch_alter_table("output_files", schema=None) as batch_op:
        batch_op.add_column(sa.Column("logical_sink_id", sa.String(36), nullable=True))
        batch_op.add_column(
            sa.Column("segment_index", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("previous_output_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("final_output_id", sa.String(36), nullable=True))
        batch_op.add_column(
            sa.Column(
                "acquisition_state",
                sa.String(16),
                nullable=False,
                server_default="open",
            )
        )
        batch_op.add_column(
            sa.Column(
                "artifact_state",
                sa.String(16),
                nullable=False,
                server_default="not_required",
            )
        )
        batch_op.add_column(sa.Column("termination_reason", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("delivery_state", sa.String(16), nullable=True))
        batch_op.add_column(
            sa.Column("byte_loss", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("sample_loss", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("finalization_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("finalizer_fence_token", sa.BigInteger(), nullable=True))
        batch_op.add_column(
            sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True)
        )

    # --- backfill deterministic defaults for existing rows ---
    # Each legacy output becomes the sole component of its own logical output.
    op.execute(
        "UPDATE output_files SET logical_sink_id = output_id "
        "WHERE logical_sink_id IS NULL"
    )
    # A closed physical file corresponds to a completed acquisition.
    op.execute(
        "UPDATE output_files SET acquisition_state = 'complete' WHERE status = 'closed'"
    )

    # --- output_files: enforce identity now that logical_sink_id is populated ---
    with op.batch_alter_table("output_files", schema=None) as batch_op:
        batch_op.alter_column(
            "logical_sink_id", existing_type=sa.String(36), nullable=False
        )
        batch_op.create_index(
            "ix_output_files_logical_sink_id", ["logical_sink_id"], unique=False
        )
        batch_op.create_unique_constraint(
            "uq_output_files_logical_segment", ["logical_sink_id", "segment_index"]
        )
        batch_op.create_unique_constraint(
            "uq_output_files_logical_path", ["logical_sink_id", "path"]
        )
        batch_op.create_check_constraint(
            "ck_output_files_no_self_predecessor",
            "previous_output_id IS NULL OR previous_output_id <> output_id",
        )

    # Server defaults were only needed to backfill existing rows; the ORM supplies
    # values for new rows, so drop them to keep the model as the single source.
    with op.batch_alter_table("output_files", schema=None) as batch_op:
        batch_op.alter_column("segment_index", server_default=None)
        batch_op.alter_column("acquisition_state", server_default=None)
        batch_op.alter_column("artifact_state", server_default=None)
        batch_op.alter_column("byte_loss", server_default=None)
        batch_op.alter_column("sample_loss", server_default=None)

    # --- recovery_gaps: versioned boundary payload alongside legacy offsets ---
    with op.batch_alter_table("recovery_gaps", schema=None) as batch_op:
        batch_op.add_column(sa.Column("boundary_kind", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("boundary_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("output_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("previous_output_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("next_output_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("pre_offset", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("post_offset", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("boundary_payload", sa.JSON(), nullable=True))
        batch_op.create_index("ix_recovery_gaps_boundary_kind", ["boundary_kind"])
        batch_op.create_index("ix_recovery_gaps_output_id", ["output_id"])


def downgrade() -> None:
    with op.batch_alter_table("recovery_gaps", schema=None) as batch_op:
        batch_op.drop_index("ix_recovery_gaps_output_id")
        batch_op.drop_index("ix_recovery_gaps_boundary_kind")
        batch_op.drop_column("boundary_payload")
        batch_op.drop_column("post_offset")
        batch_op.drop_column("pre_offset")
        batch_op.drop_column("next_output_id")
        batch_op.drop_column("previous_output_id")
        batch_op.drop_column("output_id")
        batch_op.drop_column("boundary_version")
        batch_op.drop_column("boundary_kind")

    with op.batch_alter_table("output_files", schema=None) as batch_op:
        batch_op.drop_constraint("ck_output_files_no_self_predecessor", type_="check")
        batch_op.drop_constraint("uq_output_files_logical_path", type_="unique")
        batch_op.drop_constraint("uq_output_files_logical_segment", type_="unique")
        batch_op.drop_index("ix_output_files_logical_sink_id")
        batch_op.drop_column("finalized_at")
        batch_op.drop_column("finalizer_fence_token")
        batch_op.drop_column("finalization_id")
        batch_op.drop_column("sample_loss")
        batch_op.drop_column("byte_loss")
        batch_op.drop_column("delivery_state")
        batch_op.drop_column("termination_reason")
        batch_op.drop_column("artifact_state")
        batch_op.drop_column("acquisition_state")
        batch_op.drop_column("final_output_id")
        batch_op.drop_column("previous_output_id")
        batch_op.drop_column("segment_index")
        batch_op.drop_column("logical_sink_id")
