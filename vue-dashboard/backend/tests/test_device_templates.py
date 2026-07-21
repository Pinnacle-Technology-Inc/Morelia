"""Contract tests for the named, mutable device template library."""

import json

import pytest

from app.database import db
from app.domain.errors import UnknownConfigType
from app.models.device_template import DeviceTemplate
from app.repositories.sessions import SessionRepository
from app.services.device_templates import (
    _canonicalize,
    _content_hash,
    clone,
    content_hash,
    create,
    delete,
    diff,
    export,
    export_artifact,
    get_by_id,
    get_by_name,
    import_config,
    references,
    rename,
    update,
)
from app.services.device_templates import (
    list as list_configs,
)

_VALID_CONTENT = {
    "type": "pod8206hr",
    "parameters": {"preamp_gain": "10", "sample_rate": "2000"},
}
_ALTERED_CONTENT = {
    "type": "pod8206hr",
    "parameters": {"preamp_gain": 10, "sample_rate": 2500, "lowpass_ch0": 50},
}


def test_canonicalize_validates_and_normalizes_device_parameters():
    result = _canonicalize(_VALID_CONTENT)

    assert result == {
        "type": "pod8206hr",
        "parameters": {"preamp_gain": 10, "sample_rate": 2000},
    }


def test_canonicalize_unknown_device_type_raises_typed_error():
    with pytest.raises(UnknownConfigType) as exc_info:
        _canonicalize({"type": "unknown_hw", "parameters": {"preamp_gain": 10}})

    assert exc_info.value.category == "device"
    assert exc_info.value.type_key == "unknown_hw"


def test_canonicalize_bad_parameter_raises_value_error():
    with pytest.raises(ValueError, match="unknown"):
        _canonicalize(
            {
                "type": "pod8206hr",
                "parameters": {"preamp_gain": 10, "ttl_port": 3},
            }
        )


def test_content_hash_is_stable_for_canonical_content():
    a = _content_hash(_canonicalize(_VALID_CONTENT))
    b = _content_hash(
        _canonicalize(
            {
                "type": "pod8206hr",
                "parameters": {"sample_rate": 2000, "preamp_gain": 10},
            }
        )
    )

    assert a == b
    assert len(a) == 64


def test_public_content_hash_ignores_name_and_canonicalizes_values():
    a = content_hash(
        {
            "name": "main-pod",
            "type": "pod8206hr",
            "parameters": {"preamp_gain": "10"},
        }
    )
    b = content_hash(
        {
            "name": "backup-pod",
            "type": "pod8206hr",
            "parameters": {"preamp_gain": 10},
        }
    )

    assert a == b


def test_create_persists_named_device_template(app):
    with app.app_context():
        cfg = create("pod-high", _VALID_CONTENT)

        assert cfg.id is not None
        assert cfg.name == "pod-high"
        assert cfg.type == "pod8206hr"
        assert cfg.content == {
            "type": "pod8206hr",
            "parameters": {"preamp_gain": 10, "sample_rate": 2000},
        }
        assert len(cfg.content_hash) == 64


def test_create_with_existing_name_auto_suffixes_without_overwrite(app):
    with app.app_context():
        first = create("pod-high", _VALID_CONTENT)
        second = create("pod-high", _ALTERED_CONTENT)
        third = create("pod-high", {"type": "pod8206hr", "parameters": {"preamp_gain": 100}})

        assert first.name == "pod-high"
        assert second.name == "pod-high-2"
        assert third.name == "pod-high-3"
        assert get_by_name("pod-high").id == first.id


def test_same_content_under_new_name_creates_new_row_with_same_hash(app):
    with app.app_context():
        first = create("pod-a", _VALID_CONTENT)
        second = create(
            "pod-b",
            {
                "type": "pod8206hr",
                "parameters": {"sample_rate": 2000, "preamp_gain": 10},
            },
        )

        assert first.id != second.id
        assert first.name == "pod-a"
        assert second.name == "pod-b"
        assert first.content_hash == second.content_hash


def test_get_by_name_get_by_id_and_list_work(app):
    with app.app_context():
        first = create("pod-a", _VALID_CONTENT)
        second = create("pod-b", _ALTERED_CONTENT)

        assert get_by_name("pod-a").id == first.id
        assert get_by_id(second.id).name == "pod-b"
        assert get_by_id(9999) is None
        assert [cfg.name for cfg in list_configs()] == ["pod-a", "pod-b"]


def test_references_returns_sessions_that_point_at_name(app):
    with app.app_context():
        repo = SessionRepository()
        referenced = repo.create(
            {
                "name": "Run A",
                "device_flows": [
                    {"nickname": "left", "device_template": "pod-high"},
                    {"nickname": "right", "device_template": "pod-low"},
                ],
            }
        )
        repo.create({"name": "Run B", "device_flows": [{"device_template": "pod-low"}]})
        repo.create({"name": "Run C", "device_flows": [{"device": "legacy-shape"}]})

        result = references("pod-high")

        assert [session.id for session in result] == [referenced.id]


