"""National Weather Service API client (free, no key required)."""

from __future__ import annotations

from dataclasses import dataclass

import requests

from config import APP


@dataclass(frozen=True, slots=True)
class HourForecast:
    time: str
    temp: int
    summary: str


@dataclass(frozen=True, slots=True)
class Weather:
    """Current conditions plus a few hours ahead."""

    temp: int
    unit: str
    summary: str
    wind: str
    hourly: list[HourForecast]


class WeatherService:
    """Fetches hourly forecast from api.weather.gov."""

    _BASE = "https://api.weather.gov"

    def __init__(self) -> None:
        self._headers = {"User-Agent": f"({APP.nws_agent})"}
        self._forecast_url: str | None = None

    def fetch(self) -> Weather:
        url = self._resolve_forecast_url()
        periods = (
            requests.get(url, headers=self._headers, timeout=10)
            .json()["properties"]["periods"]
        )
        now = periods[0]
        return Weather(
            temp=now["temperature"],
            unit=now["temperatureUnit"],
            summary=now["shortForecast"],
            wind=f"{now['windSpeed']} {now['windDirection']}",
            hourly=[
                HourForecast(
                    time=p["startTime"][11:16],
                    temp=p["temperature"],
                    summary=p["shortForecast"],
                )
                for p in periods[1:4]
            ],
        )

    def _resolve_forecast_url(self) -> str:
        if self._forecast_url is None:
            resp = requests.get(
                f"{self._BASE}/points/{APP.lat},{APP.lon}",
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            self._forecast_url = resp.json()["properties"]["forecastHourly"]
        return self._forecast_url
