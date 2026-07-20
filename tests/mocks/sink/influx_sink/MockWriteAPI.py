class MockWriteAPI:
    """
    Minimal WriteApi used to satisfy InfluxSink during testing.
    """

    def write(self, bucket, org, record):
        pass

    def close(self):
        pass