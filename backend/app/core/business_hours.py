from datetime import datetime

from backend.app.core.time import as_utc, market_timezone


def is_business_open_at(hours_by_weekday: dict[int, object], now: datetime, market_code: str | None = None) -> bool:
    """Open interval is [opens_at, closes_at); absent schedule means closed."""
    local_now = as_utc(now).astimezone(market_timezone(market_code=market_code))
    day = hours_by_weekday.get(local_now.weekday())
    if day is None or day.is_closed or day.opens_at is None or day.closes_at is None:
        return False
    local_time = local_now.timetz().replace(tzinfo=None)
    return day.opens_at <= local_time < day.closes_at
