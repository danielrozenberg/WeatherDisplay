#!/usr/bin/env bash
#
# WeatherDisplay installer for Raspberry Pi OS.
#
# Idempotent: every step checks whether it has already been done and skips it if
# so, so re-running is safe. On failure it prints the cause and a suggested fix.
#
# Usage:  ./install.sh
#
set -euo pipefail

# --------------------------------------------------------------------------- #
# Paths and constants
# --------------------------------------------------------------------------- #
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${INSTALL_DIR}/.venv"
CONFIG_FILE="${INSTALL_DIR}/config.toml"
EXAMPLE_CONFIG="${INSTALL_DIR}/config.example.toml"
STATE_DIR="/var/lib/weatherdisplay"
SERVICE_NAME="weatherdisplay.service"
SERVICE_TEMPLATE="${INSTALL_DIR}/systemd/${SERVICE_NAME}"
SERVICE_DEST="/etc/systemd/system/${SERVICE_NAME}"
BUTTON_SCRIPT="${INSTALL_DIR}/tools/pisugar-button.sh"
PISUGAR_HOST="127.0.0.1"
PISUGAR_PORT=8423
MIN_PY_MINOR=13     # require Python 3.<this>+; a newer OS Python is used if found

# Runtime + build needs. fonts-dejavu-core is the error-banner fallback font;
# python3 (>= 3.13 on Debian 13 "trixie") plus python3-venv give us the
# interpreter and the venv module. The toolchain (build-essential + python3-dev)
# is for Inky's C extensions (spidev/RPi.GPIO etc.). i2c-tools provides
# i2cget/i2cset for the button handler's LED-blink feedback.
APT_PACKAGES=(
  fonts-dejavu-core
  python3 python3-venv python3-dev
  build-essential
  git curl
  i2c-tools
)

# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #
if [[ -t 1 ]]; then
  C_INFO=$'\e[1;34m'; C_OK=$'\e[1;32m'; C_WARN=$'\e[1;33m'
  C_ERR=$'\e[1;31m'; C_OFF=$'\e[0m'
else
  C_INFO=""; C_OK=""; C_WARN=""; C_ERR=""; C_OFF=""
fi

