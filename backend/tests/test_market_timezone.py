from datetime import date, datetime, time, timezone

import pytest


@pytest.fixture
def settings_factory(monkeypatch):
    from backend.app.core.config import Settings
    from backend.app.core import time as time_module

    def configure(**values):
        settings = Settings(app_env="test", **values)
        monkeypatch.setattr(time_module, "get_settings", lambda: settings)
        return settings

    return configure


def test_senegal_market_uses_dakar_and_local_availability_maps_to_utc(settings_factory):
    from backend.app.core.time import market_datetime_as_utc, market_timezone, market_today

    settings_factory(launch_country="SN", market_timezone="UTC")
    assert market_timezone().key == "Africa/Dakar"
    assert market_datetime_as_utc(date(2026, 1, 15), time(12)) == datetime(
        2026, 1, 15, 12, tzinfo=timezone.utc
    )
    assert market_today() == datetime.now(timezone.utc).date()


@pytest.mark.parametrize(
    ("country", "expected"),
    [("CI", "Africa/Abidjan"), ("BJ", "Africa/Porto-Novo"), ("TG", "Africa/Lome"),
     ("CM", "Africa/Douala"), ("GN", "Africa/Conakry"), ("CA", "America/Toronto")],
)
def test_market_registry_resolves_market_timezone(settings_factory, country, expected):
    from backend.app.core.time import market_timezone

    settings_factory(launch_country=country, market_timezone="UTC")
    assert market_timezone().key == expected


def test_business_timezone_precedes_market_timezone(settings_factory):
    from backend.app.core.time import market_timezone

    settings_factory(launch_country="SN", market_timezone="UTC")
    assert market_timezone(business_timezone="America/Toronto").key == "America/Toronto"


def test_business_timezone_is_used_for_availability_conversion(settings_factory):
    from backend.app.core.time import market_datetime_as_utc

    settings_factory(launch_country="SN", market_timezone="UTC")
    assert market_datetime_as_utc(
        date(2026, 1, 15), time(12), business_timezone="America/Toronto"
    ) == datetime(2026, 1, 15, 17, tzinfo=timezone.utc)


def test_market_today_uses_local_date_at_midnight_boundary(settings_factory, monkeypatch):
    from backend.app.core import time as time_module

    settings_factory(launch_country="CA", market_timezone="UTC")
    monkeypatch.setattr(
        time_module,
        "utc_now",
        lambda: datetime(2026, 1, 15, 2, 30, tzinfo=timezone.utc),
    )
    assert time_module.market_today().isoformat() == "2026-01-14"


def test_configured_timezone_is_fallback_for_unknown_market(settings_factory):
    from backend.app.core.time import market_timezone

    settings_factory(launch_country="XX", market_timezone="America/Bogota")
    assert market_timezone().key == "America/Bogota"


def test_invalid_timezones_fall_back_to_utc_and_colombia_is_explicit(settings_factory):
    from backend.app.core.time import market_timezone

    settings_factory(launch_country="XX", market_timezone="not/a-zone")
    assert market_timezone(business_timezone="also/not-a-zone").key == "UTC"
    settings_factory(launch_country="CO", market_timezone="UTC")
    assert market_timezone().key == "America/Bogota"
