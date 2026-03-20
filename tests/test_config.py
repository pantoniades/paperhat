"""Tests for config dataclasses and TOML loading."""

import dataclasses
from unittest.mock import patch

import pytest

from config import APP, HW, SCREEN_H, SCREEN_W, AppConfig, HardwareConfig, _load_toml


class TestHardwareConfig:
    def test_defaults(self):
        hw = HardwareConfig()
        assert hw.rst == 17
        assert hw.dc == 25
        assert hw.busy == 24
        assert hw.touch_int == 27
        assert hw.touch_rst == 22
        assert hw.touch_addr == 0x14
        assert hw.i2c_bus == 1
        assert hw.spi_bus == 0
        assert hw.spi_device == 0
        assert hw.spi_speed == 4_000_000
        assert hw.epd_width == 122
        assert hw.epd_height == 250

    def test_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            HW.rst = 99

    def test_slots(self):
        assert hasattr(HardwareConfig, "__slots__")
        with pytest.raises((AttributeError, TypeError)):
            HW.nonexistent_attr = 1


class TestAppConfig:
    def test_defaults(self):
        app = AppConfig()
        assert app.lat == pytest.approx(40.6742)
        assert app.lon == pytest.approx(-73.9708)
        assert app.nws_agent == "paperhat-app"
        assert app.min_departure_minutes == 0
        assert app.touch_swap_xy is True
        assert app.touch_invert_x is False
        assert app.touch_invert_y is True

    def test_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            APP.lat = 0.0

    def test_custom_values(self):
        custom = AppConfig(lat=0.0, lon=0.0)
        assert custom.lat == 0.0
        assert custom.nws_agent == "paperhat-app"  # other defaults preserved


class TestScreenDimensions:
    def test_landscape_swap(self):
        assert SCREEN_W == 250
        assert SCREEN_H == 122

    def test_module_singletons(self):
        assert isinstance(HW, HardwareConfig)
        assert isinstance(APP, AppConfig)


class TestTomlLoading:
    def test_load_returns_empty_when_no_file(self, tmp_path):
        with patch("config._CONFIG_PATH", tmp_path / "nonexistent.toml"):
            assert _load_toml() == {}

    def test_load_parses_toml_file(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('lat = 41.0\nlon = -74.0\nmin_departure_minutes = 5\n')
        with patch("config._CONFIG_PATH", toml_file):
            data = _load_toml()
        assert data["lat"] == 41.0
        assert data["lon"] == -74.0
        assert data["min_departure_minutes"] == 5

    def test_toml_overrides_app_config(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('lat = 0.0\nmin_departure_minutes = 3\n')
        with patch("config._CONFIG_PATH", toml_file):
            data = _load_toml()
        overrides = {k: v for k, v in data.items() if k in AppConfig.__dataclass_fields__}
        app = AppConfig(**overrides)
        assert app.lat == 0.0
        assert app.min_departure_minutes == 3
        assert app.lon == pytest.approx(-73.9708)  # default preserved

    def test_unknown_toml_keys_ignored(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text('lat = 41.0\nbogus_key = "hello"\n')
        with patch("config._CONFIG_PATH", toml_file):
            data = _load_toml()
        overrides = {k: v for k, v in data.items() if k in AppConfig.__dataclass_fields__}
        app = AppConfig(**overrides)  # should not raise
        assert app.lat == 41.0
