from __future__ import annotations

import json

from click.testing import CliRunner

from app.cli.main import pinnacle


class FakeDaemonClient:
    def __init__(self, *, posts=None, gets=None, error=None):
        self.posts = list(posts or [])
        self.gets = dict(gets or {})
        self.error = error
        self.calls: list[tuple[str, str, object | None]] = []

    def post(self, path: str, payload):
        self.calls.append(("POST", path, payload))
        if self.error is not None:
            raise self.error
        return self.posts.pop(0)

    def get(self, path: str):
        self.calls.append(("GET", path, None))
        if self.error is not None:
            raise self.error
        return self.gets[path]


def _use_fake_client(monkeypatch, fake: FakeDaemonClient) -> None:
    import app.cli.session_cmd as session_cmd

    monkeypatch.setattr(session_cmd, "DaemonClient", lambda: fake)


def _use_app(monkeypatch, app) -> None:
    import app.cli.session_cmd as session_cmd

    monkeypatch.setattr(session_cmd, "create_app", lambda: app)


def post_calls_payload(fake: FakeDaemonClient) -> dict:
    post_calls = [call for call in fake.calls if call[0] == "POST"]
    assert len(post_calls) == 1
    return post_calls[0][2]


# The single-CSV sink the guided quiz builds when the operator accepts every
# default: type csv, name csv, no location, no optional parameters.
_DEFAULT_CSV_SINK = {"sink_name": "csv", "sink_type": "csv", "sink_parameters": {}}


def test_guided_create_flow1_picks_a_free_device_config(monkeypatch):
    fake = FakeDaemonClient(
        gets={
            "/api/v1/device-configs": [
                {
                    "id": 7,
                    "type": "pod8206hr",
                    "hardware_id": "HW001",
                    "port": "COM3",
                    "nickname": "bench-pod",
                    "claim_state": "free",
                },
                {
                    "id": 8,
                    "type": "pod8401hr",
                    "hardware_id": "HW002",
                    "port": "COM4",
                    "nickname": None,
                    "claim_state": "claimed",
                },
            ],
        },
        posts=[{"id": "1", "status": "draft"}],
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        pinnacle,
        ["session", "create"],
        # device name, sink type, sink name, sink location, optional-params=N,
        # sink action=done, session name, policy
        input="bench-pod\n\n\n\n\n\n\n\n",
    )

    assert result.exit_code == 0, result.output
    post_calls = [call for call in fake.calls if call[0] == "POST"]
    assert len(post_calls) == 1
    _, path, payload = post_calls[0]
    assert path == "/api/v1/sessions/"
    assert payload["policy"] == "recommend"
    assert payload["device_flows"] == [
        {
            "device_config_id": 7,
            "nickname": "bench-pod",
            "sinks": [_DEFAULT_CSV_SINK],
        }
    ]


def test_guided_create_flow1_adds_multiple_sinks_to_one_source(monkeypatch):
    fake = FakeDaemonClient(
        gets={
            "/api/v1/device-configs": [
                {
                    "id": 7,
                    "type": "pod8206hr",
                    "hardware_id": "HW001",
                    "port": "COM3",
                    "nickname": "bench-pod",
                    "claim_state": "free",
                },
            ],
        },
        posts=[{"id": "1", "status": "draft"}],
    )
    _use_fake_client(monkeypatch, fake)

    # First sink: csv with an explicit location. Then add a second, repeated csv
    # sink (distinct auto name csv-2) and an influx service sink whose token is
    # an env-var NAME, never a value.
    result = CliRunner().invoke(
        pinnacle,
        ["session", "create"],
        input="\n".join(
            [
                "bench-pod",  # device config id or name
                # sink 1: csv -> C:/data/a.csv
                "csv",  # sink type
                "primary",  # sink name
                "C:/data/a.csv",  # sink location
                "n",  # optional params?
                # menu: add another
                "add",
                # sink 2: repeated csv, default name csv, no location, no params
                "csv",
                "",  # accept default name
                "",  # no location
                "n",  # optional params?
                # menu: add another
                "add",
                # sink 3: influx (service) -> env-var name only
                "influx",
                "metrics",  # sink name
                "PINNACLE_INFLUX_TOKEN",  # api_token_env (required)
                "n",  # optional params?
                # menu: done
                "done",
                "",  # session name
                "",  # policy
            ]
        )
        + "\n",
    )

    assert result.exit_code == 0, result.output
    payload = post_calls_payload(fake)
    assert payload["device_flows"] == [
        {
            "device_config_id": 7,
            "nickname": "bench-pod",
            "sinks": [
                {
                    "sink_name": "primary",
                    "sink_type": "csv",
                    "sink_location": "C:/data/a.csv",
                    "sink_parameters": {},
                },
                {"sink_name": "csv", "sink_type": "csv", "sink_parameters": {}},
                {
                    "sink_name": "metrics",
                    "sink_type": "influx",
                    "sink_parameters": {"api_token_env": "PINNACLE_INFLUX_TOKEN"},
                },
            ],
        }
    ]
    # A service sink is never offered a sink_location.
    assert all("sink_location" not in s for s in payload["device_flows"][0]["sinks"][1:])


