"""National Weather Service API client (free, no key required)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

from config import APP

logger = logging.getLogger(__name__)

_HOURLY_TTL = 30 * 60    # 30 minutes
_WEEKLY_TTL = 2 * 60 * 60  # 2 hours


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


@dataclass(frozen=True, slots=True)
class DayForecast:
    """One day in the 5-day forecast."""

    name: str       # "Today", "Monday", etc.
    high: int
    low: int | None
    summary: str    # "Sunny", "Rain", etc.


class WeatherService:
    """Fetches hourly and daily forecasts from api.weather.gov."""

    _BASE = "https://api.weather.gov"

    def __init__(self) -> None:
        self._headers = {"User-Agent": f"({APP.nws_agent})"}
        self._hourly_url: str | None = None
        self._daily_url: str | None = None
        self._cached: Weather | None = None
        self._cached_at: float = 0.0
        self._weekly: list[DayForecast] | None = None
        self._weekly_at: float = 0.0

    def fetch(self) -> Weather:
        now = time.monotonic()
        if self._cached and (now - self._cached_at) < _HOURLY_TTL:
            logger.debug("Weather cache hit (age %.0fs)", now - self._cached_at)
            return self._cached

        self._resolve_urls()
        periods = (
            requests.get(self._hourly_url, headers=self._headers, timeout=10)
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
                for p in periods[1:13]
            ],
        )
        self._cached_at = now
        logger.info("Weather fetched and cached for %dm", _HOURLY_TTL // 60)
        return self._cached

    def fetch_weekly(self) -> list[DayForecast]:
        now = time.monotonic()
        if self._weekly and (now - self._weekly_at) < _WEEKLY_TTL:
            logger.debug("Weekly cache hit (age %.0fs)", now - self._weekly_at)
            return self._weekly

        self._resolve_urls()
        periods = (
            requests.get(self._daily_url, headers=self._headers, timeout=10)
            .json()["properties"]["periods"]
        )

        days: list[DayForecast] = []
        i = 0
        while i < len(periods) and len(days) < 5:
            p = periods[i]
            if p["isDaytime"]:
                low = (
                    periods[i + 1]["temperature"]
                    if i + 1 < len(periods) and not periods[i + 1]["isDaytime"]
                    else None
                )
                days.append(DayForecast(
                    name=p["name"],
                    high=p["temperature"],
                    low=low,
                    summary=p["shortForecast"],
                ))
                i += 2 if low is not None else 1
            else:
                i += 1  # skip standalone nighttime period

        self._weekly = days
        self._weekly_at = now
        logger.info("Weekly forecast fetched and cached for %dh", _WEEKLY_TTL // 3600)
        return self._weekly

    def _resolve_urls(self) -> None:
        if self._hourly_url is not None:
            return
        resp = requests.get(
            f"{self._BASE}/points/{APP.lat},{APP.lon}",
            headers=self._headers,
            timeout=10,
        )
        resp.raise_for_status()
        props = resp.json()["properties"]
        self._hourly_url = props["forecastHourly"]
        self._daily_url = props["forecast"]
