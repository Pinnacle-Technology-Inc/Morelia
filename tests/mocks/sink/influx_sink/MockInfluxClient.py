class MockInfluxClient:
    """Minimal InfluxDB client used to avoid creating a real database connection."""

    def close(self):
        pass