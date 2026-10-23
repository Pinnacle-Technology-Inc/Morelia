"""Standalone, enumeration-only FTDI diagnostic; see diagnose_ftdi.md.

No Flask startup, device opens, resets, stream commands, or database writes.
Exit codes: 0 = requested serials unique, 1 = absent/ambiguous in any sample,
2 = incomplete inventory/configuration error, 130 = interrupted.
This samples a separate process; it cannot capture a worker's exact failing call.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_DATABASE = Path(__file__).resolve().parents[1] / "instance/guarded-experiment.sqlite3"


def session_selectors(database: Path, session_id: int) -> list[str]:
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT content FROM runtime_manifests WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError(f"Session {session_id} has no persisted runtime manifest")
    serials = []
    for flow in json.loads(row[0])["device_flows"]:
        binding = flow.get("connection") or {}
        if binding.get("transport") == "d2xx":
            serials.append(binding["address"])
    if not serials:
        raise ValueError(f"Session {session_id} has no native D2XX bindings")
    return serials


def decode(value):
    return value.decode("utf-8", errors="backslashreplace") if isinstance(value, bytes) else value


def snapshot(ftd, selectors: list[str], sample: int) -> dict:
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "pid": os.getpid(),
        "sample": sample,
        "requested_serials": selectors,
        "native": [],
        "errors": [],
    }
    try:
        count = ftd.createDeviceInfoList()
        result["native_count"] = count
        for index in range(count):
            try:
                info = ftd.getDeviceInfoDetail(index, update=False)
                flags = info.get("flags")
                serial = info.get("serial")
                result["native"].append(
                    {
                        "index": index,
                        "serial": decode(serial),
                        "serial_raw": repr(serial),
                        "serial_hex": serial.hex() if isinstance(serial, bytes) else None,
                        "description": decode(info.get("description")),
                        "flags": flags,
                        "reported_open": bool(flags & 1) if isinstance(flags, int) else None,
                        "type": info.get("type"),
                        "id": info.get("id"),
                        "location": info.get("location", info.get("locid")),
                    }
                )
            except Exception as exc:
                result["errors"].append(f"native index {index}: {type(exc).__name__}: {exc}")
    except Exception as exc:
        result["errors"].append(f"native enumeration: {type(exc).__name__}: {exc}")
    native_complete = not result["errors"]
    result["native_complete"] = native_complete
    counts = Counter(row["serial"] for row in result["native"])
    result["duplicate_serials"] = {serial: n for serial, n in counts.items() if n > 1}
    result["matches"] = [
        {
            "requested_serial": serial,
            "exact_match_count": counts[serial],
            "result": "unknown"
            if not native_complete
            else (
                "absent"
                if counts[serial] == 0
                else "unique"
                if counts[serial] == 1
                else "ambiguous"
            ),
        }
        for serial in selectors
    ]
    try:
        from serial.tools.list_ports import comports

        result["vcp"] = [
            {"port": p.device, "serial": p.serial_number, "vid": p.vid, "pid": p.pid}
            for p in comports()
        ]
    except Exception as exc:
        result["errors"].append(f"VCP enumeration: {type(exc).__name__}: {exc}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--serial", action="append", default=[], help="Exact native serial; repeatable"
    )
    parser.add_argument(
        "--session", type=int, help="Read native selectors from this session's manifest"
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument(
        "--count", type=int, default=1, help="Snapshots to take; 0 runs until Ctrl+C"
    )
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between snapshots")
    parser.add_argument("--log", type=Path, help="Append each snapshot to this JSONL file")
    args = parser.parse_args()
    if args.count < 0 or not math.isfinite(args.interval) or args.interval <= 0:
        parser.error("--count must be >= 0 and --interval must be positive and finite")
    if any(not value or value != value.strip() for value in args.serial):
        parser.error("--serial must be nonempty with no surrounding whitespace")

    log = None
    try:
        import ftd2xx

        selectors = list(args.serial)
        if args.session is not None:
            selectors.extend(session_selectors(args.database, args.session))
        selectors = list(dict.fromkeys(selectors))
        if args.log:
            log = args.log.open("a", encoding="utf-8")
        print(f"Python: {sys.executable}\nFTDI wrapper: {ftd2xx.__file__}", flush=True)
        print(
            "Enumeration only. A unique match does not prove the device can be opened.", flush=True
        )
        sample, exit_code = 0, 0
        while args.count == 0 or sample < args.count:
            sample += 1
            result = snapshot(ftd2xx, selectors, sample)
            print(json.dumps(result, indent=2, ensure_ascii=True), flush=True)
            if log:
                log.write(json.dumps(result, ensure_ascii=True) + "\n")
                log.flush()
            if result["errors"]:
                exit_code = 2
            elif result["duplicate_serials"] or any(
                match["result"] != "unique" for match in result["matches"]
            ):
                exit_code = max(exit_code, 1)
            if args.count == 0 or sample < args.count:
                time.sleep(args.interval)
        return exit_code
    except KeyboardInterrupt:
        print("Diagnostic stopped.", flush=True)
        return 130
    except Exception as exc:
        print(f"Diagnostic error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 2
    finally:
        if log is not None:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