def test_rename_returns_references_and_does_not_mutate_content(app):
    with app.app_context():
        cfg = create("pod-high", _VALID_CONTENT)
        repo = SessionRepository()
        referenced = repo.create(
            {"name": "Run A", "device_flows": [{"device_template": "pod-high"}]}
        )

        renamed, refs = rename("pod-high", "pod-renamed")

        assert renamed.id == cfg.id
        assert renamed.name == "pod-renamed"
        assert renamed.content_hash == cfg.content_hash
        assert [session.id for session in refs] == [referenced.id]
        assert get_by_name("pod-high") is None


def test_update_rewrites_content_in_place_and_recomputes_hash(app):
    with app.app_context():
        template = create("pod-high", _VALID_CONTENT)
        original_id = template.id
        original_hash = template.content_hash

        updated = update("pod-high", _ALTERED_CONTENT)

        assert updated.id == original_id
        assert updated.name == "pod-high"
        assert updated.content == {
            "type": "pod8206hr",
            "parameters": {
                "preamp_gain": 10,
                "sample_rate": 2500,
                "lowpass_ch0": 50,
            },
        }
        assert updated.content_hash != original_hash
        assert db.session.scalar(db.select(db.func.count()).select_from(DeviceTemplate)) == 1


def test_delete_returns_references_and_removes_template(app):
    with app.app_context():
        create("pod-high", _VALID_CONTENT)
        repo = SessionRepository()
        referenced = repo.create(
            {"name": "Run A", "device_flows": [{"device_template": "pod-high"}]}
        )

        refs = delete("pod-high")

        assert [session.id for session in refs] == [referenced.id]
        assert get_by_name("pod-high") is None


def test_import_from_export_round_trips_to_same_hash(app):
    with app.app_context():
        original = create("pod-high", _VALID_CONTENT)

        imported = import_config(export(original))

        assert imported.name == "pod-high-2"
        assert imported.content_hash == original.content_hash
        assert imported.content == original.content


def test_import_from_toml_uses_name_and_parameters(app):
    toml_source = """\
name = "pod-toml"
type = "pod8206hr"

[parameters]
preamp_gain = 10
sample_rate = "2000"
"""
    with app.app_context():
        cfg = import_config(toml_source, format="toml")

        assert cfg.name == "pod-toml"
        assert cfg.content == {
            "type": "pod8206hr",
            "parameters": {"preamp_gain": 10, "sample_rate": 2000},
        }


def test_import_can_override_source_name(app):
    with app.app_context():
        cfg = import_config(
            {"name": "from-file", "type": "pod8206hr", "parameters": {"preamp_gain": 10}},
            name="from-ui",
        )

        assert cfg.name == "from-ui"


def test_import_unknown_type_writes_no_row(app):
    with app.app_context():
        with pytest.raises(UnknownConfigType):
            import_config({"name": "bad", "type": "bad_hw", "parameters": {"preamp_gain": 10}})

        count = db.session.scalar(db.select(db.func.count()).select_from(DeviceTemplate))
        assert count == 0


def test_import_bad_parameter_writes_no_row(app):
    with app.app_context():
        with pytest.raises(ValueError, match="unknown"):
            import_config(
                {
                    "name": "bad",
                    "type": "pod8206hr",
                    "parameters": {"preamp_gain": 10, "ttl_port": 3},
                }
            )

        count = db.session.scalar(db.select(db.func.count()).select_from(DeviceTemplate))
        assert count == 0


def test_export_produces_canonical_json_artifact(app):
    with app.app_context():
        cfg = create("pod-high", _VALID_CONTENT)

        exported = export(cfg)

        assert exported == json.dumps(
            {
                "name": "pod-high",
                "parameters": {"preamp_gain": 10, "sample_rate": 2000},
                "type": "pod8206hr",
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def test_export_artifact_formats_config_content_without_persisting():
    result = export_artifact(
        {
            "name": "pod-from-config",
            "type": "pod8206hr",
            "parameters": {"preamp_gain": "10", "sample_rate": "2000"},
        },
        format="toml",
    )

    assert result == (
        'name = "pod-from-config"\n'
        'type = "pod8206hr"\n'
        "\n"
        "[parameters]\n"
        "preamp_gain = 10\n"
        "sample_rate = 2000\n"
    )


def test_clone_creates_new_row_with_same_hash(app):
    with app.app_context():
        source = create("pod-high", _VALID_CONTENT)
        original_hash = source.content_hash
        original_content = dict(source.content)

        cloned = clone(source)

        assert cloned.id != source.id
        assert cloned.name == "pod-high-2"
        assert cloned.content_hash == original_hash
        assert get_by_id(source.id).content == original_content


def test_diff_reports_precise_parameter_changes(app):
    with app.app_context():
        before = create("before", _VALID_CONTENT)
        after = create("after", _ALTERED_CONTENT)

        result = diff(before, after)

        assert result == {
            "equal": False,
            "type": None,
            "parameters": {
                "added": {"lowpass_ch0": 50},
                "removed": {},
                "modified": {"sample_rate": {"old": 2000, "new": 2500}},
            },
        }


def test_diff_identical_content_reports_equal(app):
    with app.app_context():
        first = create("first", _VALID_CONTENT)
        second = create("second", _VALID_CONTENT)

        assert diff(first, second) == {
            "equal": True,
            "type": None,
            "parameters": {"added": {}, "removed": {}, "modified": {}},
        }
