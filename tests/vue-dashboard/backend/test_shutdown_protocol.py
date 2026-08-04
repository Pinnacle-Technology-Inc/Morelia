from Morelia.shutdown import (
    REQUIRED_SHUTDOWN_PHASES,
    ShutdownAction,
    ShutdownPhase,
    ShutdownProtocol,
    ShutdownOutcome,
)


def action(protocol, phase, action_name, *, outcome=ShutdownOutcome.ACKNOWLEDGED, **fields):
    return protocol.apply(
        ShutdownAction(
            shutdown_id=protocol.shutdown_id,
            stream_index=protocol.stream_index,
            actor="dataflow_worker",
            actor_pid=42,
            phase=phase,
            action=action_name,
            outcome=outcome,
            emitted_at_ns=fields.pop("emitted_at_ns", 1_000),
            **fields,
        )
    )


def clean_protocol():
    protocol = ShutdownProtocol("shutdown-1", 0, started_at_ns=1_000)
    protocol.request()
    action(protocol, ShutdownPhase.STOP_OBSERVED, "stop_event_observed")
    action(protocol, ShutdownPhase.SOURCE_STOPPED, "source_port_closed")
    action(protocol, ShutdownPhase.SINKS_FINALIZING, "sink_close_started")
    action(protocol, ShutdownPhase.SINKS_FINALIZED, "all_sinks_closed")
    action(protocol, ShutdownPhase.WORKER_EXITING, "worker_exit_started")
    action(
        protocol,
        ShutdownPhase.WORKER_EXITED,
        "worker_exit_observed",
        outcome=ShutdownOutcome.COMPLETED,
        worker_exitcode=0,
    )
    return protocol


def test_clean_sequence_reaches_complete_only_after_zero_exit():
    protocol = clean_protocol()

    result = protocol.complete()

    assert result.ok is True
    assert result.phase is ShutdownPhase.COMPLETE
    assert [record.phase for record in result.transcript] == [
        ShutdownPhase.REQUESTED,
        *REQUIRED_SHUTDOWN_PHASES,
        ShutdownPhase.COMPLETE,
    ]
    assert [record.action_seq for record in result.transcript] == list(range(1, 9))
    assert all(record.elapsed_ms >= 0 for record in result.transcript)


def test_skipped_phase_fails_with_protocol_violation():
    protocol = ShutdownProtocol("shutdown-2", 0)
    protocol.request()

    result = action(protocol, ShutdownPhase.SINKS_FINALIZING, "sink_close_started")

    assert result.ok is False
    assert result.phase is ShutdownPhase.FAILED
    assert result.reason == "protocol_violation"
    assert any(record.phase is ShutdownPhase.PROTOCOL_VIOLATION for record in result.transcript)


def test_nonzero_worker_exit_fails_with_stable_reason():
    protocol = ShutdownProtocol("shutdown-1", 0)
    protocol.request()
    action(protocol, ShutdownPhase.STOP_OBSERVED, "stop_event_observed")
    action(protocol, ShutdownPhase.SOURCE_STOPPED, "source_port_closed")
    action(protocol, ShutdownPhase.SINKS_FINALIZING, "sink_close_started")
    action(protocol, ShutdownPhase.SINKS_FINALIZED, "all_sinks_closed")
    action(protocol, ShutdownPhase.WORKER_EXITING, "worker_exit_started")

    result = protocol.apply(
        ShutdownAction(
            shutdown_id=protocol.shutdown_id,
            stream_index=protocol.stream_index,
            actor="monitor",
            actor_pid=None,
            phase=ShutdownPhase.WORKER_EXITED,
            action="worker_exit_observed",
            outcome=ShutdownOutcome.COMPLETED,
            emitted_at_ns=2_000,
            worker_exitcode=3,
        )
    )

    assert result.ok is False
    assert result.reason == "worker_exit_nonzero"


def test_deadline_and_forced_termination_fail_explicitly():
    protocol = ShutdownProtocol("shutdown-3", 0)
    protocol.request()
    protocol.deadline_expired()
    protocol.force_termination_requested()

    result = protocol.forced_termination(worker_exitcode=-15)

    assert result.ok is False
    assert result.phase is ShutdownPhase.FAILED
    assert result.forced_termination is True
    assert result.reason == "forced_termination"
    assert [record.phase for record in result.transcript][-4:] == [
        ShutdownPhase.DEADLINE_EXPIRED,
        ShutdownPhase.FORCE_TERMINATION_REQUESTED,
        ShutdownPhase.FORCED_TERMINATION,
        ShutdownPhase.FAILED,
    ]


def test_duplicate_acknowledgement_is_visible_and_idempotent():
    protocol = ShutdownProtocol("shutdown-4", 0)
    protocol.request()
    action(protocol, ShutdownPhase.STOP_OBSERVED, "stop_event_observed")

    result = action(protocol, ShutdownPhase.STOP_OBSERVED, "stop_event_observed")

    assert result.ok is None
    assert result.phase is ShutdownPhase.STOP_OBSERVED
    assert result.transcript[-1].outcome is ShutdownOutcome.DUPLICATE


def test_transcript_overflow_fails_without_exceeding_bound():
    protocol = ShutdownProtocol("shutdown-5", 0, max_actions=3)
    protocol.request()
    action(protocol, ShutdownPhase.STOP_OBSERVED, "stop_event_observed")

    result = action(protocol, ShutdownPhase.SOURCE_STOPPED, "source_port_closed")

    assert result.ok is False
    assert result.reason == "transcript_overflow"
    assert len(result.transcript) == 3
    assert result.transcript[-1].action == "transcript_overflow"


def test_invalid_identity_is_rejected_without_mutating_transcript():
    protocol = ShutdownProtocol("shutdown-6", 0)
    protocol.request()
    before = protocol.snapshot()

    result = protocol.apply(
        ShutdownAction(
            shutdown_id="other",
            stream_index=0,
            actor="monitor",
            actor_pid=None,
            phase=ShutdownPhase.STOP_OBSERVED,
            action="stop_event_observed",
            outcome=ShutdownOutcome.ACKNOWLEDGED,
            emitted_at_ns=1_000,
        )
    )

    assert result.reason == "protocol_violation"
    assert len(result.transcript) > len(before.transcript)
