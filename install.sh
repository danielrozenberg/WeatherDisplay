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
PYENV_ROOT="${PYENV_ROOT:-${HOME}/.pyenv}"
MIN_SWAP_KB=900000  # ~900 MB; Chromium needs headroom on the 512 MB Pi Zero 2 W

# pyenv "suggested build environment" + our runtime needs.
APT_PACKAGES=(
  chromium-browser fonts-dejavu-core
  make build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev
  libsqlite3-dev libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev
  libffi-dev liblzma-dev libgdbm-dev libnss3-dev uuid-dev git curl
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

if ! grep -qi raspberry /proc/cpuinfo /sys/firmware/devicetree/base/model 2>/dev/null; then
  warn "this does not look like a Raspberry Pi; hardware steps may not apply"
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
}

# --------------------------------------------------------------------------- #
# 2. Install APT packages (Chromium, fonts, Python build deps)
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
# 3. Ensure enough swap for Chromium on the Pi Zero 2 W
# --------------------------------------------------------------------------- #
ensure_swap() {
  info "Checking swap space"
  local swap_kb
  swap_kb="$(awk '/SwapTotal/ {print $2}' /proc/meminfo)"
  if [[ "${swap_kb:-0}" -ge "$MIN_SWAP_KB" ]]; then
    ok "swap is $((swap_kb / 1024)) MB (>= $((MIN_SWAP_KB / 1024)) MB)"
    return
  fi
  if [[ -f /etc/dphys-swapfile ]]; then
    info "  raising dphys-swapfile to 1024 MB"
    sudo sed -i 's/^#\?CONF_SWAPSIZE=.*/CONF_SWAPSIZE=1024/' /etc/dphys-swapfile \
      || die "could not edit /etc/dphys-swapfile" "set CONF_SWAPSIZE=1024 manually and run 'sudo dphys-swapfile setup'"
    sudo dphys-swapfile setup && sudo dphys-swapfile swapon \
      || die "could not enable swap" "run 'sudo dphys-swapfile setup && sudo dphys-swapfile swapon'"
    ok "swap raised to 1024 MB"
  else
    warn "no dphys-swapfile found; create ~1 GB of swap manually to avoid Chromium OOM"
  fi
}

# --------------------------------------------------------------------------- #
# 4. Install pyenv and build the pinned Python
# --------------------------------------------------------------------------- #
install_python() {
  local version
  version="$(cat "${INSTALL_DIR}/.python-version")"
  info "Setting up Python ${version} via pyenv"

  if [[ ! -d "$PYENV_ROOT" ]]; then
    info "  installing pyenv into ${PYENV_ROOT}"
    curl -fsSL https://pyenv.run | bash \
      || die "pyenv installation failed" "see https://github.com/pyenv/pyenv#installation"
  else
    ok "pyenv already present"
  fi

  export PYENV_ROOT
  export PATH="${PYENV_ROOT}/bin:${PATH}"
  eval "$(pyenv init - bash)"

  if pyenv versions --bare | grep -qx "$version"; then
    ok "Python ${version} already built"
  else
    info "  building Python ${version} (this can take 20+ min on a Pi Zero)"
    pyenv install -s "$version" \
      || die "Python ${version} build failed" \
             "check the apt build deps installed above, then re-run ./install.sh"
    ok "Python ${version} built"
  fi
}

# --------------------------------------------------------------------------- #
# 5. Create the virtualenv and install the project
# --------------------------------------------------------------------------- #
install_project() {
  info "Creating virtualenv and installing WeatherDisplay"
  local version py
  version="$(cat "${INSTALL_DIR}/.python-version")"
  py="${PYENV_ROOT}/versions/${version}/bin/python"
  [[ -x "$py" ]] || die "expected Python at ${py} not found" "re-run ./install.sh to build it"

  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    "$py" -m venv "$VENV_DIR" || die "could not create venv at ${VENV_DIR}" "check disk space and permissions"
  fi
  "${VENV_DIR}/bin/python" -m pip install --quiet --upgrade pip
  # The [pi] extra pulls in the hardware 'inky' package. We deliberately do NOT
  # run 'playwright install' here: on the Pi we use the system Chromium.
  "${VENV_DIR}/bin/pip" install --quiet -e "${INSTALL_DIR}[pi]" \
    || die "pip install failed" "re-run with '${VENV_DIR}/bin/pip install -e ${INSTALL_DIR}[pi]' to see details"
  ok "WeatherDisplay installed into ${VENV_DIR}"
}

# --------------------------------------------------------------------------- #
# 6. Create the config file from the example
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
# 7. Check the PiSugar power-manager server is reachable
# --------------------------------------------------------------------------- #
check_pisugar() {
  info "Checking PiSugar power-manager server"
  if (exec 3<>/dev/tcp/127.0.0.1/8423) 2>/dev/null; then
    ok "pisugar-server is reachable on 127.0.0.1:8423"
  else
    warn "pisugar-server not reachable on :8423 (scheduled wake-up needs it)"
    echo "       install it with:"
    echo "         curl https://cdn.pisugar.com/release/pisugar-power-manager.sh | sudo bash"
  fi
}

# --------------------------------------------------------------------------- #
# 8. Install and enable the systemd service
# --------------------------------------------------------------------------- #
install_service() {
  info "Installing systemd service"
  sudo mkdir -p "$STATE_DIR"

  local chromium
  chromium="$(command -v chromium-browser || command -v chromium || echo /usr/bin/chromium-browser)"

  local rendered
  rendered="$(mktemp)"
  sed -e "s|@INSTALL_DIR@|${INSTALL_DIR}|g" \
      -e "s|@VENV@|${VENV_DIR}|g" \
      -e "s|@CONFIG@|${CONFIG_FILE}|g" \
      -e "s|@STATE_DIR@|${STATE_DIR}|g" \
      -e "s|@CHROMIUM@|${chromium}|g" \
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
  enable_spi
  install_apt
  ensure_swap
  install_python
  install_project
  setup_config
  check_pisugar
  install_service
  echo
  ok "Done."
  echo
  echo "Next steps:"
  echo "  1. Edit your settings:    ${CONFIG_FILE}"
  echo "  2. Test without shutdown: set auto_shutdown=false, then"
  echo "                            ${VENV_DIR}/bin/weatherdisplay --config ${CONFIG_FILE} update"
  echo "  3. Watch logs:            journalctl -u ${SERVICE_NAME} -f"
  echo "  4. Re-enable shutdown in config when you are happy."
  echo
  echo "Maintenance: 'sudo touch /boot/firmware/weatherdisplay-stayawake' keeps"
  echo "the Pi awake after an update so you can SSH in."
}

main "$@"
