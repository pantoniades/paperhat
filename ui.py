"""Screen rendering and touch-zone handling for the e-Paper display.

Each Screen subclass owns its rendering and touch interpretation.
Touch results are lightweight action objects that the App dispatches.
Paginated screens track their own page index and return Refresh to
request a re-render after a page change.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import APP, SCREEN_H, SCREEN_W
from drivers.touch import TouchPoint
from services.mta import Arrival, Station
from services.weather import DayForecast, Weather

# ── fonts ───────────────────────────────────────────────────────

_FONT_PATHS = [
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in _FONT_PATHS:
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


XL, LG, MD, SM = _font(28), _font(18), _font(13), _font(11)

# ── touch zones ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Rect:
    """Axis-aligned rectangle for hit-testing."""

    x: int
    y: int
    w: int
    h: int

    def contains(self, pt: TouchPoint) -> bool:
        return self.x <= pt.x < self.x + self.w and self.y <= pt.y < self.y + self.h


# ── actions (returned by screens, dispatched by App) ────────────


@dataclass(frozen=True, slots=True)
class ShowWeather:
    """Navigate to the weather screen."""


@dataclass(frozen=True, slots=True)
class ShowSubway:
    """Navigate to the nearby-stations screen."""


@dataclass(frozen=True, slots=True)
class ShowWeekly:
    """Navigate to the 5-day forecast screen."""


@dataclass(frozen=True, slots=True)
class SelectStation:
    """Navigate to arrivals for a specific station."""

    station: Station


@dataclass(frozen=True, slots=True)
class GoBack:
    """Pop one level in the navigation stack."""


@dataclass(frozen=True, slots=True)
class Refresh:
    """Re-render the current screen (e.g. after a page change)."""


@dataclass(frozen=True, slots=True)
class RefreshArrivals:
    """Re-fetch subway arrival data and re-render."""


@dataclass(frozen=True, slots=True)
class RefreshStation:
    """Re-fetch arrivals for the current station."""

    station: Station


Action = ShowWeather | ShowSubway | ShowWeekly | SelectStation | GoBack | Refresh | RefreshArrivals | RefreshStation

# ── screen base ─────────────────────────────────────────────────


class Screen(ABC):
    @abstractmethod
    def render(self) -> Image.Image: ...

    @abstractmethod
    def on_touch(self, pt: TouchPoint) -> Action | None: ...

    @staticmethod
    def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("1", (SCREEN_W, SCREEN_H), 255)
        return img, ImageDraw.Draw(img)


# ── shared helpers ──────────────────────────────────────────────

_BACK_ZONE = Rect(0, 0, 40, 32)
_PAGE_UP_ZONE = Rect(200, 0, 50, SCREEN_H // 2)
_PAGE_DOWN_ZONE = Rect(200, SCREEN_H // 2, 50, SCREEN_H // 2)
_REFRESH_ZONE = Rect(40, 0, 110, 24)  # title area on SubwayScreen
_WEEKLY_ZONE = Rect(150, 0, 50, 24)   # "Wk▸" button on WeatherScreen


def _back_arrow(draw: ImageDraw.ImageDraw) -> None:
    draw.polygon([(22, 8), (8, 16), (22, 24)], fill=0)


def _hline(draw: ImageDraw.ImageDraw, y: int) -> None:
    draw.line([(10, y), (SCREEN_W - 10, y)], fill=0)


def _page_nav(draw: ImageDraw.ImageDraw, page: int, total: int) -> None:
    """Draw ▲/▼ arrows and page indicator in the right margin."""
    if total <= 1:
        return
    draw.text((SCREEN_W - 8, SCREEN_H // 2), f"{page + 1}/{total}",
              font=SM, fill=0, anchor="rm")
    if page > 0:
        cx, cy = SCREEN_W - 20, 14
        draw.polygon([(cx, cy - 6), (cx - 6, cy + 2), (cx + 6, cy + 2)], fill=0)
    if page < total - 1:
        cx, cy = SCREEN_W - 20, SCREEN_H - 14
        draw.polygon([(cx, cy + 6), (cx - 6, cy - 2), (cx + 6, cy - 2)], fill=0)


def _handle_page(pt: TouchPoint, screen: Screen, page: int, total: int) -> Action | None:
    """Common page-up / page-down handler. Mutates screen.page."""
    if total <= 1:
        return None
    if _PAGE_UP_ZONE.contains(pt) and page > 0:
        screen.page -= 1  # type: ignore[attr-defined]
        return Refresh()
    if _PAGE_DOWN_ZONE.contains(pt) and page < total - 1:
        screen.page += 1  # type: ignore[attr-defined]
        return Refresh()
    return None


def _clock(arrival: Arrival) -> str:
    """Format arrival as 'HH:MM (Xm)'."""
    t = datetime.fromtimestamp(arrival.arrival_time).strftime("%H:%M")
    return f"{t} ({arrival.minutes}m)"


def _reachable(arrivals: list[Arrival]) -> list[Arrival]:
    """Filter arrivals to those still reachable (future + above min_departure_minutes)."""
    cutoff = APP.min_departure_minutes
    return [a for a in arrivals if a.is_future and a.minutes >= cutoff]


def _next_arrival(arrivals: list[Arrival], direction: str) -> Arrival | None:
    """First reachable arrival in the given direction, or None."""
    cutoff = APP.min_departure_minutes
    for a in arrivals:
        if a.is_future and a.minutes >= cutoff and a.direction == direction:
            return a
    return None


def _weather_icon(summary: str) -> str:
    """Map a forecast summary to a Unicode weather symbol."""
    s = summary.lower()
    if any(w in s for w in ("rain", "shower", "thunder", "storm")):
        return "☂"
    if any(w in s for w in ("snow", "sleet", "ice", "flurr")):
        return "❄"
    if any(w in s for w in ("sunny", "clear", "fair")):
        return "☀"
    if "partly" in s:
        return "⛅"
    return "☁"


# ── HomeScreen ──────────────────────────────────────────────────


class HomeScreen(Screen):
    """Two tappable icons: Weather (left, live conditions) · Subway (right)."""

    _LEFT = Rect(0, 0, SCREEN_W // 2, SCREEN_H)
    _RIGHT = Rect(SCREEN_W // 2, 0, SCREEN_W // 2, SCREEN_H)

    def __init__(self, summary: str = "", high_low: str = "Weather") -> None:
        self._icon = _weather_icon(summary) if summary else "☀"
        self._temps = high_low

    def render(self) -> Image.Image:
        img, draw = self._canvas()
        mid = SCREEN_W // 2

        draw.line([(mid, 8), (mid, SCREEN_H - 8)], fill=0)

        # live weather icon + today's high/low
        cx, cy = mid // 2, SCREEN_H // 2 - 10
        draw.text((cx, cy), self._icon, font=XL, fill=0, anchor="mm")
        draw.text((cx, cy + 28), self._temps, font=MD, fill=0, anchor="mt")

        # subway icon (circle with S)
        sx, sy, sr = mid + mid // 2, SCREEN_H // 2 - 10, 20
        draw.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], outline=0, width=3)
        draw.text((sx, sy), "S", font=LG, fill=0, anchor="mm")
        draw.text((sx, sy + sr + 14), "Subway", font=MD, fill=0, anchor="mt")

        return img

    def on_touch(self, pt: TouchPoint) -> Action | None:
        if self._LEFT.contains(pt):
            return ShowWeather()
        if self._RIGHT.contains(pt):
            return ShowSubway()
        return None


# ── WeatherScreen ───────────────────────────────────────────────

_WX_HOURLY_PAGE0 = 2
_WX_HOURLY_PER_PAGE = 6


class WeatherScreen(Screen):
    def __init__(self, data: Weather) -> None:
        self.data = data
        self.page = 0
        extra = max(0, len(data.hourly) - _WX_HOURLY_PAGE0)
        self._total = 1 + math.ceil(extra / _WX_HOURLY_PER_PAGE) if extra else 1

    def render(self) -> Image.Image:
        img, draw = self._canvas()
        _back_arrow(draw)
        draw.text((40, 4), "NYC Weather", font=LG, fill=0)
        draw.text((160, 6), "Wk▸", font=SM, fill=0)
        _page_nav(draw, self.page, self._total)

        if self.page == 0:
            y = 30
            draw.text((10, y), f"{self.data.temp}°{self.data.unit}", font=LG, fill=0)
            y += 22
            draw.text((10, y), self.data.summary, font=MD, fill=0)
            y += 16
            draw.text((10, y), f"Wind: {self.data.wind}", font=SM, fill=0)
            y += 16
            _hline(draw, y)
            y += 4
            for h in self.data.hourly[:_WX_HOURLY_PAGE0]:
                draw.text((10, y), f"{h.time}  {h.temp}°  {h.summary}", font=SM, fill=0)
                y += 14
        else:
            start = _WX_HOURLY_PAGE0 + (self.page - 1) * _WX_HOURLY_PER_PAGE
            entries = self.data.hourly[start:start + _WX_HOURLY_PER_PAGE]
            y = 26
            for h in entries:
                draw.text((10, y), f"{h.time}  {h.temp}°  {h.summary}", font=SM, fill=0)
                y += 14

        return img

    def on_touch(self, pt: TouchPoint) -> Action | None:
        if _BACK_ZONE.contains(pt):
            return GoBack()
        if _WEEKLY_ZONE.contains(pt):
            return ShowWeekly()
        return _handle_page(pt, self, self.page, self._total)


# ── WeeklyScreen (5-day forecast) ───────────────────────────────


class WeeklyScreen(Screen):
    """5-day forecast with weather icons."""

    def __init__(self, days: list[DayForecast]) -> None:
        self.days = days

    def render(self) -> Image.Image:
        img, draw = self._canvas()
        _back_arrow(draw)
        draw.text((40, 4), "5-Day Forecast", font=MD, fill=0)
        _hline(draw, 22)

        y = 26
        for day in self.days:
            icon = _weather_icon(day.summary)
            temps = f"{day.high}/{day.low}" if day.low is not None else f"{day.high}"

            # day name (short)
            name = day.name[:3] if len(day.name) > 5 else day.name
            draw.text((10, y), name, font=SM, fill=0)
            draw.text((50, y), icon, font=MD, fill=0)
            draw.text((68, y), temps, font=SM, fill=0)

            # truncate summary to fit
            summary = day.summary if len(day.summary) <= 16 else day.summary[:14] + "…"
            draw.text((110, y), summary, font=SM, fill=0)
            y += 18

        return img

    def on_touch(self, pt: TouchPoint) -> Action | None:
        return GoBack() if _BACK_ZONE.contains(pt) else None


# ── SubwayScreen (nearest stations, paginated) ──────────────────

_SUBWAY_PER_PAGE = 3


class SubwayScreen(Screen):
    """Nearest stations with next arrival times, 3 per page."""

    _ROW_H = 30
    _TOP = 26

    def __init__(self, stations: list[Station], arrivals: list[list[Arrival]]) -> None:
        self.stations = stations
        self.arrivals = arrivals
        self.page = 0
        self._total = math.ceil(len(stations) / _SUBWAY_PER_PAGE)

    def _page_slice(self) -> range:
        start = self.page * _SUBWAY_PER_PAGE
        return range(start, min(start + _SUBWAY_PER_PAGE, len(self.stations)))

    def render(self) -> Image.Image:
        img, draw = self._canvas()
        _back_arrow(draw)
        draw.text((40, 4), "Nearby Stations", font=MD, fill=0)
        _page_nav(draw, self.page, self._total)
        _hline(draw, self._TOP - 2)

        for row, i in enumerate(self._page_slice()):
            y = self._TOP + row * self._ROW_H
            draw.text((14, y + 2), self.stations[i].name, font=MD, fill=0)

            routes_str = ",".join(self.stations[i].routes)
            parts = [routes_str]
            for direction, arrow in (("N", "↑"), ("S", "↓")):
                nxt = _next_arrival(self.arrivals[i], direction)
                parts.append(f"{arrow}{_clock(nxt)}" if nxt else f"{arrow}—")
            draw.text((14, y + 16), "  ".join(parts), font=SM, fill=0)
        return img

    def on_touch(self, pt: TouchPoint) -> Action | None:
        if _BACK_ZONE.contains(pt):
            return GoBack()
        if _REFRESH_ZONE.contains(pt):
            return RefreshArrivals()
        if paged := _handle_page(pt, self, self.page, self._total):
            return paged
        for row, i in enumerate(self._page_slice()):
            zone = Rect(0, self._TOP + row * self._ROW_H, 200, self._ROW_H)
            if zone.contains(pt):
                return SelectStation(self.stations[i])
        return None


# ── StationScreen (arrivals by direction) ───────────────────────


class StationScreen(Screen):
    """Arrivals for one station, grouped by direction."""

    def __init__(self, arrivals: list[Arrival], station: Station) -> None:
        self.arrivals = arrivals
        self.station = station

    def render(self) -> Image.Image:
        img, draw = self._canvas()
        _back_arrow(draw)

        name = self.station.name
        if len(name) > 24:
            name = name[:22] + "…"
        draw.text((40, 4), name, font=MD, fill=0)
        _hline(draw, 22)

        live = _reachable(self.arrivals)
        north = [a for a in live if a.direction == "N"]
        south = [a for a in live if a.direction == "S"]

        y = 26
        y = self._draw_direction(draw, f"↑ {self.station.north_label}", north, y)
        y += 4
        y = self._draw_direction(draw, f"↓ {self.station.south_label}", south, y)
        return img

    @staticmethod
    def _draw_direction(
        draw: ImageDraw.ImageDraw, label: str, arrivals: list[Arrival], y: int,
    ) -> int:
        draw.text((10, y), label, font=SM, fill=0)
        y += 14
        if not arrivals:
            draw.text((14, y), "—", font=SM, fill=0)
            return y + 14

        x = 14
        for arr in arrivals[:3]:
            token = f"{arr.line} {_clock(arr)}"
            bbox = draw.textbbox((0, 0), token, font=SM)
            tw = bbox[2] - bbox[0]
            if x + tw > SCREEN_W - 10:
                y += 14
                x = 14
                if y > SCREEN_H - 14:
                    break
            draw.text((x, y), token, font=SM, fill=0)
            x += tw + 12
        return y + 14

    def on_touch(self, pt: TouchPoint) -> Action | None:
        if _BACK_ZONE.contains(pt):
            return GoBack()
        return RefreshStation(station=self.station)


# ── MessageScreen ───────────────────────────────────────────────


class MessageScreen(Screen):
    """Full-screen message (loading, error)."""

    def __init__(self, text: str, *, show_back: bool = False) -> None:
        self.text = text
        self._show_back = show_back

    def render(self) -> Image.Image:
        img, draw = self._canvas()
        if self._show_back:
            _back_arrow(draw)
        draw.text(
            (SCREEN_W // 2, SCREEN_H // 2),
            self.text, font=MD, fill=0, anchor="mm",
        )
        return img

    def on_touch(self, pt: TouchPoint) -> Action | None:
        return GoBack() if self._show_back else None
