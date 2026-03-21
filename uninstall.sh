#!/usr/bin/env bash
# PaperHat uninstaller — stops the service and removes the systemd unit.
# Does NOT delete the project directory, venv, or config.toml.

set -euo pipefail

SERVICE="paperhat"
UNIT="/etc/systemd/system/$SERVICE.service"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

info() { echo -e "${GREEN}▸${NC} $*"; }

if [ -f "$UNIT" ]; then
    sudo systemctl stop "$SERVICE" 2>/dev/null || true
    sudo systemctl disable "$SERVICE" 2>/dev/null || true
    sudo rm -f "$UNIT"
    sudo systemctl daemon-reload
    info "Service removed"
else
    info "Service not installed — nothing to do"
fi

echo
echo "  To fully remove PaperHat, delete the project directory."
echo
