from Morelia.Stream.sink.sink_interface import SinkInterface
from Morelia.Stream.sink.influx_sink import InfluxSink
from Morelia.Stream.sink.csv_sink import CSVSink
from Morelia.Stream.sink.edf_sink import EDFSink
from Morelia.Stream.sink.pvfs_sink import PvfsSink
from Morelia.Stream.sink.quest_sink import QuestSink
from Morelia.Stream.sink.buffer_sink import BufferSink
from Morelia.Stream.sink.udp_sink import UDPSink
from Morelia.Stream.sink.osc_sink import OSCSink


def __getattr__(name: str):
    """Lazy import for PlotSink/PlotDisplay so Qt is only loaded when needed."""
    if name in ("PlotSink", "PlotDisplay"):
        from Morelia.Stream.sink.plot_sink import PlotSink, PlotDisplay
        globals()["PlotSink"] = PlotSink
        globals()["PlotDisplay"] = PlotDisplay
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
