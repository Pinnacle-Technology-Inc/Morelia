# Morelia Watchdog

`Morelia.Watchdog` monitors Morelia DataFlow streams and standalone devices.
It can detect stalled streams, report health information, reconnect hardware,
and rebuild failed DataFlow workers.

## Import

Import the high-level `Watchdog` class with:

```python
from Morelia.Watchdog.watchdog import Watchdog
```

Most applications should use `Watchdog` rather than constructing
`DataFlowMonitor`, `HardwareMonitor`, or `HealthSink` directly.

## Components

| Component | Purpose |
| --- | --- |
| `Watchdog` | Public lifecycle, watcher threads, callbacks, and reports. |
| `DataFlowMonitor` | Injects stream heartbeats and rebuilds DataFlow workers. |
| `HardwareMonitor` | Pings, resets, and rebuilds serial device objects. |
| `HealthSink` | Records sample activity inside each DataFlow worker. |

## Required Lifecycle

For a DataFlow, use this order:

1. Create the devices, sinks, and `DataFlow`.
2. Construct `Watchdog`.
3. Call `watchdog.preflight()`.
4. Call `flowgraph.collect()`.
5. Call `watchdog.run()`.
6. Call `watchdog.close()` in a `finally` block.

Construct `Watchdog` before calling `flowgraph.collect()`. Construction adds a
`HealthSink` to every stream, and the worker must be created with that sink.

Call `preflight()` before `flowgraph.collect()`. Once collection starts, the
worker processes own the serial ports and preflight raises `RuntimeError`.

`run()` is blocking. It returns only after `stop()` is called, usually from
another thread, a timer, or interrupt handling. `stop()` only stops the watcher
loops. Always finish with `close()` to release DataFlow resources.

On Windows, put device construction and all multiprocessing work behind:

```python
if __name__ == "__main__":
    main()
```

## Stream-Only Example

This example watches one 8206HR stream for 60 seconds.

```python
import threading
from pprint import pprint

from Morelia.Devices import Pod8206HR
from Morelia.Stream.data_flow import DataFlow
from Morelia.Stream.sink import CSVSink
from Morelia.Watchdog.watchdog import Watchdog


def main():
    pod = Pod8206HR("COM4", 10)
    pod.sample_rate = 2000

    sink = CSVSink(file_path="stream_8206.csv", pod=pod)
    flowgraph = DataFlow([(pod, [sink])])

    # Watchdog must be constructed before flowgraph.collect().
    watchdog = Watchdog(
        flowgraph=flowgraph,
        failure_threshold=3,
        max_heartbeat_age_sec=10.0,
    )

    stop_timer = None
    try:
        pprint(watchdog.preflight(timeout_sec=5.0), sort_dicts=False)
        flowgraph.collect()

        stop_timer = threading.Timer(60.0, watchdog.stop)
        stop_timer.daemon = True
        stop_timer.start()

        watchdog.run(
            report_interval_sec=5.0,
            stream_interval=2.0,
            timeout_sec=5.0,
            on_result=lambda report: pprint(report, sort_dicts=False),
            verbose=False,
        )
    except KeyboardInterrupt:
        pass
    finally:
        if stop_timer is not None:
            stop_timer.cancel()
        watchdog.close()


if __name__ == "__main__":
    main()
```

`HealthSink` is added automatically. Do not add one manually unless you are
building a lower-level integration around `DataFlowMonitor`.

## Standalone Device Example

A standalone device is monitored without placing it in a DataFlow:

```python
import threading
from pprint import pprint

from Morelia.Devices import Pod8206HR
from Morelia.Watchdog.watchdog import Watchdog


def main():
    pod = Pod8206HR("COM5", 10)
    pod.sample_rate = 2000

    watchdog = Watchdog(
        devices=[pod],
        failure_threshold=3,
    )

    stop_timer = threading.Timer(60.0, watchdog.stop)
    stop_timer.daemon = True

    try:
        pprint(watchdog.preflight(timeout_sec=5.0), sort_dicts=False)
        stop_timer.start()
        watchdog.run(
            report_interval_sec=5.0,
            device_interval=2.0,
            timeout_sec=5.0,
            on_result=lambda report: pprint(report, sort_dicts=False),
        )
    except KeyboardInterrupt:
        pass
    finally:
        stop_timer.cancel()
        watchdog.close()
        try:
            pod.close_port()
        except Exception:
            pass


if __name__ == "__main__":
    main()
```

