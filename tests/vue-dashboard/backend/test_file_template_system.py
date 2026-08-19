from pathlib import Path

from sqlalchemy import inspect

from app import create_app
from app.database import db
from app.services import device_configs, device_templates, session_templates


def _app(tmp_path):
    app = create_app(
        "testing",
        {
            "DEVICE_TEMPLATE_DIR": str(tmp_path / "device-templates"),
        },
    )
    with app.app_context():
        db.create_all()
    return app


def test_device_template_listing_is_file_only_and_idempotent(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        created = device_templates.create(
            "pod",
            {"type": "pod8206hr", "parameters": {"preamp_gain": 10, "sample_rate": 2000}},
        )
        first_listing = device_templates.list()
        second_listing = device_templates.list()

        assert created.file_path == "device-templates/pod.toml"
        assert [template.file_path for template in first_listing] == ["device-templates/pod.toml"]
        assert [template.file_path for template in second_listing] == ["device-templates/pod.toml"]
        assert "device_templates" not in inspect(db.engine).get_table_names()


def test_template_names_strip_file_extensions(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        device = device_templates.create(
            "pod.toml",
            {"type": "pod8206hr", "parameters": {"preamp_gain": 10, "sample_rate": 2000}},
        )
        session = session_templates.create(
            "session.toml",
            {
                "device_flows": [
                    {
                        "device_template_path": device.file_path,
                        "sink_type": "csv",
                    }
                ]
            },
        )

        assert device.name == "pod"
        assert device.file_path == "device-templates/pod.toml"
        assert session.name == "session"


def test_same_session_template_name_and_content_is_idempotent(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        device = device_templates.create(
            "pod",
            {"type": "pod8206hr", "parameters": {"preamp_gain": 10, "sample_rate": 2000}},
        )
        content = {
            "device_flows": [
                {"device_template_path": device.file_path, "sink_type": "csv"}
            ]
        }

        first = session_templates.create("session", content)
        second = session_templates.create("session.toml", content)

        assert second.id == first.id


def test_session_template_resolves_changed_path_and_hash(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        original = device_templates.create(
            "pod",
            {"type": "pod8206hr", "parameters": {"preamp_gain": 10, "sample_rate": 2000}},
        )
        stored = session_templates.create(
            "session",
            {
                "device_flows": [
                    {
                        "device_template_path": original.file_path,
                        "device_template_content_hash": original.content_hash,
                        "sink_type": "csv",
                    }
                ]
            },
        )

        device_templates.update(
            "pod",
            {"type": "pod8206hr", "parameters": {"preamp_gain": 10, "sample_rate": 1000}},
        )
        resolved, warnings = session_templates.resolve_device_template_reference(
            stored.content["device_flows"][0]
        )

        assert resolved.content["parameters"]["sample_rate"] == 1000
        assert warnings


def test_device_config_records_source_template_hash(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        template = device_templates.create(
            "pod",
            {"type": "pod8206hr", "parameters": {
                "preamp_gain": 10,
                "sample_rate": 2000,
                }},
        )
        config = device_configs.create_from_template(
            template,
            hardware_id="001",
            port="COM1",
        )

        assert config.source_template == template.file_path
        assert config.source_template_hash == template.content_hash


def test_session_template_api_object_exposes_reference_warning_state(tmp_path):
    app = _app(tmp_path)
    with app.app_context():
        template = device_templates.create(
            "pod",
            {"type": "pod8206hr", "parameters": {"preamp_gain": 10, "sample_rate": 2000}},
        )
        row = session_templates.create(
            "reference-warning-session",
            {
                "device_flows": [
                    {
                        "device_template_path": template.file_path,
                        "device_template_content_hash": "0" * 64,
                        "sink_type": "csv",
                    }
                ]
            },
        )

        assert row.reference_warnings
