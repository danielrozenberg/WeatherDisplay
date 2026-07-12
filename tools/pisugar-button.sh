#!/usr/bin/env bash
#
# PiSugar custom-button handler, run as root by pisugar-server (which executes
# the configured button shell via /bin/sh). Registered by install.sh through
# the server's set_button_shell command.
#
#   pisugar-button.sh single   start an update (no-op if one is running);
#                              blink LEDs 1x
#   pisugar-button.sh double   toggle the stay-awake sentinel; blink LEDs 2x
#                              when created, 3x when removed
#   pisugar-button.sh long     git pull, then start an update; blink LEDs 4x
#                              up front and 1x more when the update starts
#
# The LED blink is visual confirmation only and is best-effort: it drives the
# four battery LEDs directly over I2C (PiSugar 3 register 0xE0), which needs
# i2c-tools and a firmware that exposes that register. Failures are ignored.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE=weatherdisplay.service

I2C_BUS=1
I2C_ADDR=0x57
REG_WRITE_ENABLE=0x0b # 0x29 makes the other registers writable; 0x00 locks
REG_LED=0xe0          # bits 0-3 drive the four battery LEDs
LED_ALL_ON=0x0f
LED_ALL_OFF=0x00
BLINK_SECONDS=0.2
GIT_PULL_TIMEOUT=300

# Bookworm mounts the boot partition at /boot/firmware; older OSes at /boot.
# Must match _STAY_AWAKE_SENTINELS in src/weatherdisplay/app.py.
sentinel_path() {
  if [[ -d /boot/firmware ]]; then
    echo /boot/firmware/weatherdisplay-stayawake
  else
    echo /boot/weatherdisplay-stayawake
  fi
}

# Blinks all four battery LEDs $1 times; every step is best-effort.
blink() {
  local count="$1" original
  command -v i2cset >/dev/null 2>&1 || return 0
  original="$(i2cget -y "$I2C_BUS" "$I2C_ADDR" "$REG_LED" 2>/dev/null)" \
    || return 0
  i2cset -y "$I2C_BUS" "$I2C_ADDR" "$REG_WRITE_ENABLE" 0x29 2>/dev/null \
    || return 0
  for ((i = 0; i < count; i++)); do
    i2cset -y "$I2C_BUS" "$I2C_ADDR" "$REG_LED" "$LED_ALL_ON" 2>/dev/null \
      || break
    sleep "$BLINK_SECONDS"
    i2cset -y "$I2C_BUS" "$I2C_ADDR" "$REG_LED" "$LED_ALL_OFF" 2>/dev/null \
      || break
    sleep "$BLINK_SECONDS"
  done
  i2cset -y "$I2C_BUS" "$I2C_ADDR" "$REG_LED" "$original" 2>/dev/null || true
  i2cset -y "$I2C_BUS" "$I2C_ADDR" "$REG_WRITE_ENABLE" 0x00 2>/dev/null || true
}

# Starts the update service without waiting for it to finish. If a run is
# already in flight, the start request merges with it (oneshot semantics)
# instead of queueing a second update.
start_update() {
  systemctl start --no-block "$SERVICE"
}

# Pulls the repo as its owning user so .git never collects root-owned files.
git_pull() {
  local owner
  owner="$(stat -c %U "$REPO_DIR")"
  timeout "$GIT_PULL_TIMEOUT" \
    runuser -u "$owner" -- git -C "$REPO_DIR" pull --ff-only
}

case "${1:-}" in
  single)
    start_update
    blink 1
    ;;
  double)
    sentinel="$(sentinel_path)"
    if [[ -e "$sentinel" ]]; then
      rm -f "$sentinel"
      blink 3
    else
      touch "$sentinel"
      blink 2
    fi
    ;;
  long)
    blink 4
    git_pull || echo "git pull failed; starting the update anyway" >&2
    start_update
    blink 1
    ;;
  *)
    echo "usage: $0 {single|double|long}" >&2
    exit 64
    ;;
esac
