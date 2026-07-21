"""The runtime layer: drivers that turn a manifest into running data collection.

The Dataflow Runtime Host (Stage 2.2) depends only on the RuntimeControlDriver
*interface* defined here — never on a concrete class — so the driver
implementation (MoreliaRuntime) can be swapped without touching the host.
"""
