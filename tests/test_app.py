"""Tests for App navigation logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ui import (
    GoBack,
    HomeScreen,
    MessageScreen,
    Screen,
    SelectStation,
    ShowSubway,
    ShowWeather,
    StationScreen,
    SubwayScreen,
    WeatherScreen,
)


@pytest.fixture()
def mock_epd():
    epd = MagicMock()
    epd.show = MagicMock()
    return epd


@pytest.fixture()
def app(sample_stations):
    with (
        patch("main.WeatherService"),
        patch("main.StationFinder") as MockFinder,
        patch("main.MTAService"),
    ):
        MockFinder.return_value.nearest.return_value = sample_stations
        from main import App

        return App()


class TestAppInit:
    def test_initial_screen_is_home(self, app):
        assert isinstance(app._screen, HomeScreen)

    def test_initial_stack_is_empty(self, app):
        assert app._stack == []


class TestNavStack:
    def test_push_adds_to_stack(self, app, mock_epd):
        original = app._screen
        new = MagicMock(spec=Screen)
        new.render.return_value = MagicMock()

        app._push(new, mock_epd)

        assert app._screen is new
        assert app._stack == [original]
        mock_epd.show.assert_called_once()

    def test_pop_restores_previous(self, app, mock_epd):
        original = app._screen
        new = MagicMock(spec=Screen)
        new.render.return_value = MagicMock()

        app._push(new, mock_epd)
        app._pop(mock_epd)

        assert isinstance(app._screen, HomeScreen)
        assert app._stack == []

    def test_pop_empty_gives_homescreen(self, app, mock_epd):
        app._stack.clear()
        app._pop(mock_epd)
        assert isinstance(app._screen, HomeScreen)


class TestDispatch:
    def test_show_weather(self, app, mock_epd, sample_weather):
        app.weather.fetch.return_value = sample_weather
        app._dispatch(ShowWeather(), mock_epd)

        assert isinstance(app._screen, WeatherScreen)
        assert len(app._stack) == 1

    def test_show_subway(self, app, mock_epd):
        app.mta.fetch_batch.return_value = [[], [], []]
        app._dispatch(ShowSubway(), mock_epd)

        assert isinstance(app._screen, SubwayScreen)
        assert len(app._stack) == 1

    def test_select_station(self, app, mock_epd, sample_station, sample_arrivals):
        app._dispatch(SelectStation(station=sample_station, arrivals=sample_arrivals), mock_epd)

        assert isinstance(app._screen, StationScreen)

    def test_go_back(self, app, mock_epd, sample_weather):
        app.weather.fetch.return_value = sample_weather
        app._dispatch(ShowWeather(), mock_epd)
        app._dispatch(GoBack(), mock_epd)

        assert isinstance(app._screen, HomeScreen)
        assert app._stack == []

    def test_select_station_is_instant(self, app, mock_epd, sample_station, sample_arrivals):
        """SelectStation should not show a loading screen — arrivals are pre-fetched."""
        app._dispatch(SelectStation(station=sample_station, arrivals=sample_arrivals), mock_epd)

        # Only one show() call (the station screen), not two (loading + result)
        assert mock_epd.show.call_count == 1
        assert isinstance(app._screen, StationScreen)


class TestLoadErrorHandling:
    def test_network_error_shows_message(self, app, mock_epd):
        app.weather.fetch.side_effect = ConnectionError("no network")
        app._dispatch(ShowWeather(), mock_epd)

        assert isinstance(app._screen, MessageScreen)
        assert app._screen._show_back is True

    def test_error_message_truncated(self, app, mock_epd):
        app.weather.fetch.side_effect = RuntimeError("x" * 100)
        app._dispatch(ShowWeather(), mock_epd)

        assert len(app._screen.text) <= 50

    def test_loading_message_shown_before_fetch(self, app, mock_epd, sample_weather):
        show_calls = []
        mock_epd.show.side_effect = lambda img: show_calls.append(type(img))
        app.weather.fetch.return_value = sample_weather

        # _load renders a MessageScreen image first, then _push renders the result
        from main import App
        from PIL import Image

        images = []
        mock_epd.show.side_effect = lambda img: images.append(img)
        app._dispatch(ShowWeather(), mock_epd)

        # At least 2 show() calls: loading message + weather screen
        assert mock_epd.show.call_count >= 2


class TestFullNavigation:
    def test_home_to_subway_to_station_and_back_twice(
        self, app, mock_epd, sample_stations, sample_arrivals
    ):
        app.mta.fetch_batch.return_value = [sample_arrivals, [], []]

        # Home → Subway
        app._dispatch(ShowSubway(), mock_epd)
        assert isinstance(app._screen, SubwayScreen)

        # Subway → Station (arrivals come from SubwayScreen, no re-fetch)
        app._dispatch(SelectStation(station=sample_stations[0], arrivals=sample_arrivals), mock_epd)
        assert isinstance(app._screen, StationScreen)

        # Station → back to Subway
        app._dispatch(GoBack(), mock_epd)
        assert isinstance(app._screen, SubwayScreen)

        # Subway → back to Home
        app._dispatch(GoBack(), mock_epd)
        assert isinstance(app._screen, HomeScreen)

    def test_deep_stack_unwinds_correctly(self, app, mock_epd, sample_weather, sample_stations, sample_arrivals):
        app.weather.fetch.return_value = sample_weather
        app.mta.fetch_batch.return_value = [sample_arrivals, [], []]

        app._dispatch(ShowWeather(), mock_epd)
        app._dispatch(GoBack(), mock_epd)
        app._dispatch(ShowSubway(), mock_epd)
        app._dispatch(SelectStation(station=sample_stations[0], arrivals=sample_arrivals), mock_epd)
        app._dispatch(GoBack(), mock_epd)
        app._dispatch(GoBack(), mock_epd)

        assert isinstance(app._screen, HomeScreen)
        assert app._stack == []
