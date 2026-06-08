"""WMO weather-code interpretation.

Open-Meteo reports conditions as WMO weather codes (WW). This maps each code to
a short human label and an icon slug. Icon slugs correspond to SVG files in
``static/icons/<slug>.svg`` (day/night variants for clear & partly-cloudy).

Reference: https://open-meteo.com/en/docs (WMO Weather interpretation codes).
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True, slots=True)
class Condition:
    """A human-friendly interpretation of a WMO weather code."""

    code: int
    label: str
    #: Icon slug; ``static/icons/<icon>.svg`` must exist.
    icon: str


# code -> (label, base icon slug). Day/night is applied in `describe()`.
_CODES: dict[int, tuple[str, str]] = {
    0: ("Clear", "clear"),
    1: ("Mainly clear", "partly-cloudy"),
    2: ("Partly cloudy", "partly-cloudy"),
    3: ("Overcast", "cloudy"),
    45: ("Fog", "fog"),
    48: ("Rime fog", "fog"),
    51: ("Light drizzle", "drizzle"),
    53: ("Drizzle", "drizzle"),
    55: ("Heavy drizzle", "drizzle"),
    56: ("Freezing drizzle", "sleet"),
    57: ("Freezing drizzle", "sleet"),
    61: ("Light rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "sleet"),
    67: ("Freezing rain", "sleet"),
    71: ("Light snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Rain showers", "rain"),
    81: ("Rain showers", "rain"),
    82: ("Heavy showers", "rain"),
    85: ("Snow showers", "snow"),
    86: ("Snow showers", "snow"),
    95: ("Thunderstorm", "thunderstorm"),
    96: ("Thunderstorm", "thunderstorm"),
    99: ("Thunderstorm, hail", "thunderstorm"),
}

# Icons that have distinct day/night artwork.
_DAY_NIGHT_ICONS = frozenset({"clear", "partly-cloudy"})


def describe(code: int, *, is_day: bool = True) -> Condition:
    """Return the :class:`Condition` for a WMO ``code``.

    Unknown codes fall back to a neutral "cloudy" condition rather than raising,
    so a surprise code never blanks the display.
    """
    label, icon = _CODES.get(code, ("Unknown", "cloudy"))
    if icon in _DAY_NIGHT_ICONS:
        icon = f"{icon}-{'day' if is_day else 'night'}"
    return Condition(code=code, label=label, icon=icon)
