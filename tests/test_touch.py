"""Tests for the TouchPanel driver."""

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock, patch

import pytest

from config import HW, SCREEN_H, SCREEN_W
from drivers.touch import TouchPanel, TouchPoint


class TestTouchPoint:
    def test_fields(self):
        pt = TouchPoint(x=100, y=50)
        assert pt.x == 100
        assert pt.y == 50

    def test_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            TouchPoint(0, 0).x = 5

    def test_has_slots(self):
        assert hasattr(TouchPoint, "__slots__")


class TestTouchPanelInit:
    def test_raises_without_gpio(self):
        with patch("drivers.touch.GPIO", None):
            with pytest.raises(RuntimeError, match="RPi.GPIO"):
                TouchPanel().__enter__()

    def test_gpio_setup(self, touch_panel, mock_gpio):
        mock_gpio = mock_gpio  # the fixture yields (bus, smbus_mod); gpio comes from mock_gpio dep
        # Touch panel should set up touch_rst as OUT and touch_int as IN
        from drivers.touch import GPIO
        GPIO.setup.assert_any_call(HW.touch_rst, GPIO.OUT)
        GPIO.setup.assert_any_call(HW.touch_int, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def test_reset_toggles_rst(self, mock_gpio, mock_smbus):
        panel = TouchPanel()
        panel.__enter__()
        rst_calls = [c for c in mock_gpio.output.call_args_list if c[0][0] == HW.touch_rst]
        values = [c[0][1] for c in rst_calls]
        assert values == [1, 0, 1]
        panel.__exit__(None, None, None)

    def test_exit_closes_bus(self, mock_smbus):
        bus, _ = mock_smbus
        panel = TouchPanel()
        panel.__enter__()
        panel.__exit__(None, None, None)
        bus.close.assert_called_once()


class TestTouchPanelRead:
    def test_no_touch_returns_empty(self, touch_panel, mock_smbus):
        bus, smbus_mod = mock_smbus
        # Status byte: not ready (bit 7 = 0)
        read_msg = MagicMock()
        read_msg.__iter__ = lambda self: iter([0x00])
        smbus_mod.i2c_msg.read.return_value = read_msg

        assert touch_panel.read() == []

    def test_one_point(self, touch_panel, mock_smbus):
        # Mock _i2c_read directly: first call returns status, second returns point data
        # GT1158 format: no track ID — bytes 0-1 = X, bytes 2-3 = Y
        touch_panel._i2c_read = MagicMock(side_effect=[
            [0x81],                              # status: ready, 1 point
            [50, 0, 30, 0, 0, 0, 0, 0],         # x=50, y=30
        ])
        touch_panel._i2c_write = MagicMock()

        points = touch_panel.read()

        assert len(points) == 1
        assert isinstance(points[0], TouchPoint)

    def test_oserror_returns_empty(self, touch_panel, mock_smbus):
        bus, _ = mock_smbus
        bus.i2c_rdwr.side_effect = OSError("I2C error")
        assert touch_panel.read() == []


class TestTouchMapping:
    def test_swap_xy(self, touch_panel):
        # Default config: touch_swap_xy=True
        pt = touch_panel._map(100, 200)
        assert pt.x == 200  # y becomes x
        assert pt.y == 100  # x becomes y

    def test_clamps_to_bounds(self, touch_panel):
        pt = touch_panel._map(9999, 9999)
        assert pt.x <= SCREEN_W - 1
        assert pt.y <= SCREEN_H - 1

    def test_clamps_negative(self, touch_panel):
        # After swap, if values would go negative with invert
        pt = touch_panel._map(0, 0)
        assert pt.x >= 0
        assert pt.y >= 0


class TestTouchWait:
    def test_returns_on_touch(self, touch_panel):
        touch_panel.read = MagicMock(
            side_effect=[[], [], [TouchPoint(50, 50)]]
        )
        with patch("drivers.touch.time") as mock_time:
            mock_time.sleep = lambda _: None
            mock_time.monotonic.side_effect = [0, 0, 0, 0, 0, 0]
            result = touch_panel.wait(timeout=5)

        assert len(result) == 1
        assert result[0] == TouchPoint(50, 50)

    def test_timeout_returns_empty(self, touch_panel):
        touch_panel.read = MagicMock(return_value=[])
        with patch("drivers.touch.time") as mock_time:
            mock_time.sleep = lambda _: None
            mock_time.monotonic.side_effect = [0, 0, 10]  # jump past deadline
            result = touch_panel.wait(timeout=5)

        assert result == []