def test_guided_create_flow1_errors_when_no_free_configs(monkeypatch):
    fake = FakeDaemonClient(
        gets={
            "/api/v1/device-configs": [
                {"id": 8, "type": "pod8401hr", "hardware_id": "HW002", "claim_state": "claimed"},
            ],
        },
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["session", "create"])

    assert result.exit_code != 0
    assert "No free device configs found" in result.output


def test_guided_create_flow2_instantiates_a_stored_template_by_name(monkeypatch):
    fake = FakeDaemonClient(
        gets={
            "/api/v1/session-templates/bench-session": {
                "id": 1,
                "name": "bench-session",
                "content": {
                    "policy": "recommend",
                    "device_flows": [
                        {
                            "device_template": "bench-rig",
                            "nickname": "bench",
                            "sink_type": "csv",
                        }
                    ],
                },
            },
            "/api/v1/device-templates": [
                {
                    "id": 5,
                    "name": "bench-rig",
                    "type": "pod8206hr",
                    "file_path": "bench-rig.toml",
                    "content_hash": "abc",
                },
            ],
            "/api/v1/devices/pool": {
                "scan_id": "s1",
                "scanned_at": "2026-07-06T00:00:00Z",
                "devices": [
                    {
                        "id": None,
                        "type": "pod8206hr",
                        "port": "COM5",
                        "hardware_id": "HW003",
                        "availability": "available",
                        "status": "unconfigured",
                    },
                ],
            },
        },
        posts=[{"id": "2", "status": "draft"}],
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        pinnacle,
        ["session", "create", "--template", "bench-session"],
        # assignment mode (default auto), sink action (done), session name
        input="\n\n\n",
    )

    assert result.exit_code == 0, result.output
    post_calls = [call for call in fake.calls if call[0] == "POST"]
    assert len(post_calls) == 1
    _, path, payload = post_calls[0]
    assert path == "/api/v1/sessions/"
    assert payload["policy"] == "recommend"
    assert payload["device_flows"] == [
        {
            "device_template_path": "bench-rig.toml",
            "device_template_content_hash": "abc",
            "hardware_id": "HW003",
            "port": "COM5",
            "nickname": "bench",
            "sinks": [_DEFAULT_CSV_SINK],
        }
    ]
    # never touches device-configs — Flow 2 only ever references device templates.
    assert ("GET", "/api/v1/device-configs", None) not in fake.calls


