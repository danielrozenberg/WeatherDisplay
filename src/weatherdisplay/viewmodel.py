"""Pure presentation logic: turns a `WeatherReport` into a `DisplayView`.

All formatting lives here (and nothing does I/O) so the renderer only has to
place already-formatted strings and plot already-chosen values. The chart is
exposed as plain per-hour data; the renderer owns all pixel geometry.
"""

from __future__ import annotations

import dataclasses
import datetime

from . import config as config_lib
from . import pisugar
from . import weather


@dataclasses.dataclass(frozen=True, slots=True)
class ChartBar:
    """One hour of the chart: the value to plot plus its labels."""

    hour_label: str  # e.g. "3p"
    temp_label: str  # primary-unit temperature, e.g. "14°"
    temp_value: float  # primary-unit temperature, for plotting the line
    precip_pct: int  # precipitation odds, rounded to the nearest 10%


@dataclasses.dataclass(frozen=True, slots=True)
class SunEvent:
    """A sunrise/sunset marker placed on the chart's time axis."""

    icon: str  # "sunrise" or "sunset"
    label: str  # 12-hour time, e.g. "5:12a"
    pos: float  # fractional hour index along the chart (0 .. len(bars) - 1)
    out_of_bounds: bool = False  # True if pinned to the end with an arrow


@dataclasses.dataclass(frozen=True, slots=True)
class ChartView:
    """The hourly chart as plain data (the renderer computes geometry)."""

    bars: list[ChartBar]
    sun_events: list[SunEvent]


@dataclasses.dataclass(frozen=True, slots=True)
class ChipView:
    """One day chip."""

    label: str  # "Today", "Mon", ...
    icon: str  # icon slug
    high: str  # primary-unit max, e.g. "21°"
    low: str  # primary-unit min, e.g. "12°"
    precip_pct: int  # precipitation odds, rounded to the nearest 10%


@dataclasses.dataclass(frozen=True, slots=True)
class HeaderView:
    """The current-conditions header."""

    temp_primary: str  # e.g. "14"
    unit_primary: str  # "C" or "F"
    temp_secondary: str  # e.g. "57°F"
    condition_label: str
    condition_icon: str
    humidity: int
    uv_index: str  # e.g. "5" or "5.4"
    uv_label: str  # "Low" / "Moderate" / ...
    wind_value: str  # e.g. "NW 12"
    wind_unit: str  # "km/h" or "mph"
    aqi_value: str  # e.g. "42" or "--"
    aqi_label: str  # e.g. "AQI Good"


@dataclasses.dataclass(frozen=True, slots=True)
class DisplayView:
    """Everything the template needs to render the 800x480 screen."""

    header: HeaderView
    chart: ChartView
    chips: list[ChipView]
    updated: str  # e.g. "Mon 07 Jun 2026 2:32 PM"
    battery_pct: int
    battery_low: bool


def build_view(
    report: weather.WeatherReport,
    battery: pisugar.BatteryStatus | None,
    cfg: config_lib.Config,
) -> DisplayView:
    """Builds the immutable `DisplayView` for a report.

    Args:
      report: The parsed weather report.
      battery: The battery snapshot, or None if it could not be read.
      cfg: The loaded configuration (controls the primary unit).

    Returns:
      The fully-populated display view-model.
    """
    metric = cfg.primary_unit == "metric"
    today = report.fetched_at.date()
    return DisplayView(
        header=_build_header(report, metric=metric),
        chart=_build_chart(report, metric=metric),
        chips=[
            _build_chip(chip, metric=metric, today=today)
            for chip in report.days
        ],
        updated=_updated_label(report.fetched_at),
        battery_pct=round(battery.percent) if battery else 0,
        battery_low=battery.low if battery else True,
    )


def _build_header(report: weather.WeatherReport, *, metric: bool) -> HeaderView:
    """Builds the current-conditions header view."""
    if metric:
        primary = round(report.temperature_c)
        unit = "C"
        secondary = f"{round(report.temperature_f)}°F"
    else:
        primary = round(report.temperature_f)
        unit = "F"
        secondary = f"{round(report.temperature_c)}°C"
    condition = report.condition
    wind = f"{_compass(report.wind_direction)} {round(report.wind_speed)}"
    aqi = report.air_quality
    return HeaderView(
        temp_primary=str(primary),
        unit_primary=unit,
        temp_secondary=secondary,
        condition_label=condition.label,
        condition_icon=condition.icon,
        humidity=report.humidity,
        uv_index=_format_uv(report.uv_index),
        uv_label=_uv_label(report.uv_index),
        wind_value=wind,
        wind_unit="km/h" if metric else "mph",
        aqi_value=str(aqi) if aqi is not None else "--",
        aqi_label=_aqi_label(aqi),
    )


