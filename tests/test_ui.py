"""Tests for screens, touch zones, and action types."""

from __future__ import annotations

import dataclasses

import pytest
from PIL import Image

from config import SCREEN_H, SCREEN_W
from drivers.touch import TouchPoint
from services.mta import Arrival, Station, StopInfo
from ui import (
    GoBack,
    HomeScreen,
    MessageScreen,
    Rect,
    Screen,
    SelectStation,
    ShowSubway,
    ShowWeather,
    StationScreen,
    SubwayScreen,
    WeatherScreen,
)

# ── Rect ────────────────────────────────────────────────────────


class TestRect:
    def test_contains_inside(self):
        assert Rect(10, 20, 50, 30).contains(TouchPoint(35, 35))

    def test_contains_top_left_inclusive(self):
        assert Rect(10, 20, 50, 30).contains(TouchPoint(10, 20))

    def test_contains_bottom_right_exclusive(self):
        assert not Rect(10, 20, 50, 30).contains(TouchPoint(60, 50))

    def test_contains_outside(self):
        assert not Rect(10, 20, 50, 30).contains(TouchPoint(0, 0))

    def test_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            Rect(0, 0, 10, 10).x = 5


# ── Action types ────────────────────────────────────────────────


class TestActions:
    def test_show_weather_has_slots(self):
        assert not hasattr(ShowWeather(), "__dict__")

    def test_select_station_holds_station(self, sample_station):
        action = SelectStation(station=sample_station)
        assert action.station is sample_station

    def test_match_case_destructure(self, sample_station):
        action = SelectStation(station=sample_station)
        match action:
            case SelectStation(station=s):
                assert s.name == "Grand Army Plaza"
            case _:
                pytest.fail("match/case failed")

    @pytest.mark.parametrize("cls", [ShowWeather, ShowSubway, GoBack])
    def test_no_payload_actions_instantiate(self, cls):
        assert cls() is not None


# ── Screen rendering invariants ─────────────────────────────────


def _assert_valid_screen_image(img: Image.Image) -> None:
    assert isinstance(img, Image.Image)
    assert img.size == (SCREEN_W, SCREEN_H)
    assert img.mode == "1"


class TestHomeScreen:
    def test_render_size_and_mode(self):
        _assert_valid_screen_image(HomeScreen().render())

    def test_render_has_content(self):
        img = HomeScreen().render()
        colors = img.getcolors()
        assert len(colors) == 2  # both black and white pixels

    def test_touch_left_returns_show_weather(self):
        assert isinstance(HomeScreen().on_touch(TouchPoint(50, 60)), ShowWeather)

    def test_touch_right_returns_show_subway(self):
        assert isinstance(HomeScreen().on_touch(TouchPoint(200, 60)), ShowSubway)


class TestWeatherScreen:
    def test_render_size_and_mode(self, sample_weather):
        _assert_valid_screen_image(WeatherScreen(sample_weather).render())

    def test_touch_back_zone(self, sample_weather):
        assert isinstance(WeatherScreen(sample_weather).on_touch(TouchPoint(15, 10)), GoBack)

    def test_touch_elsewhere_returns_none(self, sample_weather):
        assert WeatherScreen(sample_weather).on_touch(TouchPoint(200, 100)) is None


class TestSubwayScreen:
    def test_render_size_and_mode(self, sample_stations):
        _assert_valid_screen_image(SubwayScreen(sample_stations).render())

    def test_touch_back(self, sample_stations):
        assert isinstance(SubwayScreen(sample_stations).on_touch(TouchPoint(15, 10)), GoBack)

    def test_touch_first_station(self, sample_stations):
        screen = SubwayScreen(sample_stations)
        action = screen.on_touch(TouchPoint(120, 30))
        assert isinstance(action, SelectStation)
        assert action.station.name == sample_stations[0].name

    def test_touch_second_station(self, sample_stations):
        screen = SubwayScreen(sample_stations)
        y = screen._TOP + screen._ROW_H + 5
        action = screen.on_touch(TouchPoint(120, y))
        assert isinstance(action, SelectStation)
        assert action.station.name == sample_stations[1].name

    def test_touch_outside_zones(self, sample_stations):
        assert SubwayScreen(sample_stations).on_touch(TouchPoint(120, 120)) is None

    def test_zones_match_station_count(self, sample_stations):
        screen = SubwayScreen(sample_stations)
        assert len(screen._zones) == len(sample_stations)


class TestStationScreen:
    def test_render_size_and_mode(self, sample_arrivals, sample_station):
        _assert_valid_screen_image(StationScreen(sample_arrivals, sample_station).render())

    def test_touch_back(self, sample_arrivals, sample_station):
        screen = StationScreen(sample_arrivals, sample_station)
        assert isinstance(screen.on_touch(TouchPoint(15, 10)), GoBack)

    def test_touch_elsewhere_returns_none(self, sample_arrivals, sample_station):
        screen = StationScreen(sample_arrivals, sample_station)
        assert screen.on_touch(TouchPoint(200, 100)) is None

    def test_long_name_does_not_crash(self, sample_arrivals):
        station = Station(
            name="A" * 40, lat=0, lon=0,
            stops=[StopInfo("X", ("1",), "Up", "Down")],
        )
        _assert_valid_screen_image(StationScreen(sample_arrivals, station).render())

    def test_empty_arrivals_does_not_crash(self, sample_station):
        _assert_valid_screen_image(StationScreen([], sample_station).render())


class TestMessageScreen:
    def test_render_size_and_mode(self):
        _assert_valid_screen_image(MessageScreen("Loading...").render())

    def test_no_back_returns_none(self):
        assert MessageScreen("hi").on_touch(TouchPoint(15, 10)) is None

    def test_with_back_returns_goback(self):
        assert isinstance(
            MessageScreen("err", show_back=True).on_touch(TouchPoint(15, 10)),
            GoBack,
        )
