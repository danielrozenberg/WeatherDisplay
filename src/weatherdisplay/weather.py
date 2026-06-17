"""Open-Meteo weather fetching and parsing.

A single HTTP request to the Open-Meteo forecast API returns current conditions,
the hourly series (for the bar chart) and the daily series (for the day chips).
The network call (`fetch`) and the pure parsing (`parse`) are kept separate so
parsing can be unit-tested against saved JSON fixtures.

Temperatures are requested in Celsius and Fahrenheit is derived locally, so both
units are always available regardless of the configured primary unit.
"""

from __future__ import annotations

import dataclasses
import datetime
from typing import NotRequired, TypedDict

import requests
import requests_cache
import retry_requests

from . import config as config_lib
from . import errors
from . import wmo

API_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo's forecast horizon cap (days).
_MAX_FORECAST_DAYS = 16

_CURRENT_VARS = (
    "temperature_2m,relative_humidity_2m,weather_code,uv_index,is_day"
)
_HOURLY_VARS = "temperature_2m,precipitation_probability"
_DAILY_VARS = (
    "weather_code,temperature_2m_max,temperature_2m_min,"
    "precipitation_probability_max,sunrise,sunset,uv_index_max"
)


# The decoded JSON shape. These TypedDicts mirror exactly the variables
# requested via the `*_VARS` strings above (plus the `time` arrays), so the
# payload stops being an untyped `Any` the moment it enters `parse` — that is
# the single trust boundary where the external data is asserted to match.
class CurrentBlock(TypedDict):
    """The `current` block: instantaneous conditions."""

    temperature_2m: float
    relative_humidity_2m: float
    weather_code: int
    is_day: int
    uv_index: NotRequired[float]


class HourlyBlock(TypedDict):
    """The `hourly` block: parallel arrays driving the chart."""

    time: list[str]
    temperature_2m: list[float]
    precipitation_probability: list[int | None]


class DailyBlock(TypedDict):
    """The `daily` block: parallel arrays driving the day chips."""

    time: list[str]
    weather_code: list[int]
    temperature_2m_max: list[float]
    temperature_2m_min: list[float]
    precipitation_probability_max: list[int | None]
    sunrise: list[str]
    sunset: list[str]
    uv_index_max: NotRequired[list[float]]


class ForecastPayload(TypedDict):
    """The top-level Open-Meteo forecast response we depend on."""

    current: CurrentBlock
    hourly: HourlyBlock
    daily: DailyBlock


def celsius_to_fahrenheit(celsius: float) -> float:
    """Converts a Celsius temperature to Fahrenheit."""
    return celsius * 9.0 / 5.0 + 32.0


@dataclasses.dataclass(frozen=True, slots=True)
class HourPoint:
    """One hour of the forecast chart."""

    time: datetime.datetime
    temperature_c: float
    precipitation_probability: int  # 0..100

    @property
    def temperature_f(self) -> float:
        """The temperature in Fahrenheit."""
        return celsius_to_fahrenheit(self.temperature_c)


@dataclasses.dataclass(frozen=True, slots=True)
class DayChip:
    """One day in the multi-day strip."""

    day: datetime.date
    weather_code: int
    temp_min_c: float
    temp_max_c: float
    precipitation_probability: int  # 0..100

    @property
    def temp_min_f(self) -> float:
        """The day's minimum temperature in Fahrenheit."""
        return celsius_to_fahrenheit(self.temp_min_c)

    @property
    def temp_max_f(self) -> float:
        """The day's maximum temperature in Fahrenheit."""
        return celsius_to_fahrenheit(self.temp_max_c)

    @property
    def condition(self) -> wmo.Condition:
        """The interpreted weather condition (day artwork)."""
        return wmo.describe(self.weather_code, is_day=True)


@dataclasses.dataclass(frozen=True, slots=True)
class WeatherReport:
    """The fully-parsed forecast used to render the display."""

    fetched_at: datetime.datetime  # timezone-aware, local
    temperature_c: float
    humidity: int  # 0..100
    uv_index: float
    weather_code: int
    is_day: bool
    sunrise: datetime.datetime
    sunset: datetime.datetime
    hours: list[HourPoint]
    days: list[DayChip]

    @property
    def temperature_f(self) -> float:
        """The current temperature in Fahrenheit."""
        return celsius_to_fahrenheit(self.temperature_c)

    @property
    def condition(self) -> wmo.Condition:
        """The interpreted current weather condition."""
        return wmo.describe(self.weather_code, is_day=self.is_day)

    @property
    def chart_min_c(self) -> float:
        """The lowest temperature across the hourly chart window."""
        return min((h.temperature_c for h in self.hours), default=0.0)

    @property
    def chart_max_c(self) -> float:
        """The highest temperature across the hourly chart window."""
        return max((h.temperature_c for h in self.hours), default=0.0)


def _session() -> requests.Session:
    """Builds a cached (1 h), auto-retrying requests session.

    Caching mostly helps dev mode (the preview re-renders without re-fetching);
    the in-memory backend keeps it within the running process and leaves no
    files behind. Retry adds resilience against transient network blips.

    Returns:
      A requests session with caching and retries configured.
    """
    base = requests_cache.CachedSession(
        "weatherdisplay", backend="memory", expire_after=3600
    )
    return retry_requests.retry(base, retries=3, backoff_factor=0.4)


def _forecast_days(cfg: config_lib.Config) -> int:
    """Returns how many days to request for both the chart and the chips."""
    needed_for_hours = cfg.chart_hours // 24 + 2
    return min(_MAX_FORECAST_DAYS, max(cfg.day_chips, needed_for_hours))