def test_guided_create_flow2_pick_mode_selects_by_config_id_and_notes_unconfigured(monkeypatch):
    fake = FakeDaemonClient(
        gets={
            "/api/v1/session-templates/bench-session": {
                "id": 1,
                "name": "bench-session",
                "content": {
                    "policy": "recommend",
                    "device_flows": [
                        {
                            "device_template": "bench-rig",
                            "nickname": "bench",
                            "sink_type": "csv",
                        }
                    ],
                },
            },
            "/api/v1/device-templates": [
                {
                    "id": 5,
                    "name": "bench-rig",
                    "type": "pod8206hr",
                    "file_path": "bench-rig.toml",
                    "content_hash": "abc",
                },
            ],
            "/api/v1/devices/pool": {
                "scan_id": "s1",
                "scanned_at": "2026-07-06T00:00:00Z",
                "devices": [
                    {
                        "id": 9,
                        "type": "pod8206hr",
                        "port": "COM3",
                        "hardware_id": "HW001",
                        "nickname": "bench-pod",
                        "availability": "available",
                        "status": "free",
                    },
                    {
                        "id": None,
                        "type": "pod8206hr",
                        "port": "COM5",
                        "hardware_id": "HW003",
                        "availability": "available",
                        "status": "unconfigured",
                    },
                ],
            },
        },
        posts=[{"id": "9", "status": "draft"}],
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        pinnacle,
        ["session", "create", "--template", "bench-session"],
        # assignment mode (pick), config id, sink action (done), session name
        input="pick\n9\n\n\n",
    )

    assert result.exit_code == 0, result.output
    assert "note: 1 matching device unconfigured" in result.output
    assert "run 'pinnacle device config'" in result.output
    payload = post_calls_payload(fake)
    assert payload["device_flows"] == [
        {
            "device_config_id": 9,
            "nickname": "bench-pod",
            "sinks": [_DEFAULT_CSV_SINK],
        }
    ]


