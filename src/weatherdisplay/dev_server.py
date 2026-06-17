"""Local design-preview server (the ``weatherdisplay dev`` command).

Renders the panel image with the production Pillow renderer and shows it in the
browser, with buttons to switch between weather presets, a battery control, and
drag-and-drop targets to hot-swap the title/body fonts. The werkzeug reloader
restarts the server on code edits and the page polls the image, so renderer,
icon, font or preset changes show up without a manual refresh -- no hardware or
headless browser needed.
"""

from __future__ import annotations

import contextlib
import io
import logging
import pathlib
import tempfile

import flask
import werkzeug

from . import config as config_lib
from . import display
from . import errors
from . import fonts
from . import palette
from . import pisugar
from . import presets
from . import render
from . import weather

_log = logging.getLogger("weatherdisplay.dev")

# Default simulated battery for the preview (no PiSugar on a dev machine).
_DEFAULT_BATTERY = 72

# Where uploaded dev fonts are stashed for hot-swapping.
_FONT_UPLOAD_DIR = (
    pathlib.Path(tempfile.gettempdir()) / "weatherdisplay-devfonts"
)


class _ReportCache:
    """Caches the fetched live report so reloads do not re-hit the API."""

    def __init__(self) -> None:
        """Starts with an empty cache."""
        self._report: weather.WeatherReport | None = None

    def get(self, cfg: config_lib.Config) -> weather.WeatherReport:
        """Returns the cached live report, fetching it on first use."""
        if self._report is None:
            self._report = weather.fetch(cfg)
        return self._report

    def clear(self) -> None:
        """Drops the cached report so the next get re-fetches."""
        self._report = None


def create_app(cfg: config_lib.Config) -> flask.Flask:
    """Builds the Flask app for the dev preview."""
    app = flask.Flask(__name__)
    cache = _ReportCache()

    @app.route("/")
    def index() -> str:
        preset = flask.request.args.get("preset", "live")
        pct = round(_dev_battery().percent)
        img = flask.url_for("screen_png", preset=preset, battery=pct)
        return flask.render_template(
            "dev.html",
            meta=_meta(cfg, preset),
            preset=preset,
            preset_names=("live", *presets.names()),
            battery=pct,
            img=img,
            title_font=fonts.current_path("title").name,
            body_font=fonts.current_path("body").name,
        )

    @app.route("/screen.png")
    def screen_png() -> flask.Response:
        preset = flask.request.args.get("preset", "live")
        battery = _dev_battery()
        try:
            report = _report_for(cfg, preset, cache)
            image = render.render_image(report, battery, cfg)
        except errors.WeatherDisplayError as exc:
            image = display.overlay_error(None, exc.user_message)
        sim = palette.simulate_eink(image, cfg.saturation, scale=1)
        buffer = io.BytesIO()
        sim.save(buffer, format="PNG")
        return flask.Response(buffer.getvalue(), mimetype="image/png")

    @app.route("/font/<slot>", methods=["POST"])
    def upload_font(slot: str) -> werkzeug.Response:
        if slot not in fonts.slots():
            flask.abort(404)
        upload = flask.request.files.get("font")
        if upload is None:
            flask.abort(400)
        _FONT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        path = _FONT_UPLOAD_DIR / f"{slot}.ttf"
        upload.save(path)
        fonts.set_override(slot, path)  # type: ignore[arg-type]
        _log.info("hot-swapped %s font -> %s", slot, upload.filename)
        return flask.Response(status=204)

    @app.route("/font/reset", methods=["POST"])
    def reset_fonts() -> werkzeug.Response:
        for slot in fonts.slots():
            fonts.clear_override(slot)
        return flask.redirect(flask.url_for("index"))

    @app.route("/refetch", methods=["POST"])
    def refetch() -> werkzeug.Response:
        cache.clear()
        return flask.redirect(flask.url_for("index"))

    return app


def serve(cfg: config_lib.Config) -> None:
    """Runs the dev server with the werkzeug auto-reloader until interrupted."""
    app = create_app(cfg)
    _log.info("dev server on http://0.0.0.0:%d", cfg.dev_port)
    app.run(host="0.0.0.0", port=cfg.dev_port, debug=True, use_reloader=True)


def _report_for(
    cfg: config_lib.Config, preset: str, cache: _ReportCache
) -> weather.WeatherReport:
    """Returns the preset report, or the cached live fetch for ``"live"``."""
    if preset and preset != "live":
        return presets.build(preset, cfg)
    return cache.get(cfg)


def _meta(cfg: config_lib.Config, preset: str) -> str:
    """Returns the small status line shown in the header."""
    return (
        f"{cfg.latitude:.3f}, {cfg.longitude:.3f} \u00b7 preset {preset} "
        f"\u00b7 saturation {cfg.saturation}"
    )


def _dev_battery() -> pisugar.BatteryStatus:
    """Returns the simulated battery, overridable via ``?battery=NN``."""
    raw = flask.request.args.get("battery")
    percent = float(_DEFAULT_BATTERY)
    if raw is not None:
        with contextlib.suppress(ValueError):
            percent = max(0.0, min(100.0, float(raw)))
    return pisugar.BatteryStatus(percent=percent, plugged=True)
