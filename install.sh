#!/usr/bin/env bash
# PaperHat installer — sets up venv, config, and systemd service.
# Safe to re-run (idempotent).
#
# Usage:
#   ./install.sh          Install/update and start the service
#   ./install.sh --check  Verify prerequisites only

set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$INSTALL_DIR/.venv"
SERVICE="paperhat"
UNIT="/etc/systemd/system/$SERVICE.service"
USER="$(whoami)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}▸${NC} $*"; }
warn()  { echo -e "${YELLOW}▸${NC} $*"; }
fail()  { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

# ── prerequisites ───────────────────────────────────────────────

check_python() {
    python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null \
        || fail "Python 3.11+ required ($(python3 --version 2>&1))"
    info "Python $(python3 --version 2>&1 | cut -d' ' -f2)"
}

check_interfaces() {
    local needs_reboot=0

    if ! ls /dev/spidev* &>/dev/null; then
        warn "SPI not enabled — enabling now"
        sudo raspi-config nonint do_spi 0
        needs_reboot=1
    fi
    info "SPI enabled"

    if ! ls /dev/i2c* &>/dev/null; then
        warn "I2C not enabled — enabling now"
        sudo raspi-config nonint do_i2c 0
        needs_reboot=1
    fi
    info "I2C enabled"

    if [ "$needs_reboot" -eq 1 ]; then
        warn "SPI/I2C was just enabled — reboot required before first run"
        warn "Run: sudo reboot && then re-run ./install.sh"
        exit 0
    fi
}

install_system_deps() {
    local pkgs="python3-venv python3-dev libjpeg-dev zlib1g-dev"
    # Only install if any are missing
    if ! dpkg -s $pkgs &>/dev/null 2>&1; then
        info "Installing system packages: $pkgs"
        sudo apt-get update -qq
        sudo apt-get install -y -qq $pkgs
    else
        info "System packages already installed"
    fi
}

# ── python environment ──────────────────────────────────────────

setup_venv() {
    if [ ! -d "$VENV" ]; then
        info "Creating virtual environment"
        python3 -m venv "$VENV"
    fi

    info "Installing Python dependencies"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
}

# ── configuration ───────────────────────────────────────────────

setup_config() {
    if [ ! -f "$INSTALL_DIR/config.toml" ]; then
        cp "$INSTALL_DIR/config.example.toml" "$INSTALL_DIR/config.toml"
        warn "Created config.toml from template — edit with your location:"
        warn "  nano $INSTALL_DIR/config.toml"
    else
        info "config.toml already exists (not overwritten)"
    fi
}

# ── systemd service ─────────────────────────────────────────────

install_service() {
    info "Installing systemd service"

    sudo tee "$UNIT" > /dev/null <<EOF
[Unit]
Description=PaperHat e-Paper Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV/bin/python main.py
Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE" --quiet
    sudo systemctl restart "$SERVICE"
    info "Service installed and started"
}

# ── main ────────────────────────────────────────────────────────

main() {
    echo
    echo "  PaperHat Installer"
    echo "  ─────────────────"
    echo

    check_python

    if [ "${1:-}" = "--check" ]; then
        check_interfaces
        info "All prerequisites met"
        exit 0
    fi

    check_interfaces
    install_system_deps
    setup_venv
    setup_config
    install_service

    echo
    info "PaperHat is running!"
    echo
    echo "  Status:  sudo systemctl status $SERVICE"
    echo "  Logs:    sudo journalctl -u $SERVICE -f"
    echo "  Stop:    sudo systemctl stop $SERVICE"
    echo "  Restart: sudo systemctl restart $SERVICE"
    echo "  Config:  $INSTALL_DIR/config.toml"
    echo
}

main "$@"
