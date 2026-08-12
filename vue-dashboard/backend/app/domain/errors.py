"""Typed domain exceptions raised by services and caught by adapter layers.

Nothing in this module imports Flask. HTTP, CLI, and future adapters map these
exceptions to their own response formats at the boundary.
"""


class SessionNotFound(Exception):
    def __init__(self, session_id: int):
        self.session_id = session_id
        super().__init__(f"No session with id {session_id!r}.")


class SessionNoteNotFound(Exception):
    def __init__(self, session_id: int, note_id: int):
        self.session_id = session_id
        self.note_id = note_id
        super().__init__(f"No note with id {note_id!r} exists on session {session_id!r}.")


class SessionRunRequestConflict(Exception):
    """An idempotency key was reused for a different run request."""

    code = "session_run_request_conflict"

    def __init__(self, request_key: str):
        self.request_key = request_key
        super().__init__(
            f"Idempotency key {request_key!r} already belongs to a different run request."
        )


class CommandInFlight(Exception):
    def __init__(
        self,
        session_id: int,
        *,
        code: str = "command_in_flight",
        details: dict | None = None,
    ):
        self.session_id = session_id
        self.code = code
        self.details = dict(details) if details is not None else {}
        super().__init__(f"A command is already running on session {session_id!r}.")


class InvalidTransition(Exception):
    def __init__(self, current):
        self.current = current
        super().__init__(f"Cannot transition from status {current!r}.")


class EmptySession(Exception):
    def __init__(self, session_id: int):
        self.session_id = session_id
        super().__init__(f"Session {session_id!r} has no device flows.")


class RuntimeStartupFailed(RuntimeError):
    """A runtime child reported a typed failure before becoming ready."""

    code = "runtime_startup_failed"

    def __init__(
        self,
        *,
        error_type: str,
        message: str,
        device_id=None,
        sink_id=None,
        sink_type=None,
    ):
        self.details = {
            "error_type": error_type,
            "device_id": device_id,
            "sink_id": sink_id,
            "sink_type": sink_type,
        }
        super().__init__(message)


class OperationNotFound(Exception):
    def __init__(self, operation_id: str):
        self.operation_id = operation_id
        super().__init__(f"No operation with id {operation_id!r}.")


class OperationResolutionError(Exception):
    def __init__(self, operation_id: str, reason: str):
        self.operation_id = operation_id
        self.reason = reason
        super().__init__(f"Cannot resolve operation {operation_id!r}: {reason}.")


class UnknownConfigType(Exception):
    def __init__(self, category: str, type_key: str):
        self.category = category
        self.type_key = type_key
        super().__init__(f"Unknown {category} type: {type_key!r}.")


class UnsupportedDeviceType(Exception):
    def __init__(self, device_type: str):
        self.device_type = device_type
        super().__init__(
            f"Device type {device_type!r} is a known DeviceType but has no pinned "
            "parameter schema yet."
        )


class DeviceTemplateNotFound(Exception):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Device template not found: {name!r}.")


class DeviceTemplateNameExists(ValueError):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Device template name already exists: {name!r}.")


class DeviceConfigNotFound(Exception):
    def __init__(self, config_id: int):
        self.config_id = config_id
        super().__init__(f"Device config not found: {config_id!r}.")


class DeviceConfigExists(ValueError):
    def __init__(self, device_type: str, hardware_id: str):
        self.device_type = device_type
        self.hardware_id = hardware_id
        super().__init__(
            f"Device config already exists for {device_type!r} + {hardware_id!r}."
        )


class DeviceNicknameExists(ValueError):
    def __init__(self, nickname: str):
        self.nickname = nickname
        super().__init__(f"Device nickname already exists: {nickname!r}.")


class DeviceConfigNotFree(Exception):
    def __init__(self, config_id: int):
        self.config_id = config_id
        super().__init__(
            f"Device config {config_id!r} is claimed; edit/delete/claim requires a free config."
        )


class DeviceClaimConflict(Exception):
    def __init__(self, config_id: int, *, claimed_session_id: int | None):
        self.config_id = config_id
        self.claimed_session_id = claimed_session_id
        self.details = {
            "device_config_id": config_id,
            "claimed_session_id": claimed_session_id,
        }
        super().__init__(
            f"Device config {config_id!r} is already claimed"
            f" by session {claimed_session_id!r}. Pass force=true to steal the claim."
        )


