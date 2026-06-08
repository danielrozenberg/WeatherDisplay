"""Tests for the PiSugar protocol parsing and wake-time maths."""

from __future__ import annotations

import datetime
import zoneinfo

import pytest

from weatherdisplay import errors
from weatherdisplay import pisugar

_TZ = zoneinfo.ZoneInfo("Europe/London")


def test_parse_reply_extracts_value() -> None:
    assert pisugar.parse_reply("get battery", "battery: 87.5") == "87.5"


def test_parse_reply_trims_whitespace() -> None:
    assert pisugar.parse_reply("x", "  key :  true  ") == "true"


def test_parse_reply_empty_raises() -> None:
    with pytest.raises(errors.PiSugarError, match="empty reply"):
        pisugar.parse_reply("get battery", "")


def test_parse_reply_malformed_raises() -> None:
    with pytest.raises(errors.PiSugarError, match="malformed"):
        pisugar.parse_reply("get battery", "no-colon-here")


def test_battery_low_threshold() -> None:
    assert pisugar.BatteryStatus(percent=19.9, plugged=False).low is True
    assert pisugar.BatteryStatus(percent=20.0, plugged=False).low is False


def test_next_wake_aligns_to_grid() -> None:
    now = datetime.datetime(2026, 6, 6, 14, 32, tzinfo=_TZ)
    wake = pisugar.next_wake_time(now, 4)
    assert wake == datetime.datetime(2026, 6, 6, 16, 0, tzinfo=_TZ)


def test_next_wake_rolls_into_next_day() -> None:
    now = datetime.datetime(2026, 6, 6, 23, 10, tzinfo=_TZ)
    wake = pisugar.next_wake_time(now, 4)
    assert wake == datetime.datetime(2026, 6, 7, 0, 0, tzinfo=_TZ)


def test_next_wake_strictly_after_now_on_boundary() -> None:
    now = datetime.datetime(2026, 6, 6, 16, 0, tzinfo=_TZ)
    wake = pisugar.next_wake_time(now, 4)
    assert wake == datetime.datetime(2026, 6, 6, 20, 0, tzinfo=_TZ)
