"""Tests for the EPD display driver."""

from __future__ import annotations

from unittest.mock import call, patch

import pytest
from PIL import Image

from config import HW


class TestEPDInit:
    def test_raises_without_gpio(self):
        from drivers.epd import EPD

        with patch("drivers.epd.GPIO", None):
            with pytest.raises(RuntimeError, match="RPi.GPIO"):
                EPD().__enter__()

    def test_gpio_setup(self, epd, mock_gpio):
        mock_gpio.setmode.assert_called_with(mock_gpio.BCM)
        mock_gpio.setup.assert_any_call(HW.rst, mock_gpio.OUT)
        mock_gpio.setup.assert_any_call(HW.dc, mock_gpio.OUT)
        mock_gpio.setup.assert_any_call(HW.busy, mock_gpio.IN)

    def test_spi_setup(self, epd, mock_spi):
        mock_spi.open.assert_called_with(HW.spi_bus, HW.spi_device)
        assert mock_spi.max_speed_hz == HW.spi_speed
        assert mock_spi.mode == 0b00

    def test_hw_reset_sequence(self, epd, mock_gpio):
        rst_calls = [c for c in mock_gpio.output.call_args_list if c[0][0] == HW.rst]
        values = [c[0][1] for c in rst_calls]
        # Should see 1, 0, 1 for the reset pulse
        assert values[:3] == [1, 0, 1]

    def test_init_sends_sw_reset(self, epd, mock_spi):
        all_writes = [c[0][0] for c in mock_spi.writebytes2.call_args_list]
        assert [0x12] in all_writes


class TestEPDExit:
    def test_sends_sleep_command(self, mock_spi, mock_gpio):
        from drivers.epd import EPD

        display = EPD()
        display.__enter__()
        mock_spi.writebytes2.reset_mock()
        display.__exit__(None, None, None)

        all_writes = [c[0][0] for c in mock_spi.writebytes2.call_args_list]
        assert [0x10] in all_writes  # sleep command
        mock_spi.close.assert_called_once()


class TestEPDClear:
    def test_sends_white_buffer(self, epd, mock_spi):
        mock_spi.writebytes2.reset_mock()
        epd.clear()

        # Find the largest data payload sent — should be the buffer
        all_writes = [c[0][0] for c in mock_spi.writebytes2.call_args_list]
        buffers = [w for w in all_writes if len(w) > 100]
        assert len(buffers) == 1
        assert all(b == 0xFF for b in buffers[0])
        assert len(buffers[0]) == (122 + 7) // 8 * 250  # 3750 bytes


class TestEPDShow:
    def test_show_calls_update_sequence(self, epd, mock_spi):
        img = Image.new("1", (250, 122), 255)
        mock_spi.writebytes2.reset_mock()
        epd.show(img)

        all_writes = [c[0][0] for c in mock_spi.writebytes2.call_args_list]
        # Should contain: command 0x24 (write RAM), data, command 0x22 (update ctrl),
        # data 0xF7, command 0x20 (activate)
        flat_cmds = [w[0] for w in all_writes if len(w) == 1]
        assert 0x24 in flat_cmds
        assert 0x22 in flat_cmds
        assert 0x20 in flat_cmds


class TestImageToBuffer:
    def test_landscape_correct_size(self, epd):
        img = Image.new("1", (250, 122), 255)
        buf = epd._to_buffer(img)
        assert len(buf) == (122 + 7) // 8 * 250

    def test_portrait_correct_size(self, epd):
        img = Image.new("1", (122, 250), 255)
        buf = epd._to_buffer(img)
        assert len(buf) == (122 + 7) // 8 * 250

    def test_all_white(self, epd):
        img = Image.new("1", (250, 122), 255)
        buf = epd._to_buffer(img)
        assert all(b == 0xFF for b in buf)

    def test_all_black(self, epd):
        img = Image.new("1", (250, 122), 0)
        buf = epd._to_buffer(img)
        # Each row is 16 bytes (128 bits) but only 122 pixels are used.
        # The last 6 bits of each row are padding (stay 0xFF).
        from drivers.epd import EPD
        for row in range(EPD.HEIGHT):
            offset = row * EPD.ROW_BYTES
            # First 15 bytes (120 pixels) should be all black
            assert all(b == 0x00 for b in buf[offset:offset + 15])
            # Byte 15: bits 0-1 are black (pixels 121-120), bits 2-7 are padding
            assert buf[offset + 15] == 0b00111111  # 2 black bits + 6 padding bits

    def test_single_pixel(self, epd):
        img = Image.new("1", (250, 122), 255)
        img.putpixel((0, 0), 0)  # top-left black pixel
        buf = epd._to_buffer(img)
        # In landscape→portrait rotation, pixel (0,0) in landscape maps to
        # the portrait buffer. Verify not all-white.
        assert buf != b"\xFF" * len(buf)
        # Count cleared bits
        black_bits = sum(bin(b ^ 0xFF).count("1") for b in buf)
        assert black_bits == 1


class TestWaitBusy:
    def test_returns_when_not_busy(self, epd, mock_gpio):
        mock_gpio.input.return_value = 0
        epd._wait_busy()  # should not raise

    def test_timeout_raises(self, epd, mock_gpio):
        mock_gpio.input.return_value = 1  # always busy
        with patch("drivers.epd.time") as mock_time:
            mock_time.monotonic.side_effect = [0, 0, 11]  # jump past deadline
            mock_time.sleep = lambda _: None
            with pytest.raises(TimeoutError):
                epd._wait_busy(timeout=10.0)


class TestDataMethod:
    def test_accepts_int(self, epd, mock_spi):
        mock_spi.writebytes2.reset_mock()
        epd._data(0x42)
        mock_spi.writebytes2.assert_called_with([0x42])

    def test_accepts_list(self, epd, mock_spi):
        mock_spi.writebytes2.reset_mock()
        epd._data([0x01, 0x02])
        mock_spi.writebytes2.assert_called_with([0x01, 0x02])

    def test_accepts_bytes(self, epd, mock_spi):
        mock_spi.writebytes2.reset_mock()
        epd._data(b"\x01\x02")
        mock_spi.writebytes2.assert_called_with([0x01, 0x02])
