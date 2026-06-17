"""Typed error hierarchy.

Every failure the ``update`` job can recover from is one of these. They carry a
short ``headline`` and a one-line ``detail`` so that, on failure, we can overlay
a human-readable banner on top of the last good screen (see
:mod:`weatherdisplay.display`).
"""

from __future__ import annotations


class WeatherDisplayError(Exception):
    """Base class for all expected, recoverable WeatherDisplay failures."""

    #: Short, fixed label shown big on the error overlay, e.g. "Network error".
    headline: str = "Error"

    def __init__(self, detail: str = "") -> None:
        """Stores the one-line detail shown after the headline.

        Args:
          detail: A short, specific description of what went wrong.
        """
        self.detail = detail
        super().__init__(detail or self.headline)

    @property
    def user_message(self) -> str:
        """The full one-line message for the on-screen overlay."""
        return (
            f"{self.headline}: {self.detail}" if self.detail else self.headline
        )


class ConfigError(WeatherDisplayError):
    """The config file is missing, unreadable, or has invalid values."""

    headline = "Config error"


class NetworkError(WeatherDisplayError):
    """Could not reach the Open-Meteo API (DNS, connection, timeout)."""

    headline = "Network error"


class ApiError(WeatherDisplayError):
    """The API responded, but with an error status or unparseable payload."""

    headline = "API error"


class RenderError(WeatherDisplayError):
    """The panel image could not be rendered."""

    headline = "Render error"


class DisplayError(WeatherDisplayError):
    """The image could not be pushed to the Inky display."""

    headline = "Display error"


class PiSugarError(WeatherDisplayError):
    """Could not talk to the PiSugar power manager."""

    headline = "PiSugar error"
