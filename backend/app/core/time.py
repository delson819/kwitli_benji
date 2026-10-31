from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.app.core.config import get_settings


MARKET_TIMEZONES = {
    "SN": "Africa/Dakar",
    "CI": "Africa/Abidjan",
    "BJ": "Africa/Porto-Novo",
    "TG": "Africa/Lome",
    "CM": "Africa/Douala",
    "GN": "Africa/Conakry",
    "CA": "America/Toronto",
    "CO": "America/Bogota",
}


def _valid_timezone(value: str | None) -> ZoneInfo | None:
    if not value:
        return None
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def market_timezone(
    business_timezone: str | None = None,
    market_code: str | None = None,
) -> ZoneInfo:
    """Resolve operational time by business, market, configured fallback, then UTC."""
    settings = get_settings()
    for candidate in (
        business_timezone,
        MARKET_TIMEZONES.get((market_code or settings.launch_country).strip().upper()),
        settings.market_timezone,
        "UTC",
    ):
        resolved = _valid_timezone(candidate)
        if resolved is not None:
            return resolved
    return ZoneInfo("UTC")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def market_today(
    business_timezone: str | None = None,
    market_code: str | None = None,
) -> date:
    return utc_now().astimezone(market_timezone(business_timezone, market_code)).date()


def market_datetime_as_utc(
    day: date,
    local_time: time,
    business_timezone: str | None = None,
    market_code: str | None = None,
) -> datetime:
    local = datetime.combine(day, local_time, tzinfo=market_timezone(business_timezone, market_code))
    return local.astimezone(timezone.utc)
