"""Configuration for the PaperHat e-Paper touch application."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HardwareConfig:
    """Pin assignments and hardware parameters."""

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
    """Application-level settings."""

    # Location — all services key off this single (lat, lon)
    lat: float = 40.6742       # Grand Army Plaza, Brooklyn
    lon: float = -73.9708
    nws_agent: str = "paperhat-app"

    # Touch coordinate mapping (portrait panel → landscape UI)
    touch_swap_xy: bool = True
    touch_invert_x: bool = False
    touch_invert_y: bool = False


HW = HardwareConfig()
APP = AppConfig()

# Landscape display dimensions used by UI code
SCREEN_W = HW.epd_height   # 250
SCREEN_H = HW.epd_width    # 122