Standalone monitoring sends a `PING` on every device interval. If the PING
fails, it closes and rebuilds the device immediately, then verifies the new
object with another PING. A failure is counted only when both the original PING
and reconnect attempt fail.

Finalize device configuration before `run()`. The reconnect recipe is captured
from `device.get_dict()` when the device watcher starts.

## Mixed Stream and Device Monitoring

Pass a DataFlow and a list of hardware-only devices to the same `Watchdog`:

```python
watchdog = Watchdog(
    flowgraph=flowgraph,
    devices=[hardware_only_pod],
    failure_threshold=3,
    max_heartbeat_age_sec=10.0,
)

try:
    watchdog.preflight(timeout_sec=5.0)
    flowgraph.collect()
    watchdog.run(
        report_interval_sec=5.0,
        stream_interval=2.0,
        device_interval=2.0,
        timeout_sec=5.0,
        on_result=handle_report,
    )
finally:
    watchdog.close()
```

If a device in `devices` uses the same port as a DataFlow source, it is removed
from the standalone list because the stream watcher already monitors it.

## Constructor

```python
Watchdog(
    flowgraph=None,
    devices=(),
    failure_threshold=3,
    max_heartbeat_age_sec=2.0,
)
```

### `flowgraph`

A configured `DataFlow`. Collection must not have started when `Watchdog` is
constructed.

### `devices`

Standalone device objects that are not part of the DataFlow. At least one of
`flowgraph` or `devices` is required.

### `failure_threshold`

The number of consecutive failed checks before a stale or never-started stream
is stopped for recovery. A dead or missing worker is stopped immediately.

For standalone devices, it counts checks where both PING and reconnect fail.

### `max_heartbeat_age_sec`

The maximum permitted age of the last sample heartbeat. A worker can be alive
while its heartbeat is stale.

## Preflight

```python
result = watchdog.preflight(
    attempts=3,
    timeout_sec=5.0,
    require_ready=True,
)
```

Preflight stops leftover streaming, drains stale packets, and verifies each
device with `GET SAMPLE RATE`.

With `require_ready=True`, it raises `RuntimeError` when any device is not
ready. Use `require_ready=False` to receive diagnostic results without raising.

Example result:

```python
{
    "ok": True,
    "devices": {
        "COM4": {
            "ok": True,
            "attempts_used": 1,
            "reset": {
                "ok": True,
                "drained_packets": 0,
                "device_quiet": True,
            },
        },
    },
}
```

## Running the Watchdog

```python
watchdog.run(
    report_interval_sec=30.0,
    stream_interval=30.0,
    device_interval=30.0,
    timeout_sec=10.0,
    on_result=None,
    on_stream_result=None,
    on_device_result=None,
    verbose=False,
)
```

| Argument | Purpose |
| --- | --- |
| `report_interval_sec` | Frequency of combined reports passed to `on_result`. |
| `stream_interval` | Frequency of each stream health check. |
| `device_interval` | Frequency of each standalone device check. |
| `timeout_sec` | Timeout for device commands and restart verification. |
| `on_result` | Callback for combined Watchdog reports. |
| `on_stream_result` | Callback for individual stream reports. |
| `on_device_result` | Callback for individual standalone device reports. |
| `verbose` | Selects compact or verbose streams in combined reports. |

Intervals may be a shared number or a dictionary of per-item values. Stream
keys are integer stream indexes. Standalone device keys are normally ports:

```python
watchdog.run(
    stream_interval={0: 1.0, 1: 5.0},
    device_interval={"COM5": 2.0},
    timeout_sec=5.0,
)
```

## Callbacks

The callback signatures are:

```python
def on_result(report):
    ...


def on_stream_result(stream_index, report):
    ...


def on_device_result(device_key, report):
    ...
```

`on_stream_result` always receives a verbose stream report. The `verbose`
argument only changes the stream entries in combined reports.

Example:

```python
def handle_stream(stream_index, report):
    if report["stream_health"] != "healthy":
        print(stream_index, report["summary"])


def handle_device(device_key, report):
    if report["status"] != "connected":
        print(device_key, report)


watchdog.run(
    stream_interval=2.0,
    device_interval=2.0,
    timeout_sec=5.0,
    on_stream_result=handle_stream,
    on_device_result=handle_device,
)
```

