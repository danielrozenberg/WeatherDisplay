"""Local design-preview web server (the ``weatherdisplay dev`` command).

Fetches the weather once, then serves a page showing the live 800x480 HTML on
top and the faithful e-ink simulation below. Templates and static assets are
watched with livereload, so saving a file reloads the browser and re-renders
both panes — no hardware required.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import io
import logging

import flask
import livereload
import werkzeug
from PIL import Image

from . import config as config_lib
from . import display
from . import errors
from . import palette
from . import pisugar
from . import render
from . import viewmodel
from . import weather

_log = logging.getLogger("weatherdisplay.dev")

# Default simulated battery for the preview (no PiSugar on a dev machine).
_DEFAULT_BATTERY = 72

# The dev server runs under Tornado's asyncio loop (livereload). Playwright's
# sync API cannot run inside a running event loop, so screenshots are taken on
# this worker thread, which has no loop of its own.
_render_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="render"
)


class _ReportCache:
    """Caches the fetched report so reloads do not re-hit the API."""

    def __init__(self) -> None:
        """Starts with an empty cache."""
        self._report: weather.WeatherReport | None = None

    def get(self, cfg: config_lib.Config) -> weather.WeatherReport:
        """Returns the cached report, fetching it on first use."""
        if self._report is None:
            self._report = weather.fetch(cfg)
        return self._report

    def clear(self) -> None:
        """Drops the cached report so the next get re-fetches."""
        self._report = None


def create_app(cfg: config_lib.Config) -> flask.Flask:
    """Builds the Flask app for the dev preview.

    Args:
      cfg: The loaded configuration.

    Returns:
      A configured Flask application.
    """
    app = flask.Flask(__name__)
    cache = _ReportCache()

    @app.route("/")
    def index() -> str:
        battery = _dev_battery()
        try:
            report = cache.get(cfg)
            fetched = report.fetched_at.strftime("%H:%M:%S")
        except errors.WeatherDisplayError as exc:
            fetched = f"ERROR: {exc.user_message}"
        template = render.environment().get_template("dev.html.j2")
        return template.render(
            location=f"{cfg.latitude:.3f}, {cfg.longitude:.3f}",
            fetched=fetched,
            saturation=cfg.saturation,
            battery_pct=battery.percent,
            screen_url=flask.url_for("screen"),
            image_url=flask.url_for("screen_png"),
            refetch_url=flask.url_for("refetch"),
        )

    @app.route("/screen")
    def screen() -> str:
        battery = _dev_battery()
        try:
            report = cache.get(cfg)
        except errors.WeatherDisplayError as exc:
            return _error_html(exc.user_message)
        view = viewmodel.build_view(report, battery, cfg, static_base="/static")
        return render.render_html(view)

    @app.route("/screen.png")
    def screen_png() -> flask.Response:
        battery = _dev_battery()
        try:
            report = cache.get(cfg)
            png = _render_pool.submit(
                render.render_png, report, battery, cfg
            ).result()
            image = Image.open(io.BytesIO(png))
        except errors.WeatherDisplayError as exc:
            image = render_error_image(exc.user_message)
        sim = palette.simulate_eink(image, cfg.saturation, scale=1)
        buffer = io.BytesIO()
        sim.save(buffer, format="PNG")
        return flask.Response(buffer.getvalue(), mimetype="image/png")

    @app.route("/static/<path:filename>")
    def static_files(filename: str) -> flask.Response:
        return flask.send_from_directory(render.static_dir(), filename)

    @app.route("/refetch", methods=["POST"])
    def refetch() -> werkzeug.Response:
        cache.clear()
        return flask.redirect(flask.url_for("index"))

    return app


def serve(cfg: config_lib.Config) -> None:
    """Runs the dev server with livereload until interrupted.

    Args:
      cfg: The loaded configuration (provides the port).
    """
    app = create_app(cfg)
    server = livereload.Server(app.wsgi_app)
    server.watch(str(render.templates_dir()))
    server.watch(str(render.static_dir()))
    _log.info("dev server on http://0.0.0.0:%d", cfg.dev_port)
    # live_css=False forces a full page reload on CSS edits. The default CSS
    # hot-swap only reloads <link> stylesheets, which updates the live-HTML
    # pane but leaves the server-rendered /screen.png (e-ink) pane stale.
    server.serve(
        host="0.0.0.0", port=cfg.dev_port, restart_delay=0.3, live_css=False
    )


def _dev_battery() -> pisugar.BatteryStatus:
    """Returns the simulated battery, overridable via ``?battery=NN``."""
    raw = flask.request.args.get("battery")
    percent = float(_DEFAULT_BATTERY)
    if raw is not None:
        with contextlib.suppress(ValueError):
            percent = max(0.0, min(100.0, float(raw)))
    return pisugar.BatteryStatus(percent=percent, plugged=True)


def render_error_image(message: str) -> Image.Image:
    """Renders a blank-screen error overlay for the preview."""
    return display.overlay_error(None, message)


def _error_html(message: str) -> str:
    """Returns a minimal HTML page describing a fetch error."""
    return (
        "<!doctype html><meta charset=utf-8>"
        "<body style='font-family:sans-serif;padding:24px'>"
        f"<h2>Weather fetch failed</h2><p>{message}</p>"
    )
