"""Request/response schemas (marshmallow).

Field NAMES here are part of the contract (acceptance criterion: "stable field
names"), so treat a rename like a breaking change. Enum fields pull their legal
values from app.domain.enums via ``fields.Enum(..., by_value=True)`` — so the wire
values are exactly the controlled vocabulary defined once in that module.

Layering reminder: these schemas answer "is this a well-formed Draft?" — they do
NOT enforce start-time business rules (>=1 flow, writable destinations). Those
live in the route/service layer, checked when a session is actually started.
"""

from datetime import UTC, datetime

from marshmallow import Schema, ValidationError, fields, validate, validates_schema

from app.domain.enums import (
    DeviceClaimState,
    DeviceType,
    IncidentStatus,
    OperationScope,
    OperationState,
    PolicyMode,
    RuntimeOwnershipState,
    SessionStatus,
    SinkType,
    WatchdogProcessState,
)


class SinkSchema(Schema):
    """One output sink in a device flow's ordered ``sinks`` collection.

    Mirrors the canonical service contract (app.services.session_config): a
    stable ``sink_name`` (defaults to the sink type when omitted), a required
    ``sink_type`` from the controlled sink vocabulary, an optional
    ``sink_location`` permitted only for file-category sinks (csv/edf/pvfs),
    and a ``sink_parameters`` map that is always present ({} when the sink
    takes none). Secret *values* are rejected by the service layer; only
    non-secret values and secret *references* (e.g. Influx ``api_token_env``,
    an environment-variable NAME) are accepted.
    """

    sink_name = fields.String(load_default=None, validate=validate.Length(min=1))
    sink_type = fields.Enum(SinkType, by_value=True, required=True)
    sink_location = fields.String(load_default=None, validate=validate.Length(min=1))
    sink_parameters = fields.Dict(keys=fields.String(), values=fields.Raw(), load_default=dict)


class DeviceFlowSchema(Schema):
    """One device/source plus its non-empty ordered collection of sinks.

    Device identity is supplied either by ``device_config_id`` (an already
    configured device) or by ``device_template_path`` + ``hardware_id`` +
    ``port`` (instantiate a config from a device template). This is the
    documented wire contract; the create/template routes accept raw flow
    mappings (``fields.Raw``) and delegate canonicalization plus legacy
    flattened-sink normalization to the session-config service, so a single
    source of truth validates both request shapes.
    """

    nickname = fields.String(load_default=None)
    device_config_id = fields.Integer(load_default=None)
    device_template_path = fields.String(load_default=None)
    device_template_content_hash = fields.String(load_default=None)
    hardware_id = fields.String(load_default=None)
    port = fields.String(load_default=None)
    sinks = fields.List(
        fields.Nested(SinkSchema),
        required=True,
        validate=validate.Length(min=1, error="A device flow needs at least one sink."),
    )


class ScheduleSchema(Schema):
    """Manual or future-dated schedule. Demonstrates cross-field validation."""

    mode = fields.String(load_default="manual", validate=validate.OneOf(["manual", "daily"]))
    start_at = fields.DateTime(load_default=None)

    @validates_schema
    def check_start_at(self, data, **kwargs):
        # This is the "required-only-when" rule from decision C: a scheduled run
        # needs a future start_at; a manual one must not carry one at all.
        mode = data.get("mode", "manual")
        start_at = data.get("start_at")
        if mode == "manual":
            if start_at is not None:
                raise ValidationError(
                    "Must be omitted for a manual session.", field_name="start_at"
                )
            return
        if start_at is None:
            raise ValidationError("Required for a scheduled session.", field_name="start_at")
        # Treat a naive datetime as UTC so the comparison never raises.
        aware = start_at if start_at.tzinfo else start_at.replace(tzinfo=UTC)
        if aware <= datetime.now(UTC):
            raise ValidationError("Must be in the future.", field_name="start_at")


