"""Pushing images to the Inky display and compositing error overlays.

`show` sends a freshly rendered PNG to the panel and remembers it as the
last-good image. `show_error` reloads that last-good image and composites a
banner describing what failed, so a transient error leaves the previous screen
visible with an explanation on top instead of a blank panel.

The ``inky`` package is imported lazily because it is a Pi-only dependency
(GPIO/SPI); the overlay compositing itself uses only Pillow and is therefore
testable on any machine.
"""

from __future__ import annotations

import io
import logging
import pathlib

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

from . import errors
from . import palette

_log = logging.getLogger("weatherdisplay.display")

# A loaded font is either a TrueType font or Pillow's bitmap default.
type _Font = ImageFont.FreeTypeFont | ImageFont.ImageFont

# Error banner appearance (colours land on the nearest Spectra-6 ink).
_BANNER_BG = (200, 0, 0)
_BANNER_FG = (255, 255, 255)
_BANNER_MARGIN = 40
_BANNER_PAD = 24

# Candidate fonts, tried in order; falls back to Pillow's built-in font.
_FONT_CANDIDATES = (
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def show(
    png: bytes, saturation: float, *, last_image_path: pathlib.Path
) -> None:
    """Pushes a rendered PNG to the panel and saves it as last-good.

    Args:
      png: PNG image bytes at the native panel resolution.
      saturation: Inky colour saturation (0.0 .. 1.0).
      last_image_path: Where to persist the image for later error overlays.

    Raises:
      DisplayError: If the image is the wrong size or the panel push fails.
    """
    image = _decode(png)
    _push(image, saturation)
    _save_last(image, last_image_path)


def show_error(
    message: str, saturation: float, *, last_image_path: pathlib.Path
) -> None:
    """Overlays ``message`` on the last-good image and pushes it.

    Args:
      message: The human-readable error message to display.
      saturation: Inky colour saturation (0.0 .. 1.0).
      last_image_path: Where the last-good image was persisted.

    Raises:
      DisplayError: If the panel push fails.
    """
    base = _load_last(last_image_path)
    composited = overlay_error(base, message)
    _push(composited, saturation)


def overlay_error(base: Image.Image | None, message: str) -> Image.Image:
    """Composites an error banner onto a copy of ``base``.

    Pure Pillow (no hardware), so it can be unit-tested and previewed.

    Args:
      base: The last-good image, or None to start from a blank screen.
      message: The error message to render in the banner.

    Returns:
      A new RGB image with the banner drawn over the base.
    """
    width, height = palette.EINK_SIZE
    if base is None:
        canvas = Image.new("RGB", palette.EINK_SIZE, (255, 255, 255))
    else:
        canvas = base.convert("RGB").resize(palette.EINK_SIZE)

    draw = ImageDraw.Draw(canvas)
    title_font = _font(34)
    body_font = _font(24)

    inner_w = width - 2 * _BANNER_MARGIN - 2 * _BANNER_PAD
    lines = _wrap(draw, message, body_font, inner_w)

    line_h = _line_height(draw, body_font)
    title_h = _line_height(draw, title_font)
    banner_h = _BANNER_PAD * 2 + title_h + 8 + line_h * len(lines)
    top = (height - banner_h) // 2

    draw.rectangle(
        (_BANNER_MARGIN, top, width - _BANNER_MARGIN, top + banner_h),
        fill=_BANNER_BG,
    )

    text_x = _BANNER_MARGIN + _BANNER_PAD
    y = top + _BANNER_PAD
    draw.text((text_x, y), "Update failed", font=title_font, fill=_BANNER_FG)
    y += title_h + 8
    for line in lines:
        draw.text((text_x, y), line, font=body_font, fill=_BANNER_FG)
        y += line_h
    return canvas


def _decode(png: bytes) -> Image.Image:
    """Decodes PNG bytes and validates the panel resolution."""
    image = Image.open(io.BytesIO(png)).convert("RGB")
    if image.size != palette.EINK_SIZE:
        raise errors.DisplayError(
            f"image is {image.size}, expected {palette.EINK_SIZE}"
        )
    return image


def _push(image: Image.Image, saturation: float) -> None:
    """Sends an image to the Inky panel (lazy hardware import)."""
    try:
        import inky  # type: ignore[import-not-found]
    except ImportError as exc:
        raise errors.DisplayError(
            "the 'inky' package is not installed; install with "
            "'pip install .[pi]' on the Raspberry Pi"
        ) from exc

    try:
        device = inky.auto()
        # Snap antialiased greys to solid ink so the driver's dithering leaves
        # text crisp (mirrors the dev preview's simulate_eink preprocessing).
        prepared = palette.snap_grays_to_mono(image)
        device.set_image(prepared, saturation=saturation)
        device.show()
    except Exception as exc:
        raise errors.DisplayError(f"could not update the panel: {exc}") from exc


def _save_last(image: Image.Image, path: pathlib.Path) -> None:
    """Persists the last-good image, ignoring write failures."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, format="PNG")
    except OSError as exc:
        _log.warning("could not save last image to %s: %s", path, exc)


def _load_last(path: pathlib.Path) -> Image.Image | None:
    """Loads the last-good image, or None if it is missing/unreadable."""
    if not path.is_file():
        return None
    try:
        return Image.open(path).convert("RGB")
    except OSError as exc:
        _log.warning("could not read last image %s: %s", path, exc)
        return None


def _font(size: int) -> _Font:
    """Loads a TrueType font at ``size``, falling back to the default."""
    for candidate in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _line_height(draw: ImageDraw.ImageDraw, font: _Font) -> int:
    """Returns the pixel height of a line of text in ``font``."""
    box = draw.textbbox((0, 0), "Ag", font=font)
    return int(box[3] - box[1])


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: _Font,
    max_width: int,
) -> list[str]:
    """Greedily wraps ``text`` to fit ``max_width`` pixels."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]
