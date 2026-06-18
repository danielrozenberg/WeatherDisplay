"""Direct Pillow rendering of the 800x480 panel image.

Draws the dashboard with pixel fonts ([fonts.py](fonts.py)) and pixel-art icons
([icons.py](icons.py)) using only the six panel inks, so the output is already
on-palette and needs no dithering. This replaces the former HTML + headless
Chromium screenshot pipeline.

`render_image` builds a `PIL.Image`; `render_png` returns PNG bytes for the
panel/display path. Both take the same `(report, battery, cfg)` as before.
"""

from __future__ import annotations

import io
import pathlib

from PIL import Image
from PIL import ImageDraw

from . import config as config_lib
from . import fonts
from . import icons
from . import palette
from . import pisugar
from . import viewmodel
from . import weather

WIDTH, HEIGHT = palette.EINK_SIZE

_PACKAGE_DIR = pathlib.Path(__file__).resolve().parent
_STATIC_DIR = _PACKAGE_DIR / "static"

# Inks (opaque RGB) used across the layout.
_BLACK = palette.BLACK
_WHITE = palette.WHITE
_RED = palette.RED
_BLUE = palette.BLUE
_GREEN = palette.GREEN

_MARGIN = 14

# Hero block (current conditions, left) + stats panel (right).
_HERO_Y = 44
_HERO_ICON = 96
_STATS_X = 432

# Chart band. No separator lines around it; the time axis sits at the bottom
# with the temperature line and precip bars above it and hour labels / sun
# notches below it.
_TEMP_TOP = 232
_TEMP_BOTTOM = 290
_AXIS_Y = 316  # the time axis / precip baseline
_PRECIP_MAX_H = 46
_HOUR_LABEL_Y = 320  # hour labels, just below the axis
_SUN_ICON = 16  # smaller icon for the sunrise/sunset notches
_TEMP_PAD = 1.0

# Day-chip strip.
_CHIPS_TOP = 366


def static_dir() -> pathlib.Path:
    """Returns the packaged static-assets directory (fonts live here)."""
    return _STATIC_DIR


def render_image(
    report: weather.WeatherReport,
    battery: pisugar.BatteryStatus | None,
    cfg: config_lib.Config,
) -> Image.Image:
    """Builds the 800x480 RGB panel image for a report."""
    view = viewmodel.build_view(report, battery, cfg)
    image = Image.new("RGB", (WIDTH, HEIGHT), _WHITE)
    draw = ImageDraw.Draw(image)
    # Render text bilevel (no anti-aliasing): the panel has only six inks, so a
    # font's anti-aliased edge pixels would land off-palette. This keeps every
    # glyph on-ink regardless of the font or size in a slot (incl. dev-mode
    # uploads), matching the pixel-art look.
    draw.fontmode = "1"

    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=_BLACK, width=2)
    _draw_topbar(draw, view)
    _draw_hero(draw, image, view)
    _draw_stats(draw, image, view)
    _draw_chart(draw, image, view)
    _draw_chips(draw, image, view)
    return image


def render_png(
    report: weather.WeatherReport,
    battery: pisugar.BatteryStatus | None,
    cfg: config_lib.Config,
) -> bytes:
    """Renders the panel image to PNG bytes."""
    buffer = io.BytesIO()
    render_image(report, battery, cfg).save(buffer, format="PNG")
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Regions
# --------------------------------------------------------------------------- #
def _draw_topbar(
    draw: ImageDraw.ImageDraw, view: viewmodel.DisplayView
) -> None:
    """Draws the 'Updated …' line and the battery gauge."""
    draw.text(
        (_MARGIN + 4, 16),
        f"Last updated: {view.updated}",
        font=fonts.font("tiny"),
        fill=_BLACK,
        anchor="lm",
    )
    _draw_battery(
        draw, WIDTH - _MARGIN - 4, 16, view.battery_pct, view.battery_low
    )
    draw.line((_MARGIN, 36, WIDTH - _MARGIN, 36), fill=_BLACK, width=2)


def _draw_battery(
    draw: ImageDraw.ImageDraw, right: int, cy: int, pct: int, low: bool
) -> None:
    """Draws a pixel battery gauge whose right edge sits at ``right``."""
    body_w, body_h = 38, 18
    x1, y0 = right - 3, cy - body_h // 2
    x0, y1 = x1 - body_w, y0 + body_h
    draw.rectangle((x0, y0, x1, y1), outline=_BLACK, width=2)
    draw.rectangle((x1 + 1, cy - 4, x1 + 3, cy + 4), fill=_BLACK)  # nub
    inner = body_w - 8
    fill_w = round(inner * max(0, min(100, pct)) / 100)
    if fill_w > 0:
        colour = _RED if low else _GREEN
        draw.rectangle((x0 + 3, y0 + 3, x0 + 3 + fill_w, y1 - 3), fill=colour)