class CreateSessionSchema(Schema):
    """Input for creating a Draft. Everything is optional — a blank Draft is valid."""

    # name omitted -> None here, then auto-generated in the store (decision B).
    name = fields.String(load_default=None, validate=validate.Length(min=1, max=120))
    policy = fields.Enum(PolicyMode, by_value=True, load_default=PolicyMode.RECOMMEND)
    experiment_id = fields.String(load_default=None)
    schedule = fields.Nested(ScheduleSchema, load_default=None)
    device_flows = fields.List(fields.Raw(), load_default=list)


class SessionSchema(Schema):
    """How a stored session is represented on the wire (response shape)."""

    id = fields.String(dump_only=True)
    name = fields.String()
    status = fields.Enum(SessionStatus, by_value=True)
    policy = fields.Enum(PolicyMode, by_value=True)
    experiment_id = fields.String(allow_none=True)
    schedule = fields.Nested(ScheduleSchema, allow_none=True)
    device_flows = fields.List(fields.Raw())
    command_id = fields.String(allow_none=True)
    created_at = fields.DateTime(dump_only=True)


class FleetSessionRowSchema(Schema):
    """One row of the fleet overview (6f): lifecycle + live health + phase."""

    id = fields.Integer()
    name = fields.String()
    status = fields.Enum(SessionStatus, by_value=True)
    phase = fields.String(allow_none=True)
    health = fields.String(allow_none=True)


class FleetOverviewSchema(Schema):
    """Fleet-wide session overview (6f)."""

    running_count = fields.Integer()
    total_count = fields.Integer()
    sessions = fields.List(fields.Nested(FleetSessionRowSchema))


class LatestStreamEventDeviceSchema(Schema):
    device_id = fields.String(allow_none=True)
    # suspect is folded to healthy before this is dumped (suspect-hidden rule).
    stream_status = fields.String(allow_none=True)


class LatestStreamEventSchema(Schema):
    """The newest persisted runtime report surfaced in a status snapshot (6g)."""

    event_id = fields.Integer()
    sequence = fields.Integer()
    phase = fields.String(allow_none=True)
    comms = fields.String(allow_none=True)
    recovery_id = fields.String(allow_none=True)
    received_at = fields.DateTime(allow_none=True)
    devices = fields.List(fields.Nested(LatestStreamEventDeviceSchema))
    diagnostics = fields.Raw(allow_none=True)


class OperationListQuerySchema(Schema):
    state = fields.Enum(OperationState, by_value=True, load_default=None)
    session_id = fields.Integer(load_default=None, data_key="session")
    dataflow_id = fields.String(load_default=None, data_key="dataflow")


class ResolveOperationSchema(Schema):
    resolved_by = fields.String(required=True, validate=validate.Length(min=1, max=255))
    resolution_note = fields.String(required=True, validate=validate.Length(min=1, max=1024))


