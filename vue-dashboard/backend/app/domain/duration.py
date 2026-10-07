from datetime import UTC, datetime, timedelta


PYTHON_DATETIME_MAX = datetime.max.replace(tzinfo=UTC)


def max_duration_seconds(start_at: datetime | None = None) -> int:
    start = start_at if start_at is not None else datetime.now(UTC)
    start = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
    return (PYTHON_DATETIME_MAX - start) // timedelta(seconds=1)


def validate_duration_seconds(value: object, *, start_at: datetime | None = None) -> None:
    if type(value) is not int or value < 1:
        raise ValueError("Duration must be a positive integer.")
    # Whole seconds must fit before Python's maximum datetime, including subsecond starts.
    maximum = max_duration_seconds(start_at)
    if value > maximum:
        raise ValueError(
            f"Duration must be at most {maximum} seconds from the start time. "
            "The deadline cannot exceed Python's datetime maximum (9999-12-31 UTC)."
        )
