"""SSD1680 e-Paper display driver for Waveshare 2.13" Touch HAT.

250×122 pixels, black/white, full-refresh only.
"""

from __future__ import annotations

import time
from typing import Self

from PIL import Image

try:
    import RPi.GPIO as GPIO
    import spidev
except ImportError:  # allow import off-Pi for testing
    GPIO = None  # type: ignore[assignment]
    spidev = None  # type: ignore[assignment]

from config import HW


class EPD:
    """2.13" e-Paper display (250×122, black & white).

    Use as a context manager to ensure proper init and cleanup::

        with EPD() as display:
            display.show(my_image)
    """

    WIDTH = HW.epd_width    # 122  (controller X-axis)
    HEIGHT = HW.epd_height  # 250  (controller Y-axis)

    def __enter__(self) -> Self:
        if GPIO is None:
            raise RuntimeError("RPi.GPIO required — run on Raspberry Pi")
        self._init_gpio()
        self._init_spi()
        self._hw_reset()
        self._init_display()
        return self

    def __exit__(self, *_: object) -> None:
        self.sleep()
        self.spi.close()

    # ── public API ──────────────────────────────────────────────

    def show(self, image: Image.Image) -> None:
        """Full-refresh the display with a Pillow Image."""
        self._set_cursor(0, 0)
        self._command(0x24)
        self._data(self._to_buffer(image))
        self._update()

    def clear(self) -> None:
        """Clear the display to white."""
        self._set_cursor(0, 0)
        self._command(0x24)
        self._data(b"\xFF" * (self.WIDTH // 8 * self.HEIGHT))
        self._update()

    def sleep(self) -> None:
        """Enter deep-sleep mode (display retains image)."""
        self._command(0x10)
        self._data(0x01)
        time.sleep(0.1)

    # ── initialisation ──────────────────────────────────────────

    def _init_gpio(self) -> None:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(HW.rst, GPIO.OUT)
        GPIO.setup(HW.dc, GPIO.OUT)
        GPIO.setup(HW.busy, GPIO.IN)

    def _init_spi(self) -> None:
        self.spi = spidev.SpiDev()
        self.spi.open(HW.spi_bus, HW.spi_device)
        self.spi.max_speed_hz = HW.spi_speed
        self.spi.mode = 0b00

    def _hw_reset(self) -> None:
        GPIO.output(HW.rst, 1)
        time.sleep(0.02)
        GPIO.output(HW.rst, 0)
        time.sleep(0.002)
        GPIO.output(HW.rst, 1)
        time.sleep(0.02)

    def _init_display(self) -> None:
        self._wait_busy()
        self._command(0x12)                         # SW reset
        self._wait_busy()
        self._command(0x01); self._data([0xF9, 0x00, 0x00])   # driver output
        self._command(0x11); self._data(0x03)                  # data entry X+Y+
        self._command(0x44); self._data([0x00, 0x0F])          # RAM X 0…15
        self._command(0x45); self._data([0x00, 0x00, 0xF9, 0x00])  # RAM Y 0…249
        self._command(0x3C); self._data(0x05)                  # border waveform
        self._command(0x21); self._data([0x00, 0x80])          # update ctrl 1
        self._command(0x18); self._data(0x80)                  # temp sensor
        self._set_cursor(0, 0)
        self._wait_busy()

    # ── low-level SPI ───────────────────────────────────────────

    def _command(self, cmd: int) -> None:
        GPIO.output(HW.dc, 0)
        self.spi.writebytes2([cmd])

    def _data(self, payload: int | list[int] | bytes) -> None:
        GPIO.output(HW.dc, 1)
        if isinstance(payload, int):
            self.spi.writebytes2([payload])
        else:
            self.spi.writebytes2(list(payload) if isinstance(payload, bytes) else payload)

    def _update(self) -> None:
        """Trigger a full display refresh and wait for completion."""
        self._command(0x22)
        self._data(0xF7)
        self._command(0x20)
        self._wait_busy()

    def _wait_busy(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while GPIO.input(HW.busy):
            if time.monotonic() > deadline:
                raise TimeoutError("EPD busy timeout")
            time.sleep(0.01)

    def _set_cursor(self, x: int, y: int) -> None:
        self._command(0x4E); self._data(x)
        self._command(0x4F); self._data([y & 0xFF, (y >> 8) & 0xFF])

    # ── image conversion ────────────────────────────────────────

    def _to_buffer(self, image: Image.Image) -> bytes:
        """Convert a Pillow Image to the controller's byte layout."""
        img = image.convert("1")
        w, h = img.size
        pixels = img.load()
        buf = bytearray(b"\xFF" * (self.WIDTH // 8 * self.HEIGHT))

        if w == self.HEIGHT and h == self.WIDTH:
            # Landscape (250×122) → rotate into portrait buffer
            for py in range(h):
                for px in range(w):
                    if pixels[px, py] == 0:
                        nx, ny = py, self.HEIGHT - 1 - px
                        buf[(nx + ny * self.WIDTH) // 8] &= ~(0x80 >> (nx % 8))
        else:
            # Portrait (122×250) → direct copy
            for py in range(min(h, self.HEIGHT)):
                for px in range(min(w, self.WIDTH)):
                    if pixels[px, py] == 0:
                        buf[(px + py * self.WIDTH) // 8] &= ~(0x80 >> (px % 8))

        return bytes(buf)