class OperationSchema(Schema):
    id = fields.Integer(dump_only=True)
    operation_id = fields.String(dump_only=True)
    request_key = fields.String()
    session_id = fields.Integer()
    dataflow_id = fields.String()
    scope = fields.Enum(OperationScope, by_value=True)
    target_device_id = fields.String(allow_none=True)
    command = fields.String()
    request_id = fields.String(allow_none=True)
    command_id = fields.String()
    watchdog_id = fields.String(allow_none=True)
    recovery_id = fields.String(allow_none=True)
    manifest_hash = fields.String(allow_none=True)
    runtime_id = fields.String(allow_none=True)
    state = fields.Enum(OperationState, by_value=True)
    queued_at = fields.DateTime(allow_none=True)
    claimed_at = fields.DateTime(allow_none=True)
    dispatched_at = fields.DateTime(allow_none=True)
    running_at = fields.DateTime(allow_none=True)
    verifying_at = fields.DateTime(allow_none=True)
    finished_at = fields.DateTime(allow_none=True)
    error_code = fields.String(allow_none=True)
    error_message = fields.String(allow_none=True)
    details = fields.Raw(allow_none=True)
    resolved_by = fields.String(allow_none=True)
    resolved_at = fields.DateTime(allow_none=True)
    resolution_note = fields.String(allow_none=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class RuntimeOwnershipSchema(Schema):
    id = fields.Integer(dump_only=True)
    runtime_id = fields.String()
    session_id = fields.Integer()
    dataflow_id = fields.String()
    manifest_hash = fields.String()
    pid = fields.Integer(allow_none=True)
    port = fields.Integer(allow_none=True)
    state = fields.Enum(RuntimeOwnershipState, by_value=True)
    started_at = fields.DateTime(dump_only=True)
    last_seen_at = fields.DateTime(allow_none=True)
    adopted_at = fields.DateTime(allow_none=True)
    stopped_at = fields.DateTime(allow_none=True)
    details = fields.Raw(allow_none=True)
    watchdog_id = fields.String(allow_none=True)
    watchdog_state = fields.Enum(WatchdogProcessState, by_value=True, allow_none=True)
    watchdog_control_port = fields.Integer(allow_none=True)
    watchdog_last_seen_at = fields.DateTime(allow_none=True)


class RuntimeRecoveryStatusSchema(Schema):
    phase = fields.String()
    reason = fields.String()
    attempt = fields.Integer()
    next_retry_at = fields.String(allow_none=True)
    hardware_access = fields.String()
    evidence = fields.Raw()
    operator_message = fields.String()


class ReconciliationSummarySchema(Schema):
    succeeded_operations = fields.Integer()
    failed_operations = fields.Integer()
    uncertain_operations = fields.Integer()
    adopted_runtimes = fields.Integer()
    stopped_runtimes = fields.Integer()
    uncertain_runtimes = fields.Integer()
    deferred_runtimes = fields.Integer()
    released_orphan_sessions = fields.Integer()


class DeviceTemplateContentSchema(Schema):
    type = fields.String(required=True, validate=validate.Length(min=1))
    parameters = fields.Dict(keys=fields.String(), values=fields.Raw(), load_default=dict)


class CreateDeviceTemplateSchema(DeviceTemplateContentSchema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=255))


class DeviceTemplateSchema(Schema):
    name = fields.String()
    file_path = fields.String()
    type = fields.String()
    content = fields.Raw()
    content_hash = fields.String()
    created_at = fields.DateTime(dump_only=True)


class RenameDeviceTemplateSchema(Schema):
    new_name = fields.String(required=True, validate=validate.Length(min=1, max=255))


class ReferencingSessionSchema(Schema):
    id = fields.String(dump_only=True)
    name = fields.String()
    status = fields.Enum(SessionStatus, by_value=True)
    policy = fields.Enum(PolicyMode, by_value=True)
    experiment_id = fields.String(allow_none=True)
    schedule = fields.Raw(allow_none=True)
    device_flows = fields.Raw()
    created_at = fields.DateTime(dump_only=True)


class DeviceTemplateRenameResponseSchema(Schema):
    device_template = fields.Nested(DeviceTemplateSchema)
    referencing_sessions = fields.List(fields.Nested("SessionTemplateSchema"))
    warning = fields.String()


class DeviceTemplateDeleteResponseSchema(Schema):
    deleted_name = fields.String()
    referencing_sessions = fields.List(fields.Nested("SessionTemplateSchema"))
    warning = fields.String()


class CreateDeviceConfigSchema(Schema):
    device_type = fields.Enum(DeviceType, by_value=True, required=True, data_key="type")
    hardware_id = fields.String(required=True, validate=validate.Length(min=1, max=255))
    port = fields.String(required=True, validate=validate.Length(min=1, max=255))
    parameters = fields.Dict(keys=fields.String(), values=fields.Raw(), load_default=dict)
    nickname = fields.String(allow_none=True, load_default=None)


