"""Read child startup output without blocking the supervising process."""

from collections.abc import Iterator
from contextlib import contextmanager
from queue import Empty, Full, Queue
from threading import Event, Thread
from time import monotonic
from typing import TextIO


@contextmanager
def startup_output(stream: TextIO, *, deadline: float) -> Iterator[Iterator[str]]:
    """Yield startup lines until EOF or an absolute monotonic deadline."""
    messages: Queue[tuple[str | None, Exception | None]] = Queue(maxsize=64)
    finished = Event()

    def publish(line: str | None, error: Exception | None = None) -> None:
        while not finished.is_set():
            try:
                messages.put((line, error), timeout=0.05)
                return
            except Full:
                continue

    def read() -> None:
        try:
            for line in stream:
                publish(line)
        except Exception as exc:
            publish(None, exc)
        finally:
            publish(None)
            stream.close()

    def lines() -> Iterator[str]:
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("Runtime startup deadline exceeded")
            try:
                line, error = messages.get(timeout=remaining)
            except Empty:
                raise TimeoutError("Runtime startup deadline exceeded") from None
            if error is not None:
                raise error
            if line is None:
                return
            yield line

    # A stuck driver or descendant may keep stdout open after its parent exits.
    # Keep pipe reads off the request thread and drain output after readiness.
    Thread(target=read, name="runtime-startup-output", daemon=True).start()
    try:
        yield lines()
    finally:
        finished.set()
