"""Configuration for the PaperHat e-Paper touch application.

Defaults are defined in the dataclasses below. To override, create a
``config.toml`` next to this file (see ``config.example.toml``).
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "config.toml"


def _load_toml() -> dict:
    if not _CONFIG_PATH.exists():
        return {}
    with open(_CONFIG_PATH, "rb") as f:
        data = tomllib.load(f)
    logger.info("Loaded config from %s", _CONFIG_PATH)
    return data


@dataclass(frozen=True, slots=True)
class HardwareConfig:
    """Pin assignments and hardware parameters (fixed by HAT wiring)."""

    # EPD control pins (BCM)
    rst: int = 17
    dc: int = 25
    busy: int = 24

    # Touch pins (BCM)
    touch_int: int = 27
    touch_rst: int = 22

    # I2C (touch panel)
    touch_addr: int = 0x14
    i2c_bus: int = 1

    # SPI (display)
    spi_bus: int = 0
    spi_device: int = 0
    spi_speed: int = 4_000_000

    # Display resolution (controller orientation: portrait)
    epd_width: int = 122
    epd_height: int = 250


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Application-level settings (overridable via config.toml)."""

    # Location — all services key off this single (lat, lon)
    lat: float = 40.6742       # Grand Army Plaza, Brooklyn
    lon: float = -73.9708
    nws_agent: str = "paperhat-app"

    # Minimum minutes for a departure to be shown (e.g. 3 = hide trains
    # arriving in less than 3 minutes, since you can't make them anyway)
    min_departure_minutes: int = 0

    # Touch coordinate mapping (portrait panel → landscape UI)
    touch_swap_xy: bool = True
    touch_invert_x: bool = False
    touch_invert_y: bool = True


# ── load config ─────────────────────────────────────────────────

HW = HardwareConfig()

_toml = _load_toml()
_app_overrides = {k: v for k, v in _toml.items() if k in AppConfig.__dataclass_fields__}
APP = AppConfig(**_app_overrides)

# Landscape display dimensions used by UI code
SCREEN_W = HW.epd_height   # 250
SCREEN_H = HW.epd_width    # 122