class CreateDeviceConfigFromTemplateSchema(Schema):
    template_name = fields.String(required=True, validate=validate.Length(min=1, max=255))
    hardware_id = fields.String(required=True, validate=validate.Length(min=1, max=255))
    port = fields.String(required=True, validate=validate.Length(min=1, max=255))
    nickname = fields.String(allow_none=True, load_default=None)


class NameDeviceConfigSchema(Schema):
    device_type = fields.Enum(DeviceType, by_value=True, required=True, data_key="type")
    hardware_id = fields.String(required=True, validate=validate.Length(min=1, max=255))
    nickname = fields.String(required=True, validate=validate.Length(min=1, max=255))


class RegisterDeviceNameSchema(NameDeviceConfigSchema):
    """Input for naming a physical device before configuration."""


class DeviceRegistrationSchema(Schema):
    id = fields.Integer(dump_only=True)
    device_type = fields.Enum(DeviceType, by_value=True, data_key="type")
    hardware_id = fields.String()
    nickname = fields.String()
    device_config_id = fields.Integer(allow_none=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class EditDeviceConfigSchema(Schema):
    parameters = fields.Dict(keys=fields.String(), values=fields.Raw(), required=True)
    update_source_template = fields.Boolean(load_default=False)


class DeviceConfigSchema(Schema):
    id = fields.Integer(dump_only=True)
    device_type = fields.Enum(DeviceType, by_value=True, data_key="type")
    hardware_id = fields.String()
    port = fields.String()
    parameters = fields.Raw()
    color = fields.String(validate=validate.Regexp(r"^#[0-9a-fA-F]{6}$"))
    nickname = fields.String(allow_none=True)
    source_template = fields.String(allow_none=True)
    source_template_hash = fields.String(allow_none=True)
    source_template_history = fields.String(allow_none=True)
    claim_state = fields.Enum(DeviceClaimState, by_value=True)
    claimed_session_id = fields.Integer(allow_none=True)
    claim_expires_at = fields.DateTime(allow_none=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class DeviceConfigDeleteResponseSchema(Schema):
    deleted_id = fields.Integer()


class CreateSessionTemplateSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=255))
    policy = fields.Enum(PolicyMode, by_value=True, load_default=PolicyMode.RECOMMEND)
    device_flows = fields.List(fields.Raw(), required=True)


class SessionTemplateSchema(Schema):
    id = fields.Integer(dump_only=True)
    name = fields.String()
    content = fields.Raw()
    content_hash = fields.String()
    warnings = fields.List(fields.String(), dump_only=True, dump_default=list)
    created_at = fields.DateTime(dump_only=True)


class ExportSessionTemplateSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=255))
    binding_mode = fields.String(
        load_default="generic",
        validate=validate.OneOf(["generic", "device-hardcoded"]),
    )


class StartSessionSchema(Schema):
    """Input for starting a session.

    ``sink_overrides`` carries operator-confirmed sink_location fixes,
    keyed by device flow nickname — how the CLI retries a start after the
    daemon rejects one of the session's stored sink_location values as
    already existing (see SinkLocationExists / manifests.resolve()). Empty
    on an ordinary start.
    """

    sink_overrides = fields.Dict(
        keys=fields.String(),
        values=fields.String(),
        load_default=dict,
    )
    force = fields.Boolean(load_default=False)


class RecoverSessionSchema(Schema):
    """Input for a targeted per-stream recovery command."""

    device_id = fields.String(required=True, validate=validate.Length(min=1))
    action = fields.String(
        required=True,
        validate=validate.OneOf(["reconnect", "restart", "reset-stream"]),
    )


class StopSessionSchema(Schema):
    force = fields.Boolean(load_default=False)


class IncidentListQuerySchema(Schema):
    session = fields.Integer(required=True)
    status = fields.Enum(IncidentStatus, by_value=True, load_default=None)


class AckIncidentSchema(Schema):
    acknowledged_by = fields.String(load_default=None, validate=validate.Length(min=1, max=255))
    note = fields.String(load_default=None, validate=validate.Length(min=1, max=1024))


