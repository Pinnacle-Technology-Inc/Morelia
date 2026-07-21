"""Hardware-in-the-loop checkpoint tier.

Everything under ``tests/hardware/`` is a SEPARATE, opt-in test tier. It does
NOT run in the fast in-process suite. Its whole purpose is to use the real
system (a real ``python -m app.runtime_host`` subprocess wrapping the real
Morelia watchdog, over real HTTP, into real SQLite) as the *oracle* for
behavior the fast suite can only assume.

Two things live here:

1. Capture (``capture.py``): records the *actual* envelopes a real watchdog
   POSTs northbound, as durable JSONL fixtures. The hardware — not an author,
   human or AI — becomes the source of the test inputs.

2. Replay + assertions (``test_packet3_replay.py``): replays those captured
   fixtures against the ingest path and checks the packet-3 acceptance
   criteria. Because the inputs are recorded reality, a green here means
   "reality agrees with the spec", not "the mock agreed with the code".

Run order at a checkpoint: drive the fault menu (``checkpoint.py``) to produce
fresh captures, then run the replay tests against them.
"""