class InvalidHardwareId(ValueError):
    def __init__(self, hardware_id: str):
        self.hardware_id = hardware_id
        super().__init__(
            f"Invalid hardware_id {hardware_id!r}: must match ^[0-9]{{1,8}}$ (1-8 digits — the "
            "FTDI EEPROM serial without its trailing channel letter)."
        )


class InvalidSessionEntry(ValueError):
    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(f"Invalid session entry field {field!r}: {message}")


class UnresolvableSession(Exception):
    def __init__(self, session_id: int, missing_config: str):
        self.session_id = session_id
        self.missing_config = missing_config
        super().__init__(
            f"Session {session_id!r} references missing device template: {missing_config!r}."
        )


class SinkLocationExists(Exception):
    """A device flow's sink_location already has a file at it before a run.

    Raised only for an explicit, user-supplied sink_location — a
    system-assigned one is deduplicated instead (see
    services.sink_paths.next_available_path). An explicit path is the
    operator naming a specific file on purpose, so silently picking a
    different name out from under them would be more surprising than
    failing loud — instead ``suggested_location`` carries a proposed
    alternative (see services.sink_paths.next_available_path) so the caller
    (CLI, UI) can offer it as a one-keystroke fix rather than making the
    operator type a whole new path.

    ``details`` follows the same convention as CommandInFlight.details: the
    app.errors._domain() handler merges it into the RFC 9457 problem body's
    extension fields, so a caller can read e.g. response["suggested_location"]
    without parsing ``detail`` prose.
    """

    def __init__(
        self,
        sink_location: str,
        *,
        nickname: str | None = None,
        suggested_location: str | None = None,
        flow_index: int | None = None,
        sink_index: int | None = None,
    ):
        self.sink_location = sink_location
        self.nickname = nickname
        self.suggested_location = suggested_location
        self.flow_index = flow_index
        self.sink_index = sink_index
        self.details: dict[str, object] = {"sink_location": sink_location}
        if nickname:
            self.details["nickname"] = nickname
        if suggested_location:
            self.details["suggested_location"] = suggested_location
        # Template-created runs address sinks positionally — the operator never
        # sees or types a sink name — so a collision has to come back with the
        # coordinates the client submitted, not just a nickname.
        if flow_index is not None:
            self.details["flow_index"] = flow_index
        if sink_index is not None:
            self.details["sink_index"] = sink_index

        label = f" for device flow {nickname!r}" if nickname else ""
        suggestion_note = (
            f" Suggested alternative: {suggested_location!r}." if suggested_location else ""
        )
        super().__init__(
            f"sink_location{label} already exists: {sink_location!r}.{suggestion_note} "
            "Choose a different path or remove the existing file."
        )


class SinkParentUnavailable(Exception):
    """A sink path names a parent that cannot accept a new output file.
    """

    def __init__(
        self,
        sink_location: str,
        *,
        directory: str,
        reason: str,
        nickname: str | None = None,
    ) -> None:
        self.details = {
            "sink_location": sink_location,
            "directory": directory,
            "reason": reason,
        }
        if nickname:
            self.details["nickname"] = nickname

        if reason == "missing":
            problem = "does not exist and could not be created"
        elif reason == "not_directory":
            problem = "is a file, not a directory"
        else:
            problem = "is not writable"
        label = f" for sink {nickname!r}" if nickname else ""
        super().__init__(
            f"Output directory{label} {directory!r} {problem}. "
            "Choose an existing writable folder before starting."
        )


class UnknownDataflow(Exception):
    def __init__(self, dataflow_id: str):
        self.dataflow_id = dataflow_id
        super().__init__(f"No session is linked to dataflow {dataflow_id!r}.")


class RuntimeNotTracked(Exception):
    """The supervisor has no in-memory record of a runtime for this dataflow.

    Distinct from ``UnknownDataflow`` (no session owns the dataflow at all):
    here the session and dataflow are known, but the daemon's in-process
    ``HostSupervisor._children`` registry has no live entry for it — either the
    runtime process died, or the daemon restarted before reconciling it.
    """

    def __init__(self, dataflow_id: str):
        self.dataflow_id = dataflow_id
        super().__init__(
            f"No runtime is currently tracked for dataflow {dataflow_id!r}. "
            "It may have died, or the daemon restarted before reconciling it; "
            "check 'pinnacle runtime list' and 'pinnacle runtime reconcile'."
        )


