from datetime import UTC, datetime, timedelta


def to_iso(moment: datetime) -> str:
    """ISO 8601 UTC with milliseconds, as stored (Processing Appendix: Schema)."""
    moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def now_iso(offset_seconds: float = 0.0) -> str:
    return to_iso(datetime.now(UTC) + timedelta(seconds=offset_seconds))


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
