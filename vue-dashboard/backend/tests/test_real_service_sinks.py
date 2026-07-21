"""Opt-in smoke gates against disposable/locally managed InfluxDB and QuestDB.

Set ``PINNACLE_REAL_SINK_INTEGRATION=1`` plus the documented service variables.
Ordinary CI remains hermetic; this module exists so release evidence cannot
silently substitute fake transports for acknowledged destination behavior.
"""

from __future__ import annotations

import json
import os
import time
import uuid

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("PINNACLE_REAL_SINK_INTEGRATION") != "1",
    reason="set PINNACLE_REAL_SINK_INTEGRATION=1 to run live service gates",
)


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} is required for live service integration")
    return value


def test_real_influx_acknowledges_and_deduplicates_logical_point():
    from app.output.influx_sink import _RealInfluxClient

    marker = uuid.uuid4().hex
    measurement = f"pinnacle_gate_{marker}"
    timestamp = time.time_ns()
    client = _RealInfluxClient(
        url=_required("PINNACLE_TEST_INFLUX_URL"),
        token=_required("PINNACLE_TEST_INFLUX_TOKEN"),
        org=_required("PINNACLE_TEST_INFLUX_ORG"),
        bucket=_required("PINNACLE_TEST_INFLUX_BUCKET"),
    )
    try:
        assert client.ready() is True
        payload = (
            f"{measurement},acquisition_id={marker},sink_id=gate,channel=ch0 "
            f"value=1.0 {timestamp}"
        ).encode()
        client.write(payload)
        client.write(payload)
        tables = client._client.query_api().query(
            'from(bucket: "' + client._bucket + '")'
            ' |> range(start: -5m)'
            f' |> filter(fn: (r) => r._measurement == "{measurement}")'
            ' |> count()'
        )
        assert sum(len(table.records) for table in tables) == 1
        assert tables[0].records[0].get_value() == 1
    finally:
        client.close()


def test_real_quest_acknowledges_and_deduplicates_logical_row():
    from app.output.quest_sink import _RealQuestClient

    marker = uuid.uuid4().hex
    table = f"pinnacle_gate_{marker}"
    client = _RealQuestClient(
        host=os.environ.get("PINNACLE_TEST_QUEST_HOST", "127.0.0.1"),
        port=int(os.environ.get("PINNACLE_TEST_QUEST_PORT", "9000")),
    )
    try:
        assert client.ready() is True
        client.validate_schema(table)
        payload = json.dumps(
            [
                {
                    "table": table,
                    "symbols": {
                        "acquisition_id": marker,
                        "sink_id": "gate",
                        "channel": "ch0",
                        "name": "ch0",
                    },
                    "value": 1.0,
                    "timestamp": time.time_ns(),
                }
            ]
        ).encode()
        client.write(payload)
        client.write(payload)
        rows = client._exec(
            f"SELECT count() FROM {table} WHERE acquisition_id = '{marker}'"
        )
        assert rows == [[1]]
    finally:
        client.close()
