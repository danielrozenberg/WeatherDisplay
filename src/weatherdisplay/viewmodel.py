"""Pure presentation logic: turns a `WeatherReport` into a `DisplayView`.

All formatting and chart geometry live here (and nothing does I/O) so the
template stays dumb and the layout maths can be unit-tested. The chart uses an
SVG view-box coordinate system; the template scales it to fit.
"""

from __future__ import annotations

import dataclasses
import datetime

from . import config as config_lib
from . import pisugar
from . import weather

# Chart SVG view-box. The temperature line lives in the upper band and the
# precipitation bars rise from the baseline, so the two overlay each other.
CHART_W = 760.0
CHART_H = 150.0
_TEMP_TOP = 14.0
_TEMP_BOTTOM = 96.0
_PRECIP_BASE = 140.0
_PRECIP_MAX_H = 74.0
# Pad the temperature axis so the line never touches the very top/bottom.
_TEMP_PAD_C = 1.0


@dataclasses.dataclass(frozen=True, slots=True)
class ChartBar:
    """One hour's geometry within the chart view-box."""

    x: float  # centre x of this hour's column
    temp_x: float  # temperature point x (== x)
    temp_y: float  # temperature point y
    precip_x: float  # left edge of the precipitation bar
    precip_y: float  # top of the precipitation bar
    precip_w: float  # bar width
    precip_h: float  # bar height
    precip_pct: int
    hour_label: str  # e.g. "14"
    show_hour: bool  # whether to draw the hour label (avoids crowding)
    temp_label: str  # primary-unit temperature, e.g. "14°"
    show_temp: bool


@dataclasses.dataclass(frozen=True, slots=True)
class ChartView:
    """The full hourly chart geometry."""

    width: float
    height: float
    bars: list[ChartBar]
    temp_points: str  # "x,y x,y ..." for the SVG polyline


@dataclasses.dataclass(frozen=True, slots=True)
class ChipView:
    """One day chip."""

    label: str  # "Today", "Mon", ...
    icon: str  # icon slug
    high: str  # primary-unit max, e.g. "21°"
    low: str  # primary-unit min, e.g. "12°"
    precip_pct: int


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
    sunrise: str  # "05:12"
    sunset: str  # "21:18"


@dataclasses.dataclass(frozen=True, slots=True)
class DisplayView:
    """Everything the template needs to render the 800x480 screen."""

    header: HeaderView
    chart: ChartView
    chips: list[ChipView]
    updated: str  # e.g. "Mon 14:32"
    battery_pct: int
    battery_low: bool
    static_base: str  # file:// (or http) base URL for static assets


def build_view(
    report: weather.WeatherReport,
    battery: pisugar.BatteryStatus | None,
    cfg: config_lib.Config,
    *,
    static_base: str,
) -> DisplayView:
    """Builds the immutable `DisplayView` for a report.

    Args:
      report: The parsed weather report.
      battery: The battery snapshot, or None if it could not be read.
      cfg: The loaded configuration (controls the primary unit).
      static_base: Base URL the template prefixes onto static asset paths.

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
        updated=report.fetched_at.strftime("%a %H:%M"),
        battery_pct=round(battery.percent) if battery else 0,
        battery_low=battery.low if battery else True,
        static_base=static_base.rstrip("/"),
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
    return HeaderView(
        temp_primary=str(primary),
        unit_primary=unit,
        temp_secondary=secondary,
        condition_label=condition.label,
        condition_icon=condition.icon,
        humidity=report.humidity,
        uv_index=_format_uv(report.uv_index),
        uv_label=_uv_label(report.uv_index),
        sunrise=report.sunrise.strftime("%H:%M"),
        sunset=report.sunset.strftime("%H:%M"),
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
        precip_pct=chip.precipitation_probability,
    )


def _build_chart(report: weather.WeatherReport, *, metric: bool) -> ChartView:
    """Computes the chart geometry from the hourly points."""
    hours = report.hours
    count = len(hours)
    if count == 0:
        return ChartView(width=CHART_W, height=CHART_H, bars=[], temp_points="")

    lo = report.chart_min_c - _TEMP_PAD_C
    hi = report.chart_max_c + _TEMP_PAD_C
    span = hi - lo or 1.0
    column = CHART_W / count
    bar_w = column * 0.6
    # Label every other hour (or every hour if few) to avoid clutter.
    label_step = 1 if count <= 8 else 2

    bars: list[ChartBar] = []
    points: list[str] = []
    for i, point in enumerate(hours):
        x = (i + 0.5) * column
        temp_y = _TEMP_BOTTOM - (point.temperature_c - lo) / span * (
            _TEMP_BOTTOM - _TEMP_TOP
        )
        precip_h = point.precipitation_probability / 100.0 * _PRECIP_MAX_H
        temp_value = point.temperature_c if metric else point.temperature_f
        bars.append(
            ChartBar(
                x=x,
                temp_x=x,
                temp_y=temp_y,
                precip_x=x - bar_w / 2,
                precip_y=_PRECIP_BASE - precip_h,
                precip_w=bar_w,
                precip_h=precip_h,
                precip_pct=point.precipitation_probability,
                hour_label=point.time.strftime("%H"),
                show_hour=(i % label_step == 0),
                temp_label=f"{round(temp_value)}°",
                show_temp=(i % label_step == 0),
            )
        )
        points.append(f"{x:.1f},{temp_y:.1f}")

    return ChartView(
        width=CHART_W,
        height=CHART_H,
        bars=bars,
        temp_points=" ".join(points),
    )


def _weekday_label(day: datetime.date, today: datetime.date) -> str:
    """Returns 'Today' when ``day`` is ``today``, else a short weekday."""
    if day == today:
        return "Today"
    return day.strftime("%a")


def _format_uv(uv: float) -> str:
    """Formats the UV index without a trailing '.0'."""
    rounded = round(uv, 1)
    return str(int(rounded)) if rounded.is_integer() else str(rounded)


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
