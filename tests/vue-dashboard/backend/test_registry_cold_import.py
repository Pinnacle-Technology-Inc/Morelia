import json
import os
from pathlib import Path
import subprocess
import sys


COLD_REGISTRY_PROGRAM = r'''
import json
import sys
import threading
import traceback
from app.services import registry

assert not any(name == "Morelia" or name.startswith("Morelia.") for name in sys.modules), "process was not cold"
package_paused = threading.Event()
second_leaf_locked = threading.Event()
results = {}
errors = {}
trace_evidence = {"package_paused": False, "second_leaf_locked": False, "constructors": []}

def trace(frame, event, arg):
    name = threading.current_thread().name
    filename = frame.f_code.co_filename.replace("\\", "/")
    if event == "call":
        if frame.f_code.co_name == "__init__" and ("/Devices/PodDevice_" in filename or "/Stream/sink/" in filename):
            trace_evidence["constructors"].append(filename)
            raise AssertionError("catalog schema lookup ran a provider constructor")
        if name == "catalog-second" and frame.f_code.co_name == "_find_and_load_unlocked" and frame.f_locals.get("name") == "Morelia.Devices.PodDevice_8401HR":
            trace_evidence["second_leaf_locked"] = True
            second_leaf_locked.set()
    if event == "line" and name == "catalog-first" and filename.endswith("/Morelia/Devices/__init__.py") and not package_paused.is_set():
        trace_evidence["package_paused"] = True
        package_paused.set()
        second_leaf_locked.wait(1.0)
    return trace

def lookup(label, device):
    try:
        results[label] = registry.device_parameter_schema(device)
    except BaseException:
        errors[label] = traceback.format_exc()

threading.settrace(trace)
first = threading.Thread(target=lookup, args=("first", "pod8206hr"), name="catalog-first", daemon=True)
second = threading.Thread(target=lookup, args=("second", "pod8401hr"), name="catalog-second", daemon=True)
first.start()
assert package_paused.wait(15), "did not reach package initialization scheduling point"
second.start()
first.join(15)
second.join(15)
threading.settrace(None)
assert not first.is_alive() and not second.is_alive(), "cold catalog lookup deadlocked"

validation = {}
if not errors:
    validation["valid"] = registry.lookup_device("pod8206hr", {"preamp_gain": "10", "sample_rate": "2000"}).as_dict()
    for label, parameters in {
        "bad_value": {"preamp_gain":42},
        "unknown_parameter": {"preamp_gain":10, "unsupported_setting":1},
        "missing_parameter": {},
    }.items():
        try:
            registry.lookup_device("pod8206hr", parameters)
        except ValueError as error:
            validation[label] = str(error)
        else:
            errors[label] = "invalid parameters unexpectedly accepted"

print(json.dumps({"results":results,"errors":errors,"trace":trace_evidence,"validation":validation}))
'''


def test_concurrent_cold_registry_schema_import_preserves_validation(tmp_path):
    root = Path(__file__).resolve().parents[3]
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join([str(root / "src"), str(root / "vue-dashboard/backend")])
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run([sys.executable, "-c", COLD_REGISTRY_PROGRAM], cwd=root,
                               env=environment, capture_output=True, text=True, timeout=40)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    (tmp_path / "cold-import-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    assert result["trace"]["package_paused"] is True
    assert result["trace"]["constructors"] == []
    assert result["errors"] == {}, result["errors"]
    assert set(result["results"]) == {"first", "second"}
    assert "preamp_gain" in result["results"]["first"]["required"]
    assert "sample_rate" in result["results"]["second"]["optional"]
    assert result["validation"]["valid"] == {"preamp_gain":10, "sample_rate":2000}
    assert "preamp_gain" in result["validation"]["bad_value"]
    assert "unknown" in result["validation"]["unknown_parameter"]
    assert "missing" in result["validation"]["missing_parameter"]
