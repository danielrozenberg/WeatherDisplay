"""Faithful Inky Impression (Spectra 6 / E673) colour simulation.

The dev preview must show what the panel will actually render, not a naive
quantization. To do that we mirror the exact pipeline of the upstream
``inky.inky_e673`` driver (verified against inky 2.3.0):

1. Blend the driver's DESATURATED and SATURATED palettes at the configured
   saturation (the quantization target).
2. Quantize the screenshot to those 6 colours with Floyd-Steinberg dithering.

The palette constants below are copied from the driver (it cannot be imported
on a dev machine: it pulls in GPIO/SPI). ``tests/test_palette.py`` asserts they
still match the installed ``inky`` package whenever it is importable, so they
cannot silently drift.
"""

from __future__ import annotations

from PIL import Image
from PIL import ImageChops

# The native panel resolution.
EINK_SIZE = (800, 480)

# Monochrome snapping (applied before dithering). Browser text and hairlines
# are antialiased to grey, which Floyd-Steinberg then turns into a black/white
# stipple. Pixels whose channel spread (max-min) is within this bound are
# treated as grey and snapped to solid black/white, so text stays crisp while
# genuinely coloured pixels are left to dither faithfully.
_MONO_CHROMA_MAX = 32
_MONO_LUMA_SPLIT = 128  # grey pixels darker than this snap to black, else white

# Copied verbatim from inky.inky_e673 (v2.3.0). The 7th entry is an unused
# "clean" placeholder; only the first six are used for blending/quantizing.
DESATURATED_PALETTE = [
    [0, 0, 0],
    [255, 255, 255],
    [255, 255, 0],
    [255, 0, 0],
    [0, 0, 255],
    [0, 255, 0],
    [255, 255, 255],
]
SATURATED_PALETTE = [
    [0, 0, 0],
    [161, 164, 165],
    [208, 190, 71],
    [156, 72, 75],
    [61, 59, 94],
    [58, 91, 70],
    [255, 255, 255],
]

# Number of selectable inks on the panel.
_NUM_COLOURS = 6


def palette_blend(saturation: float) -> list[int]:
    """Blends the two driver palettes into a flat RGB palette.

    Reproduces ``inky.inky_e673.Inky._palette_blend``: each channel is
    ``saturated * saturation + desaturated * (1 - saturation)``, truncated to an
    int, for the first six colours.

    Args:
      saturation: Colour saturation in the range 0.0 (muted) .. 1.0 (vivid).

    Returns:
      A flat ``[r, g, b, r, g, b, ...]`` palette of 18 ints (6 colours).
    """
    palette: list[int] = []
    for i in range(_NUM_COLOURS):
        rs, gs, bs = (c * saturation for c in SATURATED_PALETTE[i])
        rd, gd, bd = (c * (1.0 - saturation) for c in DESATURATED_PALETTE[i])
        palette += [int(rs + rd), int(gs + gd), int(bs + bd)]
    return palette


def quantize(image: Image.Image, saturation: float) -> Image.Image:
    """Quantizes an image to the 6 Spectra-6 inks with dithering.

    Identical to the driver's ``set_image`` quantization step, so the dithered
    output matches the panel pixel-for-pixel.

    Args:
      image: The source image (any mode/size; converted to RGB).
      saturation: Colour saturation passed through to the blend.

    Returns:
      A palette-mode (``"P"``) image with the blended 6-colour palette.
    """
    palette_image = Image.new("P", (1, 1))
    palette_image.putpalette(palette_blend(saturation))
    return image.convert("RGB").quantize(
        _NUM_COLOURS,
        palette=palette_image,
        dither=Image.Dither.FLOYDSTEINBERG,
    )


def snap_grays_to_mono(image: Image.Image) -> Image.Image:
    """Snaps near-grey pixels to pure black or white before dithering.

    Antialiased text/hairlines render as grey, which Floyd-Steinberg dithers
    into a distracting stipple. This snaps low-chroma pixels to solid ink (so
    text comes out crisp) while leaving coloured pixels untouched (so they keep
    dithering to the Spectra-6 inks). Applied on both the real-panel and dev
    paths, so the preview stays faithful to what the panel shows.

    Args:
      image: The source screenshot (any mode; converted to RGB).

    Returns:
      A new RGB image with near-grey pixels forced to black or white.
    """
    rgb = image.convert("RGB")
    red, green, blue = rgb.split()
    hi = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    lo = ImageChops.darker(ImageChops.darker(red, green), blue)
    grey_mask = ImageChops.subtract(hi, lo).point(
        lambda c: 255 if c <= _MONO_CHROMA_MAX else 0
    )
    mono = (
        rgb.convert("L")
        .point(lambda lum: 0 if lum < _MONO_LUMA_SPLIT else 255)
        .convert("RGB")
    )
    out = rgb.copy()
    out.paste(mono, (0, 0), grey_mask)
    return out


def simulate_eink(
    image: Image.Image, saturation: float, *, scale: int = 1
) -> Image.Image:
    """Produces the dev-preview image: quantized, optionally nearest-scaled.

    The result shows true 6-colour Floyd-Steinberg dithering at the configured
    saturation. The optional ``scale`` upsamples with nearest-neighbour
    sampling (kept for callers that want a magnified view).

    Args:
      image: The 800x480 screenshot to simulate.
      saturation: Colour saturation in the range 0.0 .. 1.0.
      scale: Integer upscaling factor for the preview (default 1, no scaling).

    Returns:
      An RGB image scaled to ``(800 * scale, 480 * scale)``.
    """
    quantized = quantize(snap_grays_to_mono(image), saturation).convert("RGB")
    if scale == 1:
        return quantized
    width, height = quantized.size
    return quantized.resize(
        (width * scale, height * scale), Image.Resampling.NEAREST
    )
