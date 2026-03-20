"""National Weather Service API client (free, no key required)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

from config import APP

logger = logging.getLogger(__name__)

_CACHE_TTL = 30 * 60  # 30 minutes


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
        self._cached: Weather | None = None
        self._cached_at: float = 0.0

    def fetch(self) -> Weather:
        now = time.monotonic()
        if self._cached and (now - self._cached_at) < _CACHE_TTL:
            logger.debug("Weather cache hit (age %.0fs)", now - self._cached_at)
            return self._cached

        url = self._resolve_forecast_url()
        periods = (
            requests.get(url, headers=self._headers, timeout=10)
            .json()["properties"]["periods"]
        )
        cur = periods[0]
        self._cached = Weather(
            temp=cur["temperature"],
            unit=cur["temperatureUnit"],
            summary=cur["shortForecast"],
            wind=f"{cur['windSpeed']} {cur['windDirection']}",
            hourly=[
                HourForecast(
                    time=p["startTime"][11:16],
                    temp=p["temperature"],
                    summary=p["shortForecast"],
                )
                for p in periods[1:4]
            ],
        )
        self._cached_at = now
        logger.info("Weather fetched and cached for %dm", _CACHE_TTL // 60)
        return self._cached

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