def test_guided_create_flow2_instantiates_a_stored_template_by_number(monkeypatch):
    fake = FakeDaemonClient(
        gets={
            "/api/v1/session-templates": [
                {
                    "id": 1,
                    "name": "bench-session",
                    "content": {
                        "policy": "automate",
                        "device_flows": [{"device_template": "bench-rig", "sink_type": "csv"}],
                    },
                },
            ],
            "/api/v1/device-templates": [
                {
                    "id": 5,
                    "name": "bench-rig",
                    "type": "pod8206hr",
                    "file_path": "bench-rig.toml",
                    "content_hash": "abc",
                },
            ],
            "/api/v1/devices/pool": {
                "scan_id": "s1",
                "scanned_at": "now",
                "devices": [
                    {
                        "id": None,
                        "type": "pod8206hr",
                        "port": "COM7",
                        "hardware_id": "HW009",
                        "availability": "available",
                        "status": "unconfigured",
                    },
                ],
            },
        },
        posts=[{"id": "3", "status": "draft"}],
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(
        pinnacle,
        ["session", "create", "--template", "1"],
        # assignment mode (default auto), sink action (done), session name.
        # policy comes from the template ("automate") and is not re-prompted.
        input="\n\n\n",
    )

    assert result.exit_code == 0, result.output
    payload = post_calls_payload(fake)
    assert payload["policy"] == "automate"
    assert payload["device_flows"] == [
        {
            "device_template_path": "bench-rig.toml",
            "device_template_content_hash": "abc",
            "hardware_id": "HW009",
            "port": "COM7",
            "nickname": "bench-rig",
            "sinks": [_DEFAULT_CSV_SINK],
        }
    ]


def test_guided_create_flow2_file_reference_resolves_names_to_ids(monkeypatch, tmp_path):
    fake = FakeDaemonClient(
        gets={
            "/api/v1/device-templates": [
                {
                    "id": 5,
                    "name": "bench-rig",
                    "type": "pod8206hr",
                    "file_path": "bench-rig.toml",
                    "content_hash": "abc",
                },
            ],
            "/api/v1/devices/pool": {
                "scan_id": "s1",
                "scanned_at": "now",
                "devices": [
                    {
                        "id": None,
                        "type": "pod8206hr",
                        "port": "COM5",
                        "hardware_id": "HW003",
                        "availability": "available",
                        "status": "unconfigured",
                    },
                ],
            },
        },
        posts=[{"id": "4", "status": "draft"}],
    )
    _use_fake_client(monkeypatch, fake)
    template_path = tmp_path / "portable-template.toml"
    template_path.write_text(
        "\n".join(
            [
                "[[device_flows]]",
                'device_template = "bench-rig"',
                'nickname = "bench"',
                "",
                "[[device_flows.sinks]]",
                'sink_name = "csv"',
                'sink_type = "csv"',
            ]
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        pinnacle,
        ["session", "create", "--template", str(template_path)],
        # assignment mode (default auto), sink action (done), session name, policy
        input="\n\n\n\n",
    )

    assert result.exit_code == 0, result.output
    payload = post_calls_payload(fake)
    assert payload["device_flows"] == [
        {
            "device_template_path": "bench-rig.toml",
            "device_template_content_hash": "abc",
            "hardware_id": "HW003",
            "port": "COM5",
            "nickname": "bench",
            "sinks": [_DEFAULT_CSV_SINK],
        }
    ]
    # a file reference never hits /api/v1/session-templates at all.
    assert not any(call[1].startswith("/api/v1/session-templates") for call in fake.calls)


def test_guided_create_flow2_template_number_can_resolve_local_library_file(
    app, monkeypatch, tmp_path
):
    fake = FakeDaemonClient(
        gets={
            "/api/v1/session-templates": [
                {
                    "id": 1,
                    "name": "stored-template",
                    "content": {
                        "policy": "automate",
                        "device_flows": [{"device_template": "stored-rig", "sink_type": "csv"}],
                    },
                    "content_hash": "stored-hash",
                },
            ],
            "/api/v1/device-templates": [
                {
                    "id": 5,
                    "name": "bench-rig",
                    "type": "pod8206hr",
                    "file_path": "bench-rig.toml",
                    "content_hash": "abc",
                },
                {
                    "id": 99,
                    "name": "stored-rig",
                    "type": "pod8206hr",
                    "file_path": "stored-rig.toml",
                    "content_hash": "def",
                },
            ],
            "/api/v1/devices/pool": {
                "scan_id": "s1",
                "scanned_at": "now",
                "devices": [
                    {
                        "id": None,
                        "type": "pod8206hr",
                        "port": "COM5",
                        "hardware_id": "HW003",
                        "availability": "available",
                        "status": "unconfigured",
                    },
                ],
            },
        },
        posts=[{"id": "4", "status": "draft"}],
    )
    _use_fake_client(monkeypatch, fake)
    _use_app(monkeypatch, app)
    # Isolate the session-template library so `--template 2` deterministically
    # resolves to the one local file (position 2 after the single stored one),
    # never a leftover file in the shared instance directory.
    import app.cli.session_cmd as session_cmd

    library_dir = tmp_path / "session-templates"
    library_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(session_cmd, "_session_template_library_dir", lambda: library_dir)
    (library_dir / "portable-template.toml").write_text(
        "\n".join(
            [
                "[[device_flows]]",
                'device_template = "bench-rig"',
                'nickname = "bench"',
                'sink_type = "csv"',
            ]
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        pinnacle,
        ["session", "create", "--template", "2"],
        input="\n\n\n\n",
    )

    assert result.exit_code == 0, result.output
    payload = post_calls_payload(fake)
    assert payload["device_flows"] == [
        {
            "device_template_path": "bench-rig.toml",
            "device_template_content_hash": "abc",
            "hardware_id": "HW003",
            "port": "COM5",
            "nickname": "bench",
            "sinks": [_DEFAULT_CSV_SINK],
        }
    ]


def test_guided_create_flow2_unknown_template_name_errors(monkeypatch):
    from app.cli.daemon_client import DaemonError

    fake = FakeDaemonClient(
        error=DaemonError("Not Found", "Session template not found: 'missing'.", status_code=404)
    )
    _use_fake_client(monkeypatch, fake)

    result = CliRunner().invoke(pinnacle, ["session", "create", "--template", "missing"])

    assert result.exit_code != 0
    assert "Not Found" in result.output


def test_create_from_file_still_bypasses_guided_flow(monkeypatch, tmp_path):
    fake = FakeDaemonClient(posts=[{"id": "3", "status": "draft"}])
    _use_fake_client(monkeypatch, fake)
    config_path = tmp_path / "session.toml"
    config_path.write_text(
        "\n".join(
            [
                'name = "from-file"',
                'policy = "recommend"',
                "",
                "[[device_flows]]",
                'device_template_path = "bench-rig.toml"',
                'hardware_id = "HW001"',
                'port = "COM3"',
                "",
                "[[device_flows.sinks]]",
                'sink_name = "csv"',
                'sink_type = "csv"',
            ]
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(pinnacle, ["session", "create", "--from", str(config_path)])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["id"] == "3"
    # no GET calls at all — --from skips the guided questionnaire entirely.
    assert all(call[0] == "POST" for call in fake.calls)