info() { echo "${C_INFO}==>${C_OFF} $*"; }
ok()   { echo "${C_OK}  ok${C_OFF} $*"; }
warn() { echo "${C_WARN}warn${C_OFF} $*" >&2; }
die() {
  echo "${C_ERR}ERROR:${C_OFF} $1" >&2
  [[ $# -ge 2 ]] && echo "       fix: $2" >&2
  exit 1
}

# --------------------------------------------------------------------------- #
# Pre-flight
# --------------------------------------------------------------------------- #
[[ $EUID -eq 0 ]] && die "do not run install.sh as root; run it as your normal user" \
  "run './install.sh' as the pi user; it will use sudo only where needed"

command -v sudo >/dev/null 2>&1 || die "sudo is required but not found" \
  "install sudo, or run the apt/systemd steps manually"

if grep -qi raspberry /proc/cpuinfo /sys/firmware/devicetree/base/model 2>/dev/null; then
  IS_PI=1
else
  IS_PI=0
  warn "this does not look like a Raspberry Pi; skipping hardware steps (SPI, PiSugar, systemd service)"
fi

# --------------------------------------------------------------------------- #
# 1. Enable the SPI bus (needed by the Inky panel)
# --------------------------------------------------------------------------- #
enable_spi() {
  info "Enabling SPI"
  if ! command -v raspi-config >/dev/null 2>&1; then
    warn "raspi-config not found; enable SPI manually (sudo raspi-config -> Interface -> SPI)"
    return
  fi
  if [[ "$(sudo raspi-config nonint get_spi 2>/dev/null || echo 1)" == "0" ]]; then
    ok "SPI already enabled"
  else
    sudo raspi-config nonint do_spi 0 \
      || die "could not enable SPI" "run 'sudo raspi-config' and enable SPI under Interface Options"
    ok "SPI enabled (a reboot may be required for it to take effect)"
  fi

  # The Inky library drives the SPI chip-select (GPIO8) itself, but enabling
  # SPI makes the kernel claim GPIO8 as spi0 CS0 -> the panel fails with "pins
  # we need are in use". The spi0-0cs overlay tells SPI0 to expose no hardware
  # chip-selects, freeing GPIO8. See pimoroni/inky README (Chip Select error).
  local config="/boot/firmware/config.txt"
  [[ -f "$config" ]] || config="/boot/config.txt"
  if [[ ! -f "$config" ]]; then
    warn "no boot config.txt found; add 'dtoverlay=spi0-0cs' manually for the Inky panel"
  elif grep -qE '^[[:space:]]*dtoverlay=spi0-0cs([[:space:],]|$)' "$config"; then
    ok "spi0-0cs overlay already set"
  else
    echo "dtoverlay=spi0-0cs" | sudo tee -a "$config" >/dev/null \
      || die "could not edit ${config}" "add 'dtoverlay=spi0-0cs' to ${config} manually"
    ok "added spi0-0cs overlay to ${config} (reboot required for the panel)"
  fi
}

# --------------------------------------------------------------------------- #
# 2. Install APT packages (fonts + Python build deps)
# --------------------------------------------------------------------------- #
install_apt() {
  info "Installing system packages"
  local missing=()
  for pkg in "${APT_PACKAGES[@]}"; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
  done
  if [[ ${#missing[@]} -eq 0 ]]; then
    ok "all system packages already installed"
    return
  fi
  info "  installing: ${missing[*]}"
  sudo apt-get update || die "apt-get update failed" "check your network and /etc/apt/sources.list"
  sudo apt-get install -y "${missing[@]}" \
    || die "apt-get install failed for: ${missing[*]}" \
           "run 'sudo apt-get install ${missing[*]}' and read the error above"
  ok "system packages installed"
}

# --------------------------------------------------------------------------- #
# 3. Locate the newest suitable Python interpreter (>= 3.<MIN_PY_MINOR>)
# --------------------------------------------------------------------------- #
find_python() {
  # Echo the path of the newest Python that meets the >= 3.MIN_PY_MINOR floor,
  # or return non-zero if there is none.
  #
  # `python3.NN` names carry their minor version, so we pick the highest from
  # the names alone (matching two digits only, since 3.9 and below can't clear a
  # >= 3.10 floor). The unversioned `python3` hides its version, so it is the
  # only one we run, and only as a fallback when no versioned binary qualifies.
  local name minor best_minor=0 best_path=""
  while read -r name; do
    [[ "$name" =~ ^python3\.([0-9][0-9])$ ]] || continue
    minor=$(( 10#${BASH_REMATCH[1]} ))  # 10# so e.g. 3.09 isn't read as octal
    if (( minor >= MIN_PY_MINOR && minor > best_minor )); then
      best_minor=$minor
      best_path="$(command -v "$name")"
    fi
  done < <(compgen -c python3. 2>/dev/null | sort -u)
  if [[ -n "$best_path" ]]; then
    echo "$best_path"
    return 0
  fi

  local path
  path="$(command -v python3 2>/dev/null)" || return 1
  minor="$("$path" -c 'import sys; print(sys.version_info[1])' 2>/dev/null)" \
    || return 1
  [[ "$minor" =~ ^[0-9]+$ ]] && (( minor >= MIN_PY_MINOR )) || return 1
  echo "$path"
}

# --------------------------------------------------------------------------- #
# 4. Create the virtualenv and install the project
# --------------------------------------------------------------------------- #
install_project() {
  info "Creating virtualenv and installing WeatherDisplay"
  local py
  py="$(find_python)" || die \
    "no Python 3.${MIN_PY_MINOR}+ found on PATH" \
    "install it (e.g. 'sudo apt-get install python3.13 python3.13-venv') and re-run ./install.sh"
  info "  using $("$py" -V 2>&1) at ${py}"

  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    "$py" -m venv "$VENV_DIR" \
      || die "could not create venv at ${VENV_DIR}" \
        "ensure the venv module is present (sudo apt-get install python3-venv) and check disk space"
  fi
  "${VENV_DIR}/bin/python" -m pip install --quiet --upgrade pip
  # The [pi] extra pulls in the hardware 'inky' package that drives the panel.
  "${VENV_DIR}/bin/pip" install --quiet -e "${INSTALL_DIR}[pi]" \
    || die "pip install failed" "re-run with '${VENV_DIR}/bin/pip install -e ${INSTALL_DIR}[pi]' to see details"
  ok "WeatherDisplay installed into ${VENV_DIR}"
}

# --------------------------------------------------------------------------- #
# 5. Create the config file from the example
# --------------------------------------------------------------------------- #
setup_config() {
  info "Setting up configuration"
  if [[ -f "$CONFIG_FILE" ]]; then
    ok "config.toml already exists (left unchanged)"
  else
    cp "$EXAMPLE_CONFIG" "$CONFIG_FILE"
    ok "created ${CONFIG_FILE}"
    warn "edit ${CONFIG_FILE} and set your latitude, longitude and timezone"
  fi
}

# --------------------------------------------------------------------------- #
# 6. Check the PiSugar power-manager server is reachable
# --------------------------------------------------------------------------- #
PISUGAR_REACHABLE=0

check_pisugar() {
  info "Checking PiSugar power-manager server"
  if timeout 3 bash -c "exec 3<>/dev/tcp/${PISUGAR_HOST}/${PISUGAR_PORT}" 2>/dev/null; then
    PISUGAR_REACHABLE=1
    ok "pisugar-server is reachable on ${PISUGAR_HOST}:${PISUGAR_PORT}"
  else
    warn "pisugar-server not reachable on :${PISUGAR_PORT} (scheduled wake-up needs it)"
    echo "       install it with:"
    echo "         curl https://cdn.pisugar.com/release/pisugar-power-manager.sh | sudo bash"
  fi
}

# --------------------------------------------------------------------------- #
# 7. Register the PiSugar custom-button actions
# --------------------------------------------------------------------------- #
# Sends one command to pisugar-server and echoes its reply line.
pisugar_command() {
  local reply
  exec 3<>"/dev/tcp/${PISUGAR_HOST}/${PISUGAR_PORT}" || return 1
  printf '%s\n' "$1" >&3
  IFS= read -r -t 3 reply <&3 || reply=""
  exec 3<&- 3>&-
  echo "$reply"
}

setup_pisugar_button() {
  info "Configuring the PiSugar custom button"
  if [[ "$PISUGAR_REACHABLE" -ne 1 ]]; then
    warn "pisugar-server unreachable; skipping button setup (re-run install.sh once it is up)"
    return
  fi
  chmod +x "$BUTTON_SCRIPT"

  # set_button_* commands persist into pisugar-server's config, so this
  # survives reboots; re-applying the same values is a no-op.
  local cmd reply failed=0
  for cmd in \
    "set_button_shell single ${BUTTON_SCRIPT} single" \
    "set_button_enable single 1" \
    "set_button_shell double ${BUTTON_SCRIPT} double" \
    "set_button_enable double 1" \
    "set_button_shell long ${BUTTON_SCRIPT} long" \
    "set_button_enable long 1"; do
    reply="$(pisugar_command "$cmd" 2>/dev/null)" || reply=""
    if [[ "$reply" != *done* ]]; then
      warn "pisugar-server rejected '${cmd}' (reply: '${reply}')"
      failed=1
    fi
  done
  if [[ "$failed" -eq 0 ]]; then
    ok "custom button set: single tap updates, double tap toggles stay-awake, long tap pulls + updates"
  fi
}

# --------------------------------------------------------------------------- #
# 8. Make boot wait for a real NTP time sync (bounded)
# --------------------------------------------------------------------------- #
# Until NTP syncs, the boot clock holds the previous shutdown's time.
# systemd-time-wait-sync holds back time-sync.target until the clock is
# synced.
TIME_SYNC_DROPIN_DIR="/etc/systemd/system/systemd-time-wait-sync.service.d"
TIME_SYNC_DROPIN="${TIME_SYNC_DROPIN_DIR}/10-weatherdisplay-timeout.conf"

setup_time_sync_wait() {
  info "Configuring boot to wait for NTP time sync"

  local rendered
  rendered="$(mktemp)"
  printf '[Service]\nTimeoutStartSec=180\n' > "$rendered"
  if [[ -f "$TIME_SYNC_DROPIN" ]] && sudo cmp -s "$rendered" "$TIME_SYNC_DROPIN"; then
    ok "time-wait-sync timeout drop-in already up to date"
    rm -f "$rendered"
  else
    sudo mkdir -p "$TIME_SYNC_DROPIN_DIR"
    sudo cp "$rendered" "$TIME_SYNC_DROPIN"
    rm -f "$rendered"
    sudo systemctl daemon-reload
    ok "installed ${TIME_SYNC_DROPIN}"
  fi

  if [[ "$(sudo systemctl is-enabled systemd-time-wait-sync.service 2>/dev/null)" == "enabled" ]]; then
    ok "systemd-time-wait-sync already enabled"
  else
    sudo systemctl enable systemd-time-wait-sync.service >/dev/null 2>&1 \
      || die "could not enable systemd-time-wait-sync.service" \
             "run 'sudo systemctl enable systemd-time-wait-sync.service'"
    ok "enabled systemd-time-wait-sync.service"
  fi
}

# --------------------------------------------------------------------------- #
# 9. Install and enable the systemd service
# --------------------------------------------------------------------------- #
install_service() {
  info "Installing systemd service"
  sudo mkdir -p "$STATE_DIR"

  local rendered
  rendered="$(mktemp)"
  sed -e "s|@INSTALL_DIR@|${INSTALL_DIR}|g" \
      -e "s|@VENV@|${VENV_DIR}|g" \
      -e "s|@CONFIG@|${CONFIG_FILE}|g" \
      -e "s|@STATE_DIR@|${STATE_DIR}|g" \
      "$SERVICE_TEMPLATE" > "$rendered"

  if [[ -f "$SERVICE_DEST" ]] && sudo cmp -s "$rendered" "$SERVICE_DEST"; then
    ok "systemd service already up to date"
    rm -f "$rendered"
  else
    sudo cp "$rendered" "$SERVICE_DEST"
    rm -f "$rendered"
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 \
      || die "could not enable ${SERVICE_NAME}" "run 'sudo systemctl enable ${SERVICE_NAME}'"
    ok "installed and enabled ${SERVICE_NAME}"
  fi
}

# --------------------------------------------------------------------------- #
# Run all steps
# --------------------------------------------------------------------------- #
main() {
  echo "WeatherDisplay installer"
  echo "  install dir: ${INSTALL_DIR}"
  echo
  [[ "$IS_PI" -eq 1 ]] && enable_spi
  install_apt
  install_project
  setup_config
  if [[ "$IS_PI" -eq 1 ]]; then
    check_pisugar
    setup_pisugar_button
    setup_time_sync_wait
    install_service
  fi
  echo
  ok "Done."
  echo
  echo "Next steps:"
  echo "  1. Edit your settings:    ${CONFIG_FILE}"
  echo "  2. Test without shutdown: set auto_shutdown=false, then"
  echo "                            ${VENV_DIR}/bin/weatherdisplay --config ${CONFIG_FILE} update"
  if [[ "$IS_PI" -eq 1 ]]; then
    echo "  3. Watch logs:            journalctl -u ${SERVICE_NAME} -f"
    echo "  4. Re-enable shutdown in config when you are happy."
    echo
    echo "See README.md for maintenance tips"
  fi
}

main "$@"