def _draw_hero(
    draw: ImageDraw.ImageDraw, image: Image.Image, view: viewmodel.DisplayView
) -> None:
    """Draws the big condition icon, temperature, and condition label."""
    header = view.header
    image.paste(
        icons.render(header.condition_icon, _HERO_ICON),
        (_MARGIN + 6, _HERO_Y + 26),
        icons.render(header.condition_icon, _HERO_ICON),
    )
    tx = _MARGIN + 6 + _HERO_ICON + 16
    big = fonts.font("temp-hero")
    draw.text(
        (tx, _HERO_Y + 24),
        header.temp_primary,
        font=big,
        fill=_RED,
        anchor="la",
    )
    num_w = draw.textlength(header.temp_primary, font=big)
    unit = f"°{header.unit_primary}"
    unit_font = fonts.font("temp-unit")
    draw.text(
        (tx + num_w + 6, _HERO_Y + 36),
        unit,
        font=unit_font,
        fill=_RED,
        anchor="la",
    )
    # Alternate-unit temp on the same top line, just right of the °unit.
    unit_w = draw.textlength(unit, font=unit_font)
    draw.text(
        (tx + num_w + 6 + unit_w + 16, _HERO_Y + 36),
        header.temp_secondary,
        font=fonts.font("secondary"),
        fill=_BLACK,
        anchor="la",
    )
    # Condition label below, left-aligned with the temperature.
    draw.text(
        (tx, _HERO_Y + 92),
        header.condition_label,
        font=fonts.font("condition"),
        fill=_BLACK,
        anchor="la",
    )


