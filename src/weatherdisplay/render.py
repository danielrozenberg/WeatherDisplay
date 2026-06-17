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

# Chart band.
_CHART_TOP = 222
_CHART_BOT = 360
_HOUR_LABEL_Y = 226
_TEMP_TOP = 250
_TEMP_BOTTOM = 318
_PRECIP_BASE = 352
_PRECIP_MAX_H = 64
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

    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline=_BLACK, width=2)
    _draw_topbar(draw, view)
    _draw_hero(draw, image, view)
    _draw_stats(draw, image, view)
    _draw_chart(draw, view)
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
        f"UPDATED {view.updated}",
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
        (_MARGIN + 6, _HERO_Y),
        icons.render(header.condition_icon, _HERO_ICON),
    )
    tx = _MARGIN + 6 + _HERO_ICON + 16
    big = fonts.font("temp-hero")
    draw.text(
        (tx, _HERO_Y + 4), header.temp_primary, font=big, fill=_RED, anchor="la"
    )
    num_w = draw.textlength(header.temp_primary, font=big)
    draw.text(
        (tx + num_w + 6, _HERO_Y + 14),
        f"°{header.unit_primary}",
        font=fonts.font("temp-unit"),
        fill=_RED,
        anchor="la",
    )
    draw.text(
        (tx, _HERO_Y + 104),
        header.temp_secondary,
        font=fonts.font("secondary"),
        fill=_BLACK,
        anchor="la",
    )
    draw.text(
        (tx, _HERO_Y + 140),
        header.condition_label,
        font=fonts.font("condition"),
        fill=_BLACK,
        anchor="la",
    )


def _draw_stats(
    draw: ImageDraw.ImageDraw, image: Image.Image, view: viewmodel.DisplayView
) -> None:
    """Draws the 2x2 stats panel (humidity, UV, sunrise, sunset)."""
    header = view.header
    cells = (
        ("humidity", f"{header.humidity}%", "Humidity"),
        ("uv", header.uv_index, f"UV {header.uv_label}"),
        ("sunrise", header.sunrise, "Sunrise"),
        ("sunset", header.sunset, "Sunset"),
    )
    col_w, row_h = 178, 74
    for i, (slug, value, label) in enumerate(cells):
        cx = _STATS_X + (i % 2) * col_w
        cy = _HERO_Y + (i // 2) * row_h
        image.paste(
            icons.render(slug, 32), (cx, cy + 8), icons.render(slug, 32)
        )
        draw.text(
            (cx + 42, cy + 6),
            value,
            font=fonts.font("value"),
            fill=_BLACK,
            anchor="la",
        )
        draw.text(
            (cx + 42, cy + 42),
            label,
            font=fonts.font("label"),
            fill=_BLACK,
            anchor="la",
        )


def _draw_chart(draw: ImageDraw.ImageDraw, view: viewmodel.DisplayView) -> None:
    """Draws the hourly temperature line and precipitation bars."""
    draw.line(
        (_MARGIN, _CHART_TOP, WIDTH - _MARGIN, _CHART_TOP), fill=_BLACK, width=2
    )
    draw.line(
        (_MARGIN, _CHART_BOT, WIDTH - _MARGIN, _CHART_BOT), fill=_BLACK, width=2
    )

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

    points: list[tuple[float, float]] = []
    for i, bar in enumerate(bars):
        x = left + (i + 0.5) * col
        y = _TEMP_BOTTOM - (bar.temp_value - lo) / span * (
            _TEMP_BOTTOM - _TEMP_TOP
        )
        points.append((x, y))
        # Precip bar from the baseline up; % label sits white inside a tall
        # enough bar (skip short bars where it would spill onto white paper).
        if bar.precip_pct > 0:
            h = bar.precip_pct / 100.0 * _PRECIP_MAX_H
            draw.rectangle(
                (x - bar_w / 2, _PRECIP_BASE - h, x + bar_w / 2, _PRECIP_BASE),
                fill=_BLUE,
            )
            if h >= 16:
                draw.text(
                    (x, _PRECIP_BASE - 3),
                    str(bar.precip_pct),
                    font=fonts.font("label"),
                    fill=_WHITE,
                    anchor="ms",
                )
        # Hour label on top.
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
        draw.text(
            (cx, _CHIPS_TOP + 58),
            f"{chip.high} {chip.low}",
            font=fonts.font("label"),
            fill=_BLACK,
            anchor="ma",
        )
        if chip.precip_pct > 0:
            draw.text(
                (cx, _CHIPS_TOP + 78),
                f"{chip.precip_pct}%",
                font=fonts.font("label"),
                fill=_BLUE,
                anchor="ma",
            )
