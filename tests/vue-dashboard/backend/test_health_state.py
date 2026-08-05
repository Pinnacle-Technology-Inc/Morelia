"""Stage 7.5 — the health-state classifier (pure, total, table-tested)."""

import itertools

from app.domain.enums import (
    HealthState,
    HealthStatus,
    LinkStatus,
    OperationState,
    StreamStatus,
)
from app.runtime_child.driver import DeviceReport, RuntimePhase
from app.services.health_state import aggregate_streams, derive, to_disposition


def _device(stream_status: StreamStatus) -> DeviceReport:
    return DeviceReport(device_id="dev-1", stream_status=stream_status)


# -- aggregate_streams: worst-of rollup ---------------------------------------


def test_empty_device_set_is_vacuously_healthy():
    assert aggregate_streams([]) is StreamStatus.HEALTHY


def test_all_healthy_devices_aggregate_to_healthy():
    devices = [_device(StreamStatus.HEALTHY) for _ in range(3)]
    assert aggregate_streams(devices) is StreamStatus.HEALTHY


def test_a_single_unhealthy_device_is_not_hidden_behind_healthy_peers():
    devices = [
        _device(StreamStatus.HEALTHY),
        _device(StreamStatus.UNHEALTHY),
        _device(StreamStatus.HEALTHY),
    ]
    assert aggregate_streams(devices) is StreamStatus.UNHEALTHY


def test_suspect_wins_over_healthy_but_loses_to_unhealthy():
    assert (
        aggregate_streams([_device(StreamStatus.HEALTHY), _device(StreamStatus.SUSPECT)])
        is StreamStatus.SUSPECT
    )
    assert (
        aggregate_streams([_device(StreamStatus.SUSPECT), _device(StreamStatus.UNHEALTHY)])
        is StreamStatus.UNHEALTHY
    )


# -- derive: one targeted case per precedence rung ----------------------------


def test_unreachable_link_outranks_everything_including_a_healthy_report():
    # Even a running, healthy stream reads unreachable — the last report is stale.
    assert (
        derive(
            link_status=LinkStatus.UNREACHABLE,
            stream_agg=StreamStatus.HEALTHY,
            phase=RuntimePhase.RUNNING,
            op_state=None,
            recovery_active=True,
        )
        is HealthState.UNREACHABLE
    )


def test_failed_operation_is_authoritative_failed():
    assert (
        derive(
            link_status=LinkStatus.REACHABLE,
            stream_agg=StreamStatus.HEALTHY,
            phase=RuntimePhase.RUNNING,
            op_state=OperationState.FAILED,
            recovery_active=False,
        )
        is HealthState.FAILED
    )


def test_stopped_phase_is_a_clean_halt_not_a_fault():
    for phase in (RuntimePhase.STOPPED, RuntimePhase.CLOSED):
        assert (
            derive(
                link_status=LinkStatus.REACHABLE,
                stream_agg=StreamStatus.HEALTHY,
                phase=phase,
                op_state=None,
                recovery_active=False,
            )
            is HealthState.STOPPED
        )


def test_active_recovery_forces_recovering_regardless_of_stream():
    assert (
        derive(
            link_status=LinkStatus.REACHABLE,
            stream_agg=StreamStatus.UNHEALTHY,
            phase=RuntimePhase.RUNNING,
            op_state=None,
            recovery_active=True,
        )
        is HealthState.RECOVERING
    )


def test_confirmed_unhealthy_stream_without_recovery_is_failed():
    assert (
        derive(
            link_status=LinkStatus.REACHABLE,
            stream_agg=StreamStatus.UNHEALTHY,
            phase=RuntimePhase.RUNNING,
            op_state=None,
            recovery_active=False,
        )
        is HealthState.FAILED
    )


def test_delayed_link_ranks_below_real_content_faults():
    assert (
        derive(
            link_status=LinkStatus.DELAYED,
            stream_agg=StreamStatus.HEALTHY,
            phase=RuntimePhase.RUNNING,
            op_state=None,
            recovery_active=False,
        )
        is HealthState.DELAYED
    )


def test_reachable_running_healthy_is_healthy():
    assert (
        derive(
            link_status=LinkStatus.REACHABLE,
            stream_agg=StreamStatus.HEALTHY,
            phase=RuntimePhase.RUNNING,
            op_state=OperationState.SUCCEEDED,
            recovery_active=False,
        )
        is HealthState.HEALTHY
    )


def test_in_window_suspect_is_not_operator_facing_and_reads_healthy():
    assert (
        derive(
            link_status=LinkStatus.REACHABLE,
            stream_agg=StreamStatus.SUSPECT,
            phase=RuntimePhase.RUNNING,
            op_state=None,
            recovery_active=False,
        )
        is HealthState.HEALTHY
    )


def test_preflight_is_unknown_not_a_misleading_healthy():
    for phase in (RuntimePhase.IDLE, RuntimePhase.PREFLIGHT):
        assert (
            derive(
                link_status=LinkStatus.REACHABLE,
                stream_agg=StreamStatus.HEALTHY,
                phase=phase,
                op_state=None,
                recovery_active=False,
            )
            is HealthState.UNKNOWN
        )


def test_uncertain_operation_does_not_make_the_badge_flap():
    # An uncertain op is surfaced separately; a running healthy stream stays healthy.
    assert (
        derive(
            link_status=LinkStatus.REACHABLE,
            stream_agg=StreamStatus.HEALTHY,
            phase=RuntimePhase.RUNNING,
            op_state=OperationState.UNCERTAIN,
            recovery_active=False,
        )
        is HealthState.HEALTHY
    )


# -- totality: every combination returns a defined state, never raises --------


def test_derive_is_total_over_every_input_combination():
    op_states: list[OperationState | None] = [None, *list(OperationState)]
    reachable_states = set()
    for link_status, stream_agg, phase, op_state, recovery_active in itertools.product(
        LinkStatus, StreamStatus, RuntimePhase, op_states, (True, False)
    ):
        result = derive(
            link_status=link_status,
            stream_agg=stream_agg,
            phase=phase,
            op_state=op_state,
            recovery_active=recovery_active,
        )
        assert isinstance(result, HealthState)
        reachable_states.add(result)

    # All seven operator-facing states must be reachable from the input space.
    assert reachable_states == set(HealthState)


# -- to_disposition: the lossy projection onto the dashboard buckets ----------


def test_every_health_state_projects_to_a_defined_disposition():
    # Guards the dict: a future HealthState added without a mapping fails here.
    for state in HealthState:
        assert isinstance(to_disposition(state), HealthStatus)


def test_nominal_and_clean_stop_both_read_as_healthy_disposition():
    assert to_disposition(HealthState.HEALTHY) is HealthStatus.HEALTHY
    assert to_disposition(HealthState.STOPPED) is HealthStatus.HEALTHY


def test_recovering_is_preserved_through_the_projection():
    assert to_disposition(HealthState.RECOVERING) is HealthStatus.RECOVERING


def test_degraded_states_fold_to_needs_action():
    for state in (HealthState.DELAYED, HealthState.UNREACHABLE, HealthState.FAILED):
        assert to_disposition(state) is HealthStatus.NEEDS_ACTION


def test_unknown_is_preserved_through_the_projection():
    assert to_disposition(HealthState.UNKNOWN) is HealthStatus.UNKNOWN
