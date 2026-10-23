"""Real HTTP API, DB, process supervisor and watchdog; fixture setup only."""
import json
import os
from pathlib import Path

def main():
    from app import create_app
    from app.database import db
    from app.domain.enums import DeviceType
    from app.models.device_config import DeviceConfig
    from app.services import device_templates, session_templates
    from werkzeug.serving import run_simple
    root = Path(os.environ["TIMED_SERIAL_HARNESS"])
    app = create_app("development")
    if (root / "fixture.json").exists():
        serve(app)
        return
    with app.app_context():
        db.create_all()
        template = device_templates.create("fixture", {"type": "pod8206hr", "parameters": {"preamp_gain": 10, "sample_rate": 100}})
        flows, assignments = [], []
        for index in range(int(os.environ.get("TIMED_FIXTURE_DEVICES", "1"))):
            suffix = f"-{index}" if index else ""
            config = DeviceConfig(device_type=DeviceType.POD8206HR, hardware_id="INDEPENDENT-TIMED-8206" + suffix, port=f"COM{int(os.environ.get('TIMED_SERIAL_PORT_BASE', '991')) + index}", parameters=template.content["parameters"], connection={}, source_template=template.file_path, source_template_hash=template.content_hash)
            db.session.add(config)
            db.session.commit()
            flows.append({"device_template_path": template.file_path, "sinks": [{"sink_type": "csv", "sink_name": f"csv-{sink}", "sink_parameters": {}} for sink in range(int(os.environ.get("TIMED_FIXTURE_SINKS", "1")))]})
            assignments.append({"flow_index": index, "device_config_id": config.id, "sink_locations": [{"sink_index": sink, "sink_location": str(root / (f"recorded{suffix}" + (f"-sink{sink}" if sink else "") + ".csv"))} for sink in range(int(os.environ.get("TIMED_FIXTURE_SINKS", "1")))]})
        run = session_templates.create("Independent timed", {"policy": os.environ.get("TIMED_FIXTURE_POLICY", "recommend"), "device_flows": flows})
        (root / "fixture.json").write_text(json.dumps({"source_template_id": run.template_id, "expected_template_hash": run.content_hash, "assignments": assignments}))
    serve(app)

def serve(app):
    from app.cli.lifecycle import _start_finalizer_process, _start_scheduled_run_coordinator
    from werkzeug.serving import run_simple
    _start_finalizer_process(app)
    _start_scheduled_run_coordinator(app)
    run_simple("127.0.0.1", int(os.environ["TIMED_API_PORT"]), app, threaded=True, use_reloader=False)

if __name__ == "__main__":
    main()