class IncidentSchema(Schema):
    id = fields.Integer(dump_only=True)
    incident_id = fields.String()
    session_id = fields.Integer()
    dataflow_id = fields.String()
    device_id = fields.String(allow_none=True)
    sink_id = fields.String(allow_none=True)
    runtime_id = fields.String(allow_none=True)
    operation_id = fields.String(allow_none=True)
    recovery_id = fields.String(allow_none=True)
    status = fields.String()
    reason = fields.String()
    policy = fields.String(allow_none=True)
    details = fields.Raw(allow_none=True)
    opened_at = fields.DateTime(allow_none=True)
    acknowledged_at = fields.DateTime(allow_none=True)
    acknowledged_by = fields.String(allow_none=True)
    acknowledgement_note = fields.String(allow_none=True)
    resolved_at = fields.DateTime(allow_none=True)
    resolution = fields.String(allow_none=True)


class GapListQuerySchema(Schema):
    session = fields.Integer(required=True)


class RecoveryGapSchema(Schema):
    id = fields.Integer(dump_only=True)
    gap_id = fields.String()
    incident_id = fields.String(allow_none=True)
    session_id = fields.Integer()
    dataflow_id = fields.String()
    device_id = fields.String(allow_none=True)
    sink_id = fields.String(allow_none=True)
    operation_id = fields.String(allow_none=True)
    recovery_id = fields.String(allow_none=True)
    previous_segment_id = fields.String(allow_none=True)
    next_segment_id = fields.String(allow_none=True)
    reason = fields.String()
    policy = fields.String(allow_none=True)
    confidence = fields.String()
    gap_start = fields.Raw(allow_none=True)
    gap_end = fields.Raw(allow_none=True)
    details = fields.Raw(allow_none=True)
    created_at = fields.DateTime(dump_only=True)


class SinkOutputStateSchema(Schema):
    """Durable per-sink output evidence, distilled from packet-21 ``output_files``.

    A SEPARATE provenance from the live report snapshot on ``SinkStatusSchema``:
    these are the control-plane's persisted finalization/delivery facts for a
    sink's output, surviving even when no live report is on record. ``artifact_state``
    is the finalization-job stage (``not_required``/``merge_pending``/``merging``/
    ``merged``/``merge_failed``); ``delivery_state`` is the service-sink delivery
    disposition; loss counters are durable and monotonic.
    """

    logical_sink_id = fields.String(allow_none=True)
    artifact_state = fields.String(allow_none=True)
    delivery_state = fields.String(allow_none=True)
    sample_loss = fields.Integer(allow_none=True)
    byte_loss = fields.Integer(allow_none=True)


class SinkStatusSchema(Schema):
    """One sink's runtime status — a SEPARATE axis from source/stream health.

    Keyed by durable ``(source_id, sink_id)`` identity (gaps SINK-08/SINK-23): a
    degraded, failed, buffering, or finalizing sink is reported here and is NEVER
    folded into the session's source ``health``/``phase``/``latest_report``. A
    running source and a failed sibling sink can therefore be true at once.

    ``status`` is a freshness marker independent of ``health``: ``current`` when
    the newest live report carried this sink, ``stale`` when only durable evidence
    (open incidents / output_files) exists, ``unknown`` when live sink state could
    not be loaded — so a healthy sink is always distinguishable from one whose
    live state is merely missing. ``health`` (SinkHealth), ``delivery``
    (SinkDeliveryState), and ``finalization`` (SinkFinalization) are the report's
    controlled vocabularies; loss counters are explicit and monotonic. All
    ``diagnostics`` are bounded and pre-redacted upstream — never raw samples,
    tokens, or resolved credential material.
    """

    source_id = fields.String(allow_none=True)
    sink_id = fields.String(allow_none=True)
    sink_class = fields.String(allow_none=True)
    status = fields.String()
    last_update = fields.DateTime(allow_none=True)
    health = fields.String(allow_none=True)
    delivery = fields.String(allow_none=True)
    finalization = fields.String(allow_none=True)
    component = fields.String(allow_none=True)
    buffered_samples = fields.Integer(allow_none=True)
    buffered_bytes = fields.Integer(allow_none=True)
    sample_loss = fields.Integer(allow_none=True)
    byte_loss = fields.Integer(allow_none=True)
    sink_sequence = fields.Integer(allow_none=True)
    diagnostics = fields.Raw(allow_none=True)
    open_incidents = fields.List(fields.Nested(IncidentSchema))
    output = fields.Nested(SinkOutputStateSchema, allow_none=True)