def fetch(
    cfg: config_lib.Config, *, now: datetime.datetime | None = None
) -> WeatherReport:
    """Fetches and parses the forecast for the configured location.

    Args:
      cfg: The loaded configuration (location, timezone, window sizes).
      now: Override for the current time (injected in tests).

    Returns:
      The parsed weather report.

    Raises:
      NetworkError: If Open-Meteo could not be reached.
      ApiError: If the response was an error status or unparseable.
    """
    params = {
        "latitude": cfg.latitude,
        "longitude": cfg.longitude,
        "timezone": cfg.timezone,
        "temperature_unit": "celsius",
        "timeformat": "iso8601",
        "current": _CURRENT_VARS,
        "hourly": _HOURLY_VARS,
        "daily": _DAILY_VARS,
        "forecast_days": _forecast_days(cfg),
    }
    try:
        response = _session().get(API_URL, params=params, timeout=20)
    except requests.exceptions.RequestException as exc:
        raise errors.NetworkError(
            f"could not reach Open-Meteo ({exc.__class__.__name__})"
        ) from exc

    if response.status_code != 200:
        # Open-Meteo returns {"error": true, "reason": "..."} on a 4xx status.
        raise errors.ApiError(
            f"HTTP {response.status_code} from Open-Meteo: "
            f"{_safe_reason(response)}"
        )

    try:
        # The lone trust boundary: decoded JSON is `Any`; we assert it matches
        # `ForecastPayload` here and `parse` validates the shape at runtime.
        payload: ForecastPayload = response.json()
    except ValueError as exc:
        raise errors.ApiError(f"Open-Meteo returned non-JSON: {exc}") from exc

    return parse(payload, cfg, now=now or datetime.datetime.now(cfg.tzinfo))


def _safe_reason(response: requests.Response) -> str:
    """Extracts a short human reason from an Open-Meteo error response."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:120]
    reason = body.get("reason") if isinstance(body, dict) else None
    return str(reason) if reason else response.text[:120]


def parse(
    payload: ForecastPayload,
    cfg: config_lib.Config,
    *,
    now: datetime.datetime,
) -> WeatherReport:
    """Parses a raw Open-Meteo JSON payload into a `WeatherReport`.

    Pure and timezone-aware: ``now`` decides where the hourly window starts.

    Args:
      payload: The decoded JSON body from the Open-Meteo forecast API.
      cfg: The loaded configuration.
      now: The current time, used to slice the hourly window.

    Returns:
      The parsed weather report.

    Raises:
      ApiError: If the payload is missing expected fields.
    """
    tz = cfg.tzinfo
    try:
        current = payload["current"]
        hourly = payload["hourly"]
        daily = payload["daily"]

        temperature_c = current["temperature_2m"]
        humidity = round(current["relative_humidity_2m"])
        weather_code = current["weather_code"]
        is_day = bool(current["is_day"])
        uv_index = _first_uv(current, daily)

        sunrise = _parse_local(daily["sunrise"][0], tz)
        sunset = _parse_local(daily["sunset"][0], tz)

        hours = _parse_hours(hourly, tz, now, cfg.chart_hours)
        days = _parse_days(daily, cfg.day_chips)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise errors.ApiError(
            f"unexpected Open-Meteo response shape: {exc}"
        ) from exc

    return WeatherReport(
        fetched_at=now,
        temperature_c=temperature_c,
        humidity=humidity,
        uv_index=uv_index,
        weather_code=weather_code,
        is_day=is_day,
        sunrise=sunrise,
        sunset=sunset,
        hours=hours,
        days=days,
    )


def _first_uv(current: CurrentBlock, daily: DailyBlock) -> float:
    """Returns the current UV index, falling back to today's daily max."""
    uv = current.get("uv_index")
    if uv is None:
        maxes = daily.get("uv_index_max")
        uv = maxes[0] if maxes else None
    return uv if uv is not None else 0.0


def _parse_hours(
    hourly: HourlyBlock,
    tz: datetime.tzinfo,
    now: datetime.datetime,
    limit: int,
) -> list[HourPoint]:
    """Parses up to ``limit`` hourly points starting at the current hour."""
    times = hourly["time"]
    temps = hourly["temperature_2m"]
    precs = hourly["precipitation_probability"]
    start_hour = now.replace(minute=0, second=0, microsecond=0)

    points: list[HourPoint] = []
    for iso, temp, prob in zip(times, temps, precs, strict=False):
        when = _parse_local(iso, tz)
        if when < start_hour:
            continue
        points.append(
            HourPoint(
                time=when,
                temperature_c=temp,
                precipitation_probability=_pct(prob),
            )
        )
        if len(points) == limit:
            break
    return points


def _parse_days(daily: DailyBlock, limit: int) -> list[DayChip]:
    """Parses up to ``limit`` day chips from the daily series."""
    chips: list[DayChip] = []
    for iso, code, tmax, tmin, prob in zip(
        daily["time"],
        daily["weather_code"],
        daily["temperature_2m_max"],
        daily["temperature_2m_min"],
        daily["precipitation_probability_max"],
        strict=False,
    ):
        chips.append(
            DayChip(
                day=datetime.date.fromisoformat(iso),
                weather_code=code,
                temp_min_c=tmin,
                temp_max_c=tmax,
                precipitation_probability=_pct(prob),
            )
        )
        if len(chips) == limit:
            break
    return chips


def _parse_local(iso: str, tz: datetime.tzinfo) -> datetime.datetime:
    """Parses a local ISO timestamp and attaches the configured timezone."""
    naive = datetime.datetime.fromisoformat(iso)
    if naive.tzinfo is None:
        return naive.replace(tzinfo=tz)
    return naive.astimezone(tz)


def _pct(value: float | None) -> int:
    """Coerces a possibly-null precipitation probability to 0..100."""
    if value is None:
        return 0
    return max(0, min(100, round(value)))
