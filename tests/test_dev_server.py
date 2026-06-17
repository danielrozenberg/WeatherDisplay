"""Tests for the dev-preview Flask app (preset path only, no network)."""

from __future__ import annotations

from weatherdisplay import config as config_lib
from weatherdisplay import dev_server


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
