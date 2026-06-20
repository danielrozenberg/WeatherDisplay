"""Flat TOML configuration loading and validation.

The config is a single flat TOML file (see `config.example.toml`). It is read
once at startup into a frozen, fully-typed `Config`. Any problem (missing file,
unknown/missing key, out-of-range value) raises `errors.ConfigError` with a
message that says exactly what to fix.
"""

from __future__ import annotations

import dataclasses
import pathlib
import tomllib
import zoneinfo
from typing import Literal

from . import errors

PrimaryUnit = Literal["metric", "imperial"]

#: Default config path, relative to the project root / working directory.
DEFAULT_CONFIG_PATH = pathlib.Path("config.toml")


@dataclasses.dataclass(frozen=True, slots=True)
class Config:
    """Validated, immutable runtime configuration.

    `Config` is the single source of truth for the recognised keys: the three
    fields without defaults are required, the rest are optional and supply their
    own defaults. The `_KNOWN_KEYS` / `_REQUIRED_KEYS` / `_DEFAULTS` collections
    below are derived from these fields so they never drift.
    """

    latitude: float
    longitude: float
    timezone: str
    primary_unit: PrimaryUnit = "metric"
    saturation: float = 0.5
    chart_hours: int = 16
    day_chips: int = 10
    wake_interval_hours: int = 4
    fetch_retries: int = 4
    auto_shutdown: bool = True
    pisugar_host: str = "127.0.0.1"
    pisugar_port: int = 8423
    dev_port: int = 8080
    verbose: bool = False

    @property
    def tzinfo(self) -> zoneinfo.ZoneInfo:
        """The configured timezone as a `zoneinfo.ZoneInfo`."""
        return zoneinfo.ZoneInfo(self.timezone)


# Recognised keys, derived from `Config` so they can never drift from it. A
# field with no default is required; the rest are optional with their default.
_FIELDS = {field.name: field for field in dataclasses.fields(Config)}
_KNOWN_KEYS = frozenset(_FIELDS)
_REQUIRED_KEYS = frozenset(
    name
    for name, field in _FIELDS.items()
    if field.default is dataclasses.MISSING
)
_DEFAULTS: dict[str, object] = {
    name: field.default
    for name, field in _FIELDS.items()
    if field.default is not dataclasses.MISSING
}


def load_config(path: pathlib.Path = DEFAULT_CONFIG_PATH) -> Config:
    """Read, validate and return the configuration from ``path``."""
    if not path.is_file():
        raise errors.ConfigError(
            f"config file not found at {path}. Copy config.example.toml to "
            f"{path} and edit it (install.sh does this for you)."
        )
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise errors.ConfigError(f"could not parse {path}: {exc}") from exc

    unknown = set(raw) - _KNOWN_KEYS
    if unknown:
        raise errors.ConfigError(
            f"unknown key(s) in {path}: {', '.join(sorted(unknown))}"
        )

    missing = _REQUIRED_KEYS - raw.keys()
    if missing:
        raise errors.ConfigError(
            f"missing required key(s) in {path}: {', '.join(sorted(missing))}"
        )

    merged = {**_DEFAULTS, **raw}
    return _build(merged, path)


def _build(values: dict[str, object], path: pathlib.Path) -> Config:
    """Coerces/validates a merged dict into a `Config` or raises."""
    latitude = _as_float(values["latitude"], "latitude", path)
    longitude = _as_float(values["longitude"], "longitude", path)
    if not -90.0 <= latitude <= 90.0:
        raise errors.ConfigError(
            f"latitude must be between -90 and 90 (got {latitude})"
        )
    if not -180.0 <= longitude <= 180.0:
        raise errors.ConfigError(
            f"longitude must be between -180 and 180 (got {longitude})"
        )

    timezone = _as_str(values["timezone"], "timezone", path)
    try:
        zoneinfo.ZoneInfo(timezone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise errors.ConfigError(
            f"invalid timezone {timezone!r}: {exc}"
        ) from exc

    primary_unit = _as_str(values["primary_unit"], "primary_unit", path)
    if primary_unit not in ("metric", "imperial"):
        raise errors.ConfigError(
            "primary_unit must be 'metric' or 'imperial' "
            f"(got {primary_unit!r})"
        )

    saturation = _as_float(values["saturation"], "saturation", path)
    if not 0.0 <= saturation <= 1.0:
        raise errors.ConfigError(
            f"saturation must be between 0.0 and 1.0 (got {saturation})"
        )

    chart_hours = _as_int(values["chart_hours"], "chart_hours", path)
    if not 1 <= chart_hours <= 48:
        raise errors.ConfigError(
            f"chart_hours must be between 1 and 48 (got {chart_hours})"
        )

    day_chips = _as_int(values["day_chips"], "day_chips", path)
    if not 1 <= day_chips <= 16:
        raise errors.ConfigError(
            f"day_chips must be between 1 and 16 (got {day_chips})"
        )

    wake_hours = _as_int(
        values["wake_interval_hours"], "wake_interval_hours", path
    )
    if not 1 <= wake_hours <= 24:
        raise errors.ConfigError(
            f"wake_interval_hours must be between 1 and 24 (got {wake_hours})"
        )

    fetch_retries = _as_int(values["fetch_retries"], "fetch_retries", path)
    if not 0 <= fetch_retries <= 10:
        raise errors.ConfigError(
            f"fetch_retries must be between 0 and 10 (got {fetch_retries})"
        )

    pisugar_port = _as_int(values["pisugar_port"], "pisugar_port", path)
    dev_port = _as_int(values["dev_port"], "dev_port", path)
    for name, port in (("pisugar_port", pisugar_port), ("dev_port", dev_port)):
        if not 1 <= port <= 65535:
            raise errors.ConfigError(
                f"{name} must be a valid port 1-65535 (got {port})"
            )

    return Config(
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
        primary_unit=primary_unit,  # type: ignore[arg-type]  # narrowed above
        saturation=saturation,
        chart_hours=chart_hours,
        day_chips=day_chips,
        wake_interval_hours=wake_hours,
        fetch_retries=fetch_retries,
        auto_shutdown=_as_bool(values["auto_shutdown"], "auto_shutdown", path),
        pisugar_host=_as_str(values["pisugar_host"], "pisugar_host", path),
        pisugar_port=pisugar_port,
        dev_port=dev_port,
        verbose=_as_bool(values["verbose"], "verbose", path),
    )


def _as_float(value: object, key: str, path: pathlib.Path) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.ConfigError(
            f"{key} in {path} must be a number (got {value!r})"
        )
    return float(value)


def _as_int(value: object, key: str, path: pathlib.Path) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.ConfigError(
            f"{key} in {path} must be an integer (got {value!r})"
        )
    return value


def _as_str(value: object, key: str, path: pathlib.Path) -> str:
    if not isinstance(value, str):
        raise errors.ConfigError(
            f"{key} in {path} must be a string (got {value!r})"
        )
    return value


def _as_bool(value: object, key: str, path: pathlib.Path) -> bool:
    if not isinstance(value, bool):
        raise errors.ConfigError(
            f"{key} in {path} must be true or false (got {value!r})"
        )
    return value
