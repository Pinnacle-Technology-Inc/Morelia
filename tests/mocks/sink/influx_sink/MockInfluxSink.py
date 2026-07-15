from Morelia.Stream.sink.influx_sink import InfluxSink

from tests.mocks.sink.influx_sink.MockInfluxClient import MockInfluxClient
from tests.mocks.sink.influx_sink.MockWriteAPI import MockWriteAPI

class MockInfluxSink(InfluxSink):
    """
    InfluxSink test implementation that records flushed packets for verification
    instead of writing them to an InfluxDB server.
    """

    def __init__(self, pod, shared_records, **kwargs):
        self.shared_records = shared_records
        super().__init__(pod, **kwargs)

        print(
            "MockInfluxSink init",
            id(self.shared_records),
            type(self.shared_records),
            flush=True,
        )

    def __enter__(self):
        self._client = MockInfluxClient()
        self._writer = MockWriteAPI()

        self._writer.write(
            bucket=self.bucket,
            org=self.org,
            record=self._data,
        )

        return self
    
    def flush(self, timestamp, packet):
        self.shared_records.append((timestamp, packet))
        super().flush(timestamp, packet)

    def __exit__(self, *args, **kwargs):
        self._writer.close()
        self._client.close()
        del self._writer
        del self._client
        return False
    
    def get_dict(self):
        d = super().get_dict()
        d["shared_records"] = self.shared_records
        return d