def _draw_stats(
    draw: ImageDraw.ImageDraw, image: Image.Image, view: viewmodel.DisplayView
) -> None:
    """Draws the 2x2 stats panel (humidity, UV, wind, air quality)."""
    header = view.header
    cells = (
        ("humidity", f"{header.humidity}%", "Humidity"),
        ("uv", header.uv_index, f"UV {header.uv_label}"),
        ("wind", header.wind_value, header.wind_unit),
        ("air-quality", header.aqi_value, header.aqi_label),
    )
    col_w, row_h = 178, 74
    for i, (slug, value, label) in enumerate(cells):
        cx = _STATS_X + (i % 2) * col_w
        cy = _HERO_Y + (i // 2) * row_h
        image.paste(
            icons.render(slug, 32), (cx, cy + 8), icons.render(slug, 32)
        )
        # Big value beside the icon; caption spans the full cell width on the
        # row below (indenting it past the icon would run long labels off the
        # panel at the body font's 20px size).
        draw.text(
            (cx + 42, cy + 4),
            value,
            font=fonts.font("value"),
            fill=_BLACK,
            anchor="la",
        )
        draw.text(
            (cx, cy + 48),
            label,
            font=fonts.font("label"),
            fill=_BLACK,
            anchor="la",
        )


def _draw_chart(
    draw: ImageDraw.ImageDraw, image: Image.Image, view: viewmodel.DisplayView
) -> None:
    """Draws the temperature line + precip bars above a bottom time axis."""
    bars = view.chart.bars
    count = len(bars)
    if count == 0:
        return
    left, right = _MARGIN + 6, WIDTH - _MARGIN - 6
    col = (right - left) / count
    lo = min(b.temp_value for b in bars) - _TEMP_PAD
    hi = max(b.temp_value for b in bars) + _TEMP_PAD
    span = (hi - lo) or 1.0
    bar_w = max(4, int(col * 0.5))

    # The time axis along the bottom; precip bars rise from it, hour labels and
    # sun notches hang off it.
    draw.line(
        (_MARGIN, _AXIS_Y, WIDTH - _MARGIN, _AXIS_Y), fill=_BLACK, width=2
    )

    points: list[tuple[float, float]] = []
    for i, bar in enumerate(bars):
        x = left + (i + 0.5) * col
        y = _TEMP_BOTTOM - (bar.temp_value - lo) / span * (
            _TEMP_BOTTOM - _TEMP_TOP
        )
        points.append((x, y))
        # Precip bar rising from the axis; % label sits white inside a tall
        # enough bar (skip short bars where it would spill onto white paper).
        if bar.precip_pct > 0:
            h = bar.precip_pct / 100.0 * _PRECIP_MAX_H
            draw.rectangle(
                (x - bar_w / 2, _AXIS_Y - h, x + bar_w / 2, _AXIS_Y), fill=_BLUE
            )
            if h >= 16:
                draw.text(
                    (x, _AXIS_Y - 3),
                    str(bar.precip_pct),
                    font=fonts.font("label"),
                    fill=_WHITE,
                    anchor="ms",
                )
        # Hour label below the axis.
        draw.text(
            (x, _HOUR_LABEL_Y),
            bar.hour_label,
            font=fonts.font("label"),
            fill=_BLACK,
            anchor="ma",
        )

    if len(points) > 1:
        draw.line(points, fill=_RED, width=3, joint="curve")
    for i, (x, y) in enumerate(points):
        draw.rectangle((x - 2, y - 2, x + 2, y + 2), fill=_RED)
        draw.text(
            (x, y - 8),
            bars[i].temp_label,
            font=fonts.font("label"),
            fill=_BLACK,
            anchor="ms",
        )

    _draw_sun_events(draw, image, view.chart.sun_events, left, col)


def _draw_sun_events(
    draw: ImageDraw.ImageDraw,
    image: Image.Image,
    events: list[viewmodel.SunEvent],
    left: float,
    col: float,
) -> None:
    """Marks sunrise/sunset with a notch on the axis and a boxed icon below it.

    The icon sits in a white box that cleanly overpaints any hour label it lands
    on; the time is drawn just below the box.
    """
    box_w, box_h = 26, _SUN_ICON + 4
    for event in events:
        x = round(left + (event.pos + 0.5) * col)
        # Notch straddling the axis.
        draw.line((x, _AXIS_Y - 4, x, _AXIS_Y + 3), fill=_BLACK, width=2)
        # Boxed icon below the axis (the white fill occludes the hour label).
        top = _AXIS_Y + 3
        draw.rectangle(
            (x - box_w // 2, top, x + box_w // 2, top + box_h),
            fill=_WHITE,
            outline=_BLACK,
        )
        glyph = icons.render(event.icon, _SUN_ICON)
        image.paste(glyph, (x - _SUN_ICON // 2, top + 2), glyph)
        # Time just below the box.
        draw.text(
            (x, top + box_h + 2),
            event.label,
            font=fonts.font("label"),
            fill=_BLACK,
            anchor="ma",
        )
        # Off-chart events get a right-pointing arrow ("still to come").
        if event.out_of_bounds:
            ax = x + box_w // 2 + 3
            ay = top + box_h // 2
            draw.polygon(
                ((ax, ay - 4), (ax, ay + 4), (ax + 5, ay)), fill=_BLACK
            )


def _draw_chips(
    draw: ImageDraw.ImageDraw, image: Image.Image, view: viewmodel.DisplayView
) -> None:
    """Draws the day-chip strip along the bottom."""
    chips = view.chips
    count = len(chips)
    if count == 0:
        return
    left, right = _MARGIN, WIDTH - _MARGIN
    cell = (right - left) / count
    for i, chip in enumerate(chips):
        cx = left + (i + 0.5) * cell
        if i > 0:
            x = round(left + i * cell)
            draw.line((x, _CHIPS_TOP + 4, x, HEIGHT - _MARGIN), fill=_BLACK)
        draw.text(
            (cx, _CHIPS_TOP),
            chip.label,
            font=fonts.font("chip-day"),
            fill=_BLACK,
            anchor="ma",
        )
        glyph = icons.render(chip.icon, 32)
        image.paste(glyph, (round(cx) - 16, _CHIPS_TOP + 20), glyph)
        # High/low drawn as two values hugging the cell centre (a joined
        # string's space sits too wide at the body font's 20px size).
        gap = 3  # half the gap between high and low
        draw.text(
            (cx - gap, _CHIPS_TOP + 58),
            chip.high,
            font=fonts.font("label"),
            fill=_BLACK,
            anchor="ra",
        )
        draw.text(
            (cx + gap, _CHIPS_TOP + 58),
            chip.low,
            font=fonts.font("label"),
            fill=_BLACK,
            anchor="la",
        )
        if chip.precip_pct > 0:
            draw.text(
                (cx, _CHIPS_TOP + 78),
                f"{chip.precip_pct}%",
                font=fonts.font("label"),
                fill=_BLUE,
                anchor="ma",
            )
