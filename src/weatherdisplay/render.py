"""HTML rendering and headless-Chromium screenshotting.

`render_html` turns a `DisplayView` into an HTML string via Jinja2; `screenshot`
loads that HTML in headless Chromium and captures an 800x480 PNG. `render_png`
chains the two for the common case.

On a dev machine Playwright's bundled Chromium is used. On the Raspberry Pi we
point Playwright at the system ``chromium-browser`` (installed by install.sh)
via ``executable_path`` so no ARM browser download is needed, and add memory-
friendly flags for low-RAM Pis (e.g. the Pi Zero 2 W).
"""

from __future__ import annotations

import functools
import os
import pathlib
import shutil
import tempfile

import jinja2
from playwright import sync_api

from . import config as config_lib
from . import errors
from . import palette
from . import pisugar
from . import viewmodel
from . import weather

_PACKAGE_DIR = pathlib.Path(__file__).resolve().parent
_TEMPLATES_DIR = _PACKAGE_DIR / "templates"
_STATIC_DIR = _PACKAGE_DIR / "static"

WEATHER_TEMPLATE = "weather.html.j2"

# Chromium flags safe on both desktop and the Pi. --no-sandbox is required when
# running as root (the appliance does); the shm/gpu flags avoid crashes and OOM
# on memory-constrained Pis like the Pi Zero 2 W.
_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--hide-scrollbars",
    "--force-color-profile=srgb",
]
# Extra flag used only with the system browser (the Pi) to cut memory use.
_PI_EXTRA_ARGS = ["--single-process"]

# System Chromium binaries to look for, in order of preference.
_CHROMIUM_BINARIES = ("chromium-browser", "chromium", "chromium-browser-stable")


def static_dir() -> pathlib.Path:
    """Returns the path to the packaged static-assets directory."""
    return _STATIC_DIR


def static_base_uri() -> str:
    """Returns a ``file://`` base URL for the static directory."""
    return _STATIC_DIR.as_uri()


@functools.cache
def _env() -> jinja2.Environment:
    """Returns the (cached) Jinja2 environment for our templates."""
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=jinja2.select_autoescape(["html", "xml", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def environment() -> jinja2.Environment:
    """Returns the shared Jinja2 environment (used by the dev server)."""
    return _env()


def templates_dir() -> pathlib.Path:
    """Returns the path to the packaged templates directory."""
    return _TEMPLATES_DIR


def render_html(
    view: viewmodel.DisplayView, *, template: str = WEATHER_TEMPLATE
) -> str:
    """Renders a `DisplayView` to an HTML string.

    Args:
      view: The populated display view-model.
      template: The template filename to render.

    Returns:
      The rendered HTML.

    Raises:
      RenderError: If the template cannot be found or rendered.
    """
    try:
        return _env().get_template(template).render(view=view)
    except jinja2.TemplateError as exc:
        raise errors.RenderError(f"template {template!r}: {exc}") from exc


def default_chromium_path() -> str | None:
    """Returns the system Chromium path, or None to use Playwright's bundle.

    Honours the ``WEATHERDISPLAY_CHROMIUM`` environment variable first, then
    searches ``PATH`` for a known Chromium binary.
    """
    override = os.environ.get("WEATHERDISPLAY_CHROMIUM")
    if override:
        return override
    for name in _CHROMIUM_BINARIES:
        found = shutil.which(name)
        if found:
            return found
    return None


def screenshot(html: str, *, executable_path: str | None = None) -> bytes:
    """Renders ``html`` in headless Chromium and returns an 800x480 PNG.

    Args:
      html: The HTML document to render.
      executable_path: System Chromium to use, or None for the bundled browser.

    Returns:
      PNG image bytes at the native panel resolution.

    Raises:
      RenderError: If the browser fails to launch or capture the page.
    """
    width, height = palette.EINK_SIZE
    args = list(_CHROMIUM_ARGS)
    if executable_path:
        args += _PI_EXTRA_ARGS

    with tempfile.TemporaryDirectory(prefix="weatherdisplay-") as tmp:
        page_path = pathlib.Path(tmp) / "page.html"
        page_path.write_text(html, encoding="utf-8")
        try:
            with sync_api.sync_playwright() as play:
                browser = play.chromium.launch(
                    headless=True,
                    args=args,
                    executable_path=executable_path,
                )
                try:
                    page = browser.new_page(
                        viewport={"width": width, "height": height},
                        device_scale_factor=1,
                    )
                    page.goto(page_path.as_uri(), wait_until="networkidle")
                    # Let web fonts finish loading before the capture.
                    page.evaluate("() => document.fonts.ready")
                    png = page.screenshot(
                        clip={"x": 0, "y": 0, "width": width, "height": height}
                    )
                finally:
                    browser.close()
        except sync_api.Error as exc:
            raise errors.RenderError(
                f"Chromium screenshot failed: {exc}"
            ) from exc
    return png


def render_png(
    report: weather.WeatherReport,
    battery: pisugar.BatteryStatus | None,
    cfg: config_lib.Config,
    *,
    executable_path: str | None = None,
) -> bytes:
    """Builds the view, renders HTML and captures the PNG in one call.

    Args:
      report: The parsed weather report.
      battery: The battery snapshot, or None if unavailable.
      cfg: The loaded configuration.
      executable_path: System Chromium to use, or None for the bundle.

    Returns:
      PNG image bytes at the native panel resolution.
    """
    view = viewmodel.build_view(
        report, battery, cfg, static_base=static_base_uri()
    )
    return screenshot(render_html(view), executable_path=executable_path)