Exceptions raised by callbacks are ignored so a user callback cannot terminate
a watcher thread. Handle and log callback errors inside the callback when they
matter to the application.

## Reports

`get_report()` and `on_result` return a combined report:

```python
{
    "watchdog_status": "ok",
    "checked_at": 12.4,
    "streams": [
        {
            "stream_index": 0,
            "port": "COM4",
            "port_owner": "worker",
            "stream_health": "healthy",
            "worker_status": "alive",
            "heartbeat": "fresh",
            "failure_count": 0,
            "action": "none",
            "reason": "ok",
        },
    ],
    "devices": {
        "COM5": {
            "status": "connected",
            "consecutive_failures": 0,
            "last_error": None,
            "checked_at": 11.9,
        },
    },
}
```

Aggregate `watchdog_status` values:

| Value | Meaning |
| --- | --- |
| `ok` | Every stream and device is healthy. |
| `degraded` | At least one item is suspect, or health states are mixed. |
| `failed` | Every monitored item is unhealthy. |
| `unknown` | No health result is available yet. |

Stream `stream_health` values are `healthy`, `suspect`, and `unhealthy`.
Recovery attempts are normally `suspect` while the watcher waits for the port
or rebuilds the worker.

With `verbose=True`, stream reports also include:

- source and sink class names,
- the health rule and human-readable summary,
- port and port owner,
- worker status, PID, and exit code,
- heartbeat age, packet count, and age limit,
- failure count and threshold, and
- recovery action details.

`checked_at` and stream `last_data_at` are seconds relative to the time the
watchdog module was imported, not Unix timestamps.

## Stream Recovery

Each stream watcher checks:

- whether its worker process is alive, and
- whether samples are producing a fresh `HealthSink` heartbeat.

A dead or missing worker is stopped immediately. A stale heartbeat or a stream
that never produced data is allowed to fail up to `failure_threshold` checks.

After escalation, the watcher:

1. Stops the affected worker.
2. Waits for its serial port to be present and openable.
3. Rebuilds the source and sinks from saved configuration.
4. Starts only that stream.
5. Verifies the new worker with a PING through the DataFlow queue.

Recovery retries continue until the stream reconnects or the watchdog stops.

Every source and sink must support Morelia reconstruction:

- `get_dict()` must return valid constructor keyword arguments.
- The class must be constructible with those arguments.
- A sink must accept the stream source through its `pod` argument.

This is especially important for custom sinks.

## Stopping and Cleanup

### `watchdog.stop()`

Stops watcher loops and causes a blocking `run()` call to return. It does not
stop DataFlow workers or shut down multiprocessing resources.

### `watchdog.close()`

Calls `stop()`, stops watched DataFlow workers, shuts down the shared heartbeat
manager, and runs source cleanup. It is safe to call repeatedly.

Always use `close()` in a `finally` block. Once the watchdog has managed a
stream, prefer `watchdog.close()` over calling `flowgraph.stop_collection()`
later because the watchdog may have replaced a stopped worker slot with `None`.

Applications should also close standalone device objects that they own after
the watchdog stops.

## Common Problems

### `preflight() must run before flowgraph.collect()`

Move the preflight call before collection starts.

### The worker is alive but the stream is unhealthy

Worker liveness and sample flow are separate signals. Inspect heartbeat
`status`, `age_sec`, and `packet_count` in a verbose report.

### `run()` never returns

This is expected until another thread calls `watchdog.stop()` or interrupt
handling enters the `finally` block.

### Restart fails for a custom source or sink

Verify that `get_dict()` matches the class constructor and that custom sinks
accept `pod`.

### Windows starts the program more than once

Put device construction, `DataFlow` creation, collection, and Watchdog startup
inside `if __name__ == "__main__":`.

## Lower-Level Hardware Monitoring

`HardwareMonitor` can be used directly for synchronous device checks without
watcher threads:

```python
from Morelia.Watchdog.hardwareMonitor import HardwareMonitor

monitor = HardwareMonitor(failure_threshold=3)
monitor.watch(pod)
states = monitor.poll_device_health_once(timeout_sec=5.0)
```

`DataFlowMonitor` and `HealthSink` are implementation-level APIs. They depend
on DataFlow worker slots, stop events, queues, and reconstruction metadata.
Prefer `Watchdog` unless implementing custom monitoring or recovery behavior.
