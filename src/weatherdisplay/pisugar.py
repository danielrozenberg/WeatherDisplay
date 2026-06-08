"""PiSugar 3 power-manager client.

Talks to ``pisugar-server`` over its TCP socket (default ``127.0.0.1:8423``)
using the simple newline-delimited text protocol::

    > get battery
    battery: 87.512
    > rtc_alarm_set 2026-06-06T20:00:00+01:00 127
    rtc_alarm_set: done

We read the battery level / charging state and schedule the next wake-up by
writing the RTC alarm. The hardware power switch must stay **ON** for the
scheduled wake to power the Pi back up.
"""

from __future__ import annotations

import dataclasses
import datetime
import io
import socket

from . import config as config_lib
from . import errors

# RTC alarm weekday bitmask: all 7 days. We re-arm the alarm on every run, so a
# fire-every-day mask simply guarantees it triggers whatever day now+interval
# lands on.
_ALARM_EVERY_DAY = 127

_SOCKET_TIMEOUT = 5.0


@dataclasses.dataclass(frozen=True, slots=True)
class BatteryStatus:
    """A snapshot of the PiSugar battery."""

    percent: float  # 0..100
    plugged: bool  # external power connected

    @property
    def low(self) -> bool:
        """Whether the battery graphic should turn red (< 20%)."""
        return self.percent < 20.0


def next_wake_time(
    now: datetime.datetime, interval_hours: int
) -> datetime.datetime:
    """Returns the next wall-clock boundary strictly after ``now``.

    Aligns wake-ups to the day's grid so updates land at predictable times
    (e.g. with a 4 h interval: 00:00, 04:00, 08:00, ...), rolling into the next
    day when needed.

    Args:
      now: The current time; should be timezone-aware.
      interval_hours: The spacing between wake-ups, in hours.

    Returns:
      The next aligned wake time.
    """
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_hours = (now - midnight).total_seconds() / 3600.0
    next_index = int(elapsed_hours // interval_hours) + 1
    return midnight + datetime.timedelta(hours=next_index * interval_hours)


class PiSugar:
    """A thin synchronous client for a single pisugar-server endpoint."""

    def __init__(self, host: str, port: int) -> None:
        """Stores the endpoint to connect to.

        Args:
          host: The pisugar-server host.
          port: The pisugar-server TCP port.
        """
        self._host = host
        self._port = port

    def read_battery(self) -> BatteryStatus:
        """Reads the current battery percentage and charging state.

        Returns:
          The battery snapshot.

        Raises:
          PiSugarError: If the server is unreachable or replies oddly.
        """
        percent_raw = self._command("get battery")
        plugged_raw = self._command("get battery_power_plugged")
        try:
            percent = float(percent_raw)
        except ValueError as exc:
            raise errors.PiSugarError(
                f"unexpected battery reading {percent_raw!r}"
            ) from exc
        return BatteryStatus(
            percent=max(0.0, min(100.0, percent)),
            plugged=plugged_raw.strip().lower() == "true",
        )

    def schedule_wake(self, at: datetime.datetime) -> None:
        """Syncs the RTC to system time, then arms the wake-up alarm.

        Args:
          at: The timezone-aware time to wake at.

        Raises:
          PiSugarError: If ``at`` is naive or the server is unreachable.
        """
        # Push the (NTP-disciplined) system clock to the RTC first so the alarm
        # fires at the intended wall-clock time even if the RTC has drifted.
        self._command("rtc_pi2rtc")
        when = at.replace(microsecond=0)
        if when.tzinfo is None:
            raise errors.PiSugarError("wake time must be timezone-aware")
        self._command(f"rtc_alarm_set {when.isoformat()} {_ALARM_EVERY_DAY}")

    def _command(self, command: str) -> str:
        """Sends one command and returns the value portion of the reply."""
        try:
            with socket.create_connection(
                (self._host, self._port), _SOCKET_TIMEOUT
            ) as sock:
                sock.settimeout(_SOCKET_TIMEOUT)
                sock.sendall(f"{command}\n".encode())
                reply = _read_line(sock)
        except OSError as exc:
            raise errors.PiSugarError(
                f"could not reach pisugar-server at "
                f"{self._host}:{self._port} ({exc})"
            ) from exc
        return parse_reply(command, reply)


def _read_line(sock: socket.socket) -> str:
    """Reads a single newline-terminated line from ``sock``."""
    buffer = io.BytesIO()
    while True:
        data = sock.recv(256)
        if not data:
            break
        buffer.write(data)
        if b"\n" in data:
            break
    lines = buffer.getvalue().decode(errors="replace").splitlines()
    return lines[0] if lines else ""


def parse_reply(command: str, reply: str) -> str:
    """Extracts the value from a ``key: value`` reply.

    Separated out (and pure) so the wire protocol can be unit-tested.

    Args:
      command: The command that was sent (for error messages).
      reply: The raw reply line from the server.

    Returns:
      The trimmed value portion of the reply.

    Raises:
      PiSugarError: If the reply is empty or malformed.
    """
    reply = reply.strip()
    if not reply:
        raise errors.PiSugarError(f"empty reply to {command!r}")
    _, sep, value = reply.partition(":")
    if not sep:
        raise errors.PiSugarError(f"malformed reply to {command!r}: {reply!r}")
    return value.strip()


def from_config(cfg: config_lib.Config) -> PiSugar:
    """Builds a `PiSugar` client from configuration."""
    return PiSugar(cfg.pisugar_host, cfg.pisugar_port)
