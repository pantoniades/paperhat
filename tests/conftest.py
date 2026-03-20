"""Shared fixtures: mock hardware, sample data factories, API responses."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from PIL import Image

from config import SCREEN_H, SCREEN_W
from drivers.touch import TouchPoint
from services.mta import Arrival, Station, StopInfo
from services.weather import HourForecast, Weather

# ── hardware mock fixtures ──────────────────────────────────────


@pytest.fixture()
def mock_gpio():
    """Patch RPi.GPIO in both driver modules with a usable mock."""
    gpio = MagicMock()
    gpio.BCM = 11
    gpio.OUT = 0
    gpio.IN = 1
    gpio.PUD_UP = 22
    gpio.input.return_value = 0  # not busy by default
    with (
        patch("drivers.epd.GPIO", gpio),
        patch("drivers.touch.GPIO", gpio),
    ):
        yield gpio


@pytest.fixture()
def mock_spi(mock_gpio):
    """Patch spidev and return the SpiDev instance mock."""
    spi_mod = MagicMock()
    spi_inst = MagicMock()
    spi_mod.SpiDev.return_value = spi_inst
    with patch("drivers.epd.spidev", spi_mod):
        yield spi_inst


@pytest.fixture()
def mock_smbus(mock_gpio):
    """Patch smbus2 and return the SMBus instance mock."""
    smbus_mod = MagicMock()
    bus = MagicMock()
    smbus_mod.SMBus.return_value = bus
    # i2c_msg helpers
    smbus_mod.i2c_msg.write.return_value = MagicMock()
    smbus_mod.i2c_msg.read.return_value = MagicMock()
    with patch("drivers.touch.smbus2", smbus_mod):
        yield bus, smbus_mod


@pytest.fixture()
def epd(mock_spi):
    """An EPD instance with mocked hardware, already entered."""
    from drivers.epd import EPD

    display = EPD()
    display.__enter__()
    yield display
    display.__exit__(None, None, None)


@pytest.fixture()
def touch_panel(mock_smbus):
    """A TouchPanel instance with mocked hardware, already entered."""
    from drivers.touch import TouchPanel

    panel = TouchPanel()
    panel.__enter__()
    yield panel
    panel.__exit__(None, None, None)


# ── data factories ──────────────────────────────────────────────


@pytest.fixture()
def sample_weather() -> Weather:
    return Weather(
        temp=72,
        unit="F",
        summary="Partly Cloudy",
        wind="5 mph NW",
        hourly=[
            HourForecast(time="14:00", temp=70, summary="Mostly Cloudy"),
            HourForecast(time="15:00", temp=68, summary="Cloudy"),
            HourForecast(time="16:00", temp=65, summary="Rain"),
        ],
    )


@pytest.fixture()
def sample_station() -> Station:
    return Station(
        name="Grand Army Plaza",
        lat=40.6752,
        lon=-73.9709,
        stops=[
            StopInfo("239", ("2", "3"), "Manhattan", "Flatbush"),
        ],
    )


@pytest.fixture()
def sample_stations() -> list[Station]:
    return [
        Station(
            name="Grand Army Plaza",
            lat=40.6752,
            lon=-73.9709,
            stops=[StopInfo("239", ("2", "3"), "Manhattan", "Flatbush")],
            distance_m=116.0,
        ),
        Station(
            name="7 Av",
            lat=40.6772,
            lon=-73.9726,
            stops=[StopInfo("D25", ("B", "Q"), "Manhattan", "Coney Island")],
            distance_m=343.0,
        ),
        Station(
            name="Eastern Pkwy-Brooklyn Museum",
            lat=40.6720,
            lon=-73.9642,
            stops=[StopInfo("238", ("2", "3"), "Manhattan", "Outbound")],
            distance_m=595.0,
        ),
    ]


@pytest.fixture()
def sample_arrivals() -> list[Arrival]:
    import time as _t

    now = _t.time()
    return [
        Arrival(line="2", direction="N", arrival_time=now + 180),
        Arrival(line="3", direction="N", arrival_time=now + 420),
        Arrival(line="2", direction="S", arrival_time=now + 60),
        Arrival(line="3", direction="S", arrival_time=now + 300),
    ]


# ── NWS API response fixtures ──────────────────────────────────


@pytest.fixture()
def nws_points_response() -> dict:
    return {
        "properties": {
            "forecastHourly": "https://api.weather.gov/gridpoints/OKX/33,35/forecast/hourly",
        }
    }


@pytest.fixture()
def nws_forecast_response() -> dict:
    return {
        "properties": {
            "periods": [
                {
                    "startTime": "2026-03-20T10:00:00-04:00",
                    "temperature": 45,
                    "temperatureUnit": "F",
                    "shortForecast": "Mostly Sunny",
                    "windSpeed": "7 mph",
                    "windDirection": "SW",
                },
                {
                    "startTime": "2026-03-20T11:00:00-04:00",
                    "temperature": 47,
                    "temperatureUnit": "F",
                    "shortForecast": "Partly Sunny",
                    "windSpeed": "8 mph",
                    "windDirection": "SW",
                },
                {
                    "startTime": "2026-03-20T12:00:00-04:00",
                    "temperature": 50,
                    "temperatureUnit": "F",
                    "shortForecast": "Cloudy",
                    "windSpeed": "9 mph",
                    "windDirection": "W",
                },
                {
                    "startTime": "2026-03-20T13:00:00-04:00",
                    "temperature": 53,
                    "temperatureUnit": "F",
                    "shortForecast": "Rain",
                    "windSpeed": "10 mph",
                    "windDirection": "W",
                },
            ]
        }
    }


# ── MTA station API response fixture ───────────────────────────


@pytest.fixture()
def mta_stations_api_response() -> list[dict]:
    return [
        {
            "complex_id": "1",
            "station_id": "1",
            "gtfs_stop_id": "239",
            "stop_name": "Grand Army Plaza",
            "daytime_routes": "2 3",
            "gtfs_latitude": "40.6752",
            "gtfs_longitude": "-73.9709",
            "north_direction_label": "Manhattan",
            "south_direction_label": "Flatbush",
        },
        {
            "complex_id": "2",
            "station_id": "2",
            "gtfs_stop_id": "D25",
            "stop_name": "7 Av",
            "daytime_routes": "B Q",
            "gtfs_latitude": "40.6772",
            "gtfs_longitude": "-73.9726",
            "north_direction_label": "Manhattan",
            "south_direction_label": "Coney Island",
        },
        {
            "complex_id": "3",
            "station_id": "3",
            "gtfs_stop_id": "238",
            "stop_name": "Eastern Pkwy-Brooklyn Museum",
            "daytime_routes": "2 3",
            "gtfs_latitude": "40.6720",
            "gtfs_longitude": "-73.9642",
            "north_direction_label": "Manhattan",
            "south_direction_label": "Outbound",
        },
        # second stop in complex 2 (same physical station)
        {
            "complex_id": "2",
            "station_id": "4",
            "gtfs_stop_id": "D26",
            "stop_name": "7 Av",
            "daytime_routes": "F G",
            "gtfs_latitude": "40.6772",
            "gtfs_longitude": "-73.9726",
            "north_direction_label": "Manhattan",
            "south_direction_label": "Church Av",
        },
    ]