def _build_chip(
    chip: weather.DayChip, *, metric: bool, today: datetime.date
) -> ChipView:
    """Builds one day chip view."""
    if metric:
        high = f"{round(chip.temp_max_c)}°"
        low = f"{round(chip.temp_min_c)}°"
    else:
        high = f"{round(chip.temp_max_f)}°"
        low = f"{round(chip.temp_min_f)}°"
    return ChipView(
        label=_weekday_label(chip.day, today),
        icon=chip.condition.icon,
        high=high,
        low=low,
        precip_pct=_round_precip(chip.precipitation_probability),
    )


def _build_chart(report: weather.WeatherReport, *, metric: bool) -> ChartView:
    """Builds the per-hour chart data (the renderer computes pixel geometry)."""
    bars: list[ChartBar] = []
    for point in report.hours:
        temp_value = point.temperature_c if metric else point.temperature_f
        bars.append(
            ChartBar(
                hour_label=_hour_label(point.time),
                temp_label=f"{round(temp_value)}°",
                temp_value=temp_value,
                precip_pct=_round_precip(point.precipitation_probability),
            )
        )
    return ChartView(bars=bars, sun_events=_sun_events(report))


def _sun_events(report: weather.WeatherReport) -> list[SunEvent]:
    """Places sunrise/sunset markers along the chart's time axis.

    Events inside the window are positioned exactly. To keep one sunrise and one
    sunset on screen, when only a single event is in view the next upcoming
    event (its complement) is pinned to the right edge and flagged out-of-bounds
    with an arrow.
    """
    hours = report.hours
    if len(hours) < 2:
        return []
    start = hours[0].time
    last = len(hours) - 1
    moments: list[tuple[float, str, datetime.datetime]] = []
    for icon, times in (
        ("sunrise", report.sunrises),
        ("sunset", report.sunsets),
    ):
        for when in times:
            pos = (when - start).total_seconds() / 3600.0
            moments.append((pos, icon, when))
    moments.sort(key=lambda m: m[0])

    events = [
        SunEvent(icon=icon, label=_clock_short(when), pos=pos)
        for pos, icon, when in moments
        if 0.0 <= pos <= last
    ]
    if len(events) == 1:
        nxt = next((m for m in moments if m[0] > last), None)
        if nxt is not None:
            _, icon, when = nxt
            events.append(
                SunEvent(
                    icon=icon,
                    label=_clock_short(when),
                    pos=float(last),
                    out_of_bounds=True,
                )
            )
    return events


def _round_precip(probability: int) -> int:
    """Rounds a precipitation probability to the nearest 10%."""
    return round(probability / 10) * 10


def _hour_label(when: datetime.datetime) -> str:
    """Formats an hour in compact 12-hour style, e.g. '1p' or '12a'."""
    hour = when.hour % 12 or 12
    suffix = "a" if when.hour < 12 else "p"
    return f"{hour}{suffix}"


def _clock_short(when: datetime.datetime) -> str:
    """Formats a time of day in compact 12-hour style, e.g. '5:12a'."""
    hour = when.hour % 12 or 12
    suffix = "a" if when.hour < 12 else "p"
    return f"{hour}:{when.minute:02d}{suffix}"


def _updated_label(when: datetime.datetime) -> str:
    """Formats the update stamp in 12-hour style (e.g. '2:32 PM')."""
    hour = when.hour % 12 or 12
    suffix = "a" if when.hour < 12 else "p"
    return f"{when:%A, %B %d, %Y}, {hour}:{when.minute:02d}{suffix}"


def _weekday_label(day: datetime.date, today: datetime.date) -> str:
    """Returns 'Today' when ``day`` is ``today``, else a short weekday."""
    if day == today:
        return "Today"
    return day.strftime("%a")


def _format_uv(uv: float) -> str:
    """Formats the UV index without a trailing '.0'."""
    rounded = round(uv, 1)
    return str(int(rounded)) if rounded.is_integer() else str(rounded)


_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def _compass(degrees: int) -> str:
    """Maps a wind bearing in degrees to an 8-point compass abbreviation."""
    return _COMPASS[round(degrees / 45) % 8]


def _aqi_label(aqi: int | None) -> str:
    """Maps a US AQI to its short category, prefixed 'AQI'."""
    if aqi is None:
        return "AQI n/a"
    if aqi <= 50:
        return "AQI Good"
    if aqi <= 100:
        return "AQI Moderate"
    if aqi <= 150:
        return "AQI Sensitive"
    if aqi <= 200:
        return "AQI Unhealthy"
    if aqi <= 300:
        return "AQI Very bad"
    return "AQI Hazardous"


def _uv_label(uv: float) -> str:
    """Maps a UV index to its WHO exposure category."""
    if uv < 3:
        return "Low"
    if uv < 6:
        return "Moderate"
    if uv < 8:
        return "High"
    if uv < 11:
        return "Very high"
    return "Extreme"
