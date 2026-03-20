"""GT1151 capacitive touch driver for Waveshare 2.13" Touch e-Paper HAT.

Communicates over I2C at address 0x14.  Five-point multitouch, but
we typically only care about the first point for UI taps.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Self

logger = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    import smbus2
except ImportError:  # allow import off-Pi for testing
    GPIO = None  # type: ignore[assignment]
    smbus2 = None  # type: ignore[assignment]

from config import APP, HW, SCREEN_H, SCREEN_W


@dataclass(frozen=True, slots=True)
class TouchPoint:
    """A single touch coordinate in landscape display space."""

    x: int
    y: int


class TouchPanel:
    """GT1151 capacitive touch panel (I2C).

    Use as a context manager::

        with TouchPanel() as touch:
            points = touch.wait(timeout=5)
    """

    # GT1151 / Goodix 16-bit register addresses
    _STATUS = [0x81, 0x4E]
    _POINTS = [0x81, 0x50]
    _PRODUCT_ID = [0x81, 0x40]   # 4 bytes ASCII
    _FIRMWARE = [0x81, 0x44]     # 2 bytes LE
    _CONFIG = [0x80, 0x47]       # config area (version, x_max, y_max, …)

    def __enter__(self) -> Self:
        if GPIO is None:
            raise RuntimeError("RPi.GPIO required — run on Raspberry Pi")
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(HW.touch_rst, GPIO.OUT)
        GPIO.setup(HW.touch_int, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self._reset()
        self.bus = smbus2.SMBus(HW.i2c_bus)
        self._log_device_info()
        return self

    def __exit__(self, *_: object) -> None:
        self.bus.close()

    # ── public API ──────────────────────────────────────────────

    def read(self) -> list[TouchPoint]:
        """Non-blocking read of current touch points (empty list = none)."""
        try:
            status = self._i2c_read(self._STATUS, 1)[0]
        except OSError:
            return []

        ready = (status >> 7) & 1
        n_points = status & 0x0F

        points: list[TouchPoint] = []
        if ready and 0 < n_points <= 5:
            data = self._i2c_read(self._POINTS, n_points * 8)
            logger.debug("touch status=0x%02X n=%d data=%s", status, n_points, data[:16])
            for i in range(n_points):
                off = i * 8
                # GT1158 has no track-ID prefix: X at bytes 0-1, Y at bytes 2-3
                raw_x = data[off] | (data[off + 1] << 8)
                raw_y = data[off + 2] | (data[off + 3] << 8)
                logger.debug("touch raw=(%d, %d)", raw_x, raw_y)
                points.append(self._map(raw_x, raw_y))

        if ready:
            self._i2c_write(self._STATUS, [0x00])  # clear buffer

        return points

    def wait(self, timeout: float | None = None) -> list[TouchPoint]:
        """Block until a touch event or *timeout* seconds elapse."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if points := self.read():
                return points
            if deadline and time.monotonic() > deadline:
                return []
            time.sleep(0.05)

    # ── internals ───────────────────────────────────────────────

    _KNOWN_MODELS = {"1158", "1151", "911"}

    def _log_device_info(self) -> None:
        """Read and log touch controller identity and configuration."""
        try:
            pid_raw = self._i2c_read(self._PRODUCT_ID, 4)
            product_id = bytes(pid_raw).decode("ascii", errors="replace").rstrip("\x00")

            fw = self._i2c_read(self._FIRMWARE, 2)
            fw_ver = fw[0] | (fw[1] << 8)

            logger.info(
                "Touch IC: product=%r fw=0x%04X i2c_addr=0x%02X",
                product_id, fw_ver, HW.touch_addr,
            )

            if product_id not in self._KNOWN_MODELS:
                logger.warning(
                    "Unrecognised touch controller %r — touch parsing may "
                    "be incorrect. Known models: %s",
                    product_id, ", ".join(sorted(self._KNOWN_MODELS)),
                )
        except Exception:
            logger.warning("Could not read touch device info", exc_info=True)

    def _reset(self) -> None:
        GPIO.output(HW.touch_rst, 1)
        time.sleep(0.1)
        GPIO.output(HW.touch_rst, 0)
        time.sleep(0.1)
        GPIO.output(HW.touch_rst, 1)
        time.sleep(0.1)

    def _i2c_read(self, reg: list[int], length: int) -> list[int]:
        w = smbus2.i2c_msg.write(HW.touch_addr, reg)
        r = smbus2.i2c_msg.read(HW.touch_addr, length)
        self.bus.i2c_rdwr(w, r)
        return list(r)

    def _i2c_write(self, reg: list[int], data: list[int]) -> None:
        self.bus.i2c_rdwr(smbus2.i2c_msg.write(HW.touch_addr, reg + data))

    def _map(self, raw_x: int, raw_y: int) -> TouchPoint:
        """Map raw touch coordinates → landscape display coordinates."""
        if APP.touch_swap_xy:
            raw_x, raw_y = raw_y, raw_x
        x = (SCREEN_W - 1 - raw_x) if APP.touch_invert_x else raw_x
        y = (SCREEN_H - 1 - raw_y) if APP.touch_invert_y else raw_y
        pt = TouchPoint(
            x=max(0, min(x, SCREEN_W - 1)),
            y=max(0, min(y, SCREEN_H - 1)),
        )
        logger.debug("touch raw=(%d,%d) → mapped=(%d,%d)", raw_x, raw_y, pt.x, pt.y)
        return pt
