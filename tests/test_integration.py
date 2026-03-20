"""Integration tests: multi-layer interactions without real hardware or network."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PIL import Image

from drivers.touch import TouchPoint
from services.mta import Arrival, Station, StopInfo
from ui import HomeScreen, MessageScreen, StationScreen, SubwayScreen, WeatherScreen


class TestRenderedImagesAreValidForEPD:
    """Every screen's rendered image must convert to a valid EPD buffer."""

    def _assert_valid_buffer(self, img: Image.Image) -> None:
        from drivers.epd import EPD

        epd = EPD()
        buf = epd._to_buffer(img)
        assert isinstance(buf, bytes)
        assert len(buf) == (122 + 7) // 8 * 250  # 3750

    def test_home_screen(self):
        self._assert_valid_buffer(HomeScreen().render())

    def test_weather_screen(self, sample_weather):
        self._assert_valid_buffer(WeatherScreen(sample_weather).render())

    def test_subway_screen(self, sample_stations):
        self._assert_valid_buffer(SubwayScreen(sample_stations, [[] for _ in sample_stations]).render())

    def test_station_screen(self, sample_arrivals, sample_station):
        self._assert_valid_buffer(StationScreen(sample_arrivals, sample_station).render())

    def test_message_screen(self):
        self._assert_valid_buffer(MessageScreen("Test").render())

    def test_empty_station_screen(self, sample_station):
        self._assert_valid_buffer(StationScreen([], sample_station).render())


class TestTouchToActionFlow:
    """Verify touch coordinates produce the right actions across screens."""

    def test_home_left_tap_to_weather_action(self):
        home = HomeScreen()
        action = home.on_touch(TouchPoint(50, 60))
        assert type(action).__name__ == "ShowWeather"

    def test_home_right_tap_to_subway_action(self):
        home = HomeScreen()
        action = home.on_touch(TouchPoint(200, 60))
        assert type(action).__name__ == "ShowSubway"

    def test_subway_station_tap_carries_data(self, sample_stations, sample_arrivals):
        screen = SubwayScreen(sample_stations, [sample_arrivals, [], []])
        action = screen.on_touch(TouchPoint(120, screen._TOP + 5))
        assert hasattr(action, "station")
        assert action.station is sample_stations[0]
        assert action.station is sample_stations[0]

    def test_back_from_weather(self, sample_weather):
        screen = WeatherScreen(sample_weather)
        action = screen.on_touch(TouchPoint(10, 10))
        assert type(action).__name__ == "GoBack"

    def test_back_from_station(self, sample_arrivals, sample_station):
        screen = StationScreen(sample_arrivals, sample_station)
        action = screen.on_touch(TouchPoint(10, 10))
        assert type(action).__name__ == "GoBack"

    def test_no_action_on_dead_zone(self, sample_weather):
        screen = WeatherScreen(sample_weather)
        assert screen.on_touch(TouchPoint(150, 80)) is None


class TestFullRoundTrip:
    """Simulate a complete user session through the nav stack."""

    def test_full_session(self, sample_weather, sample_stations, sample_arrivals):
        from unittest.mock import patch

        with (
            patch("main.WeatherService") as MockWeather,
            patch("main.StationFinder") as MockFinder,
            patch("main.MTAService") as MockMTA,
        ):
            MockWeather.return_value.fetch.return_value = sample_weather
            MockFinder.return_value.nearest.return_value = sample_stations
            MockMTA.return_value.fetch_batch.return_value = [sample_arrivals] + [[] for _ in range(5)]
            MockMTA.return_value.fetch.return_value = sample_arrivals

            from main import App

            a = App()
            epd = MagicMock()
            app = a  # rename for clarity below

            # Start at home
            assert isinstance(app._screen, HomeScreen)

            # Tap weather
            action = app._screen.on_touch(TouchPoint(50, 60))
            app._dispatch(action, epd)
            assert isinstance(app._screen, WeatherScreen)

            # Go back
            action = app._screen.on_touch(TouchPoint(10, 10))
            app._dispatch(action, epd)
            assert isinstance(app._screen, HomeScreen)

            # Tap subway
            action = app._screen.on_touch(TouchPoint(200, 60))
            app._dispatch(action, epd)
            assert isinstance(app._screen, SubwayScreen)

            # Tap first station
            action = app._screen.on_touch(TouchPoint(120, app._screen._TOP + 5))
            app._dispatch(action, epd)
            assert isinstance(app._screen, StationScreen)

            # Back to subway list (preserved)
            action = app._screen.on_touch(TouchPoint(10, 10))
            app._dispatch(action, epd)
            assert isinstance(app._screen, SubwayScreen)

            # Back to home
            action = app._screen.on_touch(TouchPoint(10, 10))
            app._dispatch(action, epd)
            assert isinstance(app._screen, HomeScreen)
            assert app._stack == []