class SessionStatusSnapshotSchema(Schema):
    """Richer-than-``GET /sessions/<id>`` aggregate detail snapshot (6g)."""

    session = fields.Nested(SessionSchema)
    health = fields.String(allow_none=True)
    phase = fields.String(allow_none=True)
    latest_report = fields.Nested(LatestStreamEventSchema, allow_none=True)
    runtimes = fields.List(fields.Nested(RuntimeOwnershipSchema))
    operations = fields.List(fields.Nested(OperationSchema))
    incidents = fields.List(fields.Nested(IncidentSchema))
    gaps = fields.List(fields.Nested(RecoveryGapSchema))
    # Per-sink runtime status on a SEPARATE axis from source/stream health: a
    # failing or finalizing sink surfaces here and never as source failure or
    # recovery (gaps SINK-08/SINK-23). Keyed by ``(source_id, sink_id)``.
    sinks = fields.List(fields.Nested(SinkStatusSchema))
    # Newest runtime-ownership row for this session, in ANY state — not just
    # the "active" ones — so a stop-proof-missing limbo (UNCERTAIN) still
    # surfaces its last-known identity. See app.services.session_status
    # ._active_runtime_view.
    runtime_id = fields.String(allow_none=True)
    watchdog_id = fields.String(allow_none=True)
    watchdog_state = fields.String(allow_none=True)
    recovery = fields.Nested(RuntimeRecoveryStatusSchema, allow_none=True)
    # Freshness of the latest DIRECT watchdog-process telemetry — same
    # classification app.control.event_poller.telemetry_freshness uses to
    # trigger stale-telemetry/outbox-overflow incidents (packet contract:
    # monitoring truth is latest direct watchdog-process telemetry plus
    # freshness windows).
    last_report_at = fields.DateTime(allow_none=True)
    outbox_health = fields.String()
    telemetry_diagnostics = fields.Raw(allow_none=True)


class DiscoveredDeviceSchema(Schema):
    type = fields.Enum(DeviceType, by_value=True)
    port = fields.String()
    hardware_id = fields.String(allow_none=True)
    label = fields.String()
    availability = fields.String(
        validate=validate.OneOf(
            ["available", "unopenable", "not_found"]
        )
    )


class ScanResultSchema(Schema):
    scan_id = fields.String()
    scanned_at = fields.DateTime()
    devices = fields.List(fields.Nested(DiscoveredDeviceSchema))


class DevicePoolRowSchema(Schema):
    id = fields.Integer(allow_none=True)
    type = fields.String()
    port = fields.String()
    hardware_id = fields.String(allow_none=True)
    color = fields.String(allow_none=True, validate=validate.Regexp(r"^#[0-9a-fA-F]{6}$"))
    availability = fields.String(
        validate=validate.OneOf(
            ["available", "unopenable", "not_found"]
        )
    )
    status = fields.String(validate=validate.OneOf(["free", "claimed", "unconfigured"]))
    owner = fields.Integer(allow_none=True)
    nickname = fields.String(allow_none=True)
    label = fields.String(allow_none=True)


class DevicePoolSchema(Schema):
    scan_id = fields.String()
    scanned_at = fields.DateTime()
    devices = fields.List(fields.Nested(DevicePoolRowSchema))