class StopProofMissing(RuntimeError):
    """A managed stop tore the process down but found no durable proof of a
    clean stop. Claims and runtime identity stay untouched and the session
    stays ACTIVE (retryable); ``--force`` is the only way to resolve it.
    """

    def __init__(self, dataflow_id: str, *, runtime_id: str) -> None:
        self.dataflow_id = dataflow_id
        self.runtime_id = runtime_id
        self.details = {"dataflow_id": dataflow_id, "runtime_id": runtime_id}
        super().__init__(
            f"No durable proof of a clean stop for dataflow {dataflow_id!r} "
            f"(runtime_id={runtime_id!r}): no stopped/closed report, no clean "
            "watchdog process exit, and no clean runtime host process exit. "
            "Retry the stop with force=true to complete it and release claims."
        )


class StaleWatchdogReport(Exception):
    """A watchdog-state write named a ``watchdog_id`` that is not the active one.

    Fencing counterpart, at persistence, to the command-envelope staleness
    check: a late report from a dead watchdog process (outbox flush, stuck
    socket) must not be able to overwrite its respawned successor's state.
    Raised instead of a silent no-op so the rejection is auditable.
    """

    def __init__(self, runtime_id: str, *, reported_watchdog_id: str, active_watchdog_id: str | None):
        self.runtime_id = runtime_id
        self.reported_watchdog_id = reported_watchdog_id
        self.active_watchdog_id = active_watchdog_id
        super().__init__(
            f"Stale watchdog report for runtime {runtime_id!r}: reported watchdog_id "
            f"{reported_watchdog_id!r} does not match active watchdog_id "
            f"{active_watchdog_id!r}."
        )


class IncidentNotFound(Exception):
    def __init__(self, incident_id: str):
        self.incident_id = incident_id
        super().__init__(f"Incident not found: {incident_id!r}.")


class SessionTemplateNotFound(Exception):
    def __init__(self, reference: str):
        self.reference = reference
        super().__init__(f"Session template not found: {reference!r}.")


class SessionTemplateNameExists(ValueError):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Session template name already exists: {name!r}.")


class SessionTemplateReconciliationRetry(Exception):
    """The template catalog changed repeatedly while reconciliation was committing."""

    def __init__(self):
        self.details = {
            "current_state": None,
            "allowed_actions": [],
        }
        super().__init__("Template catalog changed concurrently; retry the request.")


class SessionTemplateDuplicate(SessionTemplateNameExists):
    """A create/import matches an existing registered template definition."""

    code = "duplicate_template"

    def __init__(self, existing_template: dict, current_state: str, allowed_actions: list[str]):
        self.details = {
            "existing_template": existing_template,
            "current_state": current_state,
            "allowed_actions": allowed_actions,
        }
        ValueError.__init__(self, "Template configuration is already registered.")


class SessionTemplateStateConflict(SessionTemplateNameExists):
    """An action is not legal from the template's current reconciled state."""

    code = "template_state_conflict"

    def __init__(self, message: str, current_state: str, allowed_actions: list[str]):
        self.details = {
            "current_state": current_state,
            "allowed_actions": allowed_actions,
        }
        ValueError.__init__(self, message)


__all__ = [
    "CommandInFlight",
    "DeviceClaimConflict",
    "DeviceConfigExists",
    "DeviceNicknameExists",
    "DeviceConfigNotFound",
    "DeviceConfigNotFree",
    "DeviceTemplateNameExists",
    "DeviceTemplateNotFound",
    "EmptySession",
    "IncidentNotFound",
    "InvalidHardwareId",
    "InvalidSessionEntry",
    "InvalidTransition",
    "OperationNotFound",
    "OperationResolutionError",
    "RuntimeNotTracked",
    "SessionNotFound",
    "SessionTemplateNameExists",
    "SessionTemplateNotFound",
    "SessionTemplateDuplicate",
    "SessionTemplateReconciliationRetry",
    "SessionTemplateStateConflict",
    "SinkLocationExists",
    "StaleWatchdogReport",
    "StopProofMissing",
    "UnknownConfigType",
    "UnknownDataflow",
    "UnresolvableSession",
    "UnsupportedDeviceType",
]
