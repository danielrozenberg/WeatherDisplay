"""Tests for the dev-preview Flask app (preset path only, no network)."""

from __future__ import annotations

import io

import flask.testing
import werkzeug.test

from weatherdisplay import config as config_lib
from weatherdisplay import dev_server
from weatherdisplay import fonts
from weatherdisplay import render


def _ttf_bytes(name: str) -> bytes:
    """Returns the bytes of a bundled font, for use as an upload payload."""
    return (render.static_dir() / "fonts" / name).read_bytes()


def _upload(
    client: flask.testing.FlaskClient, slot: str, name: str
) -> werkzeug.test.TestResponse:
    """Posts a bundled font ``name`` to ``slot`` as a multipart upload."""
    data = {"font": (io.BytesIO(_ttf_bytes(name)), name)}
    return client.post(
        f"/font/{slot}", data=data, content_type="multipart/form-data"
    )


def test_screen_png_for_preset(cfg: config_lib.Config) -> None:
    client = dev_server.create_app(cfg).test_client()
    resp = client.get("/screen.png?preset=rainy&battery=50")
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"
    assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_index_lists_preset_buttons(cfg: config_lib.Config) -> None:
    client = dev_server.create_app(cfg).test_client()
    resp = client.get("/?preset=snowy")
    assert resp.status_code == 200
    assert b"snowy" in resp.data
    assert b"Title font" in resp.data


def test_unknown_font_slot_is_404(cfg: config_lib.Config) -> None:
    client = dev_server.create_app(cfg).test_client()
    resp = client.post("/font/middle", data={})
    assert resp.status_code == 404


def test_font_upload_swaps_and_reports_name(cfg: config_lib.Config) -> None:
    client = dev_server.create_app(cfg).test_client()
    try:
        resp = _upload(client, "body", "PixelPurl.ttf")
        assert resp.status_code == 200
        assert resp.get_json()["name"] == "PixelPurl.ttf"
        # The index reflects the uploaded name, and rendering still works.
        assert b"PixelPurl.ttf" in client.get("/").data
        assert client.get("/screen.png?preset=rainy").status_code == 200
    finally:
        fonts.clear_override("body")


def test_font_upload_twice_does_not_crash(cfg: config_lib.Config) -> None:
    # Regression: a second upload used to overwrite a reused path out from
    # under the still-cached first font and 500 the next render. Each upload
    # now lands on a unique path, so re-swapping is safe.
    client = dev_server.create_app(cfg).test_client()
    try:
        for name in ("PixelPurl.ttf", "HomeVideo-Regular.ttf"):
            assert _upload(client, "body", name).status_code == 200
            assert client.get("/screen.png?preset=rainy").status_code == 200
        assert fonts.current_name("body") == "HomeVideo-Regular.ttf"
    finally:
        fonts.clear_override("body")


def test_font_upload_rejects_non_font(cfg: config_lib.Config) -> None:
    client = dev_server.create_app(cfg).test_client()
    data = {"font": (io.BytesIO(b"not a font"), "bad.ttf")}
    resp = client.post(
        "/font/body", data=data, content_type="multipart/form-data"
    )
    assert resp.status_code == 400
    # The slot stays on its bundled default.
    assert fonts.current_name("body") == "HomeVideo-Regular.ttf"
