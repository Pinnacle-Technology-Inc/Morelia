class InvalidChecksumError(Exception):
    """Raised when a POD packet has an invalid checksum."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
