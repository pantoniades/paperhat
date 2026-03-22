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


XXL, XL, LG, MD, SM = _font(36), _font(28), _font(18), _font(13), _font(11)

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


Action = ShowWeather | ShowSubway | ShowWeekly | SelectStation | GoBack | Refresh | RefreshArrivals

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


class PaginatedScreen(Screen):
    """Screen with ▲/▼ page navigation."""

    page: int = 0

    @property
    @abstractmethod
    def total_pages(self) -> int: ...

    def _page_touch(self, pt: TouchPoint) -> Action | None:
        """Handle page-up/down taps. Returns Refresh or None."""
        if self.total_pages <= 1:
            return None
        if _PAGE_UP_ZONE.contains(pt) and self.page > 0:
            self.page -= 1
            return Refresh()
        if _PAGE_DOWN_ZONE.contains(pt) and self.page < self.total_pages - 1:
            self.page += 1
            return Refresh()
        return None


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


def _weather_kind(summary: str) -> str:
    """Map a forecast summary to a weather kind key."""
    s = summary.lower()
    if any(w in s for w in ("rain", "shower", "thunder", "storm")):
        return "rain"
    if any(w in s for w in ("snow", "sleet", "ice", "flurr")):
        return "snow"
    if any(w in s for w in ("sunny", "clear", "fair")):
        return "sun"
    if "partly" in s:
        return "partly"
    return "cloud"


def _draw_weather_icon(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, kind: str,
) -> None:
    """Draw a weather icon centred at (cx, cy) using only primitives.

    *size* is the approximate bounding-box height/width in pixels.
    """
    r = size // 2

    if kind == "sun":
        # circle with rays
        sr = r * 5 // 9
        draw.ellipse([cx - sr, cy - sr, cx + sr, cy + sr], outline=0, width=2)
        for angle_deg in range(0, 360, 45):
            rad = math.radians(angle_deg)
            x0 = cx + int(sr * 1.4 * math.cos(rad))
            y0 = cy - int(sr * 1.4 * math.sin(rad))
            x1 = cx + int(r * 0.95 * math.cos(rad))
            y1 = cy - int(r * 0.95 * math.sin(rad))
            draw.line([(x0, y0), (x1, y1)], fill=0, width=1)

    elif kind == "cloud":
        _draw_cloud(draw, cx, cy, r)

    elif kind == "partly":
        # small sun peeking upper-right, cloud overlapping lower-left
        _draw_weather_icon(draw, cx + r // 3, cy - r // 3, size * 2 // 3, "sun")
        _draw_cloud(draw, cx - r // 5, cy + r // 5, r * 2 // 3)

    elif kind == "rain":
        cr = r * 2 // 3
        _draw_cloud(draw, cx, cy - r // 4, cr)
        # three rain drops
        for dx in (-cr // 2, 0, cr // 2):
            x = cx + dx
            y0 = cy + cr // 2
            draw.line([(x, y0), (x - 2, y0 + r // 3)], fill=0, width=1)

    elif kind == "snow":
        cr = r * 2 // 3
        _draw_cloud(draw, cx, cy - r // 4, cr)
        # three snowflake dots
        dot = max(1, size // 14)
        for dx in (-cr // 2, 0, cr // 2):
            x = cx + dx
            y = cy + cr // 2 + r // 4
            draw.ellipse([x - dot, y - dot, x + dot, y + dot], fill=0)


def _draw_cloud(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    """Draw a simple cloud shape centred at (cx, cy) with radius *r*."""
    # flat base with two bumps
    bw = r  # half-width of base
    draw.line([(cx - bw, cy + r // 3), (cx + bw, cy + r // 3)], fill=0, width=2)
    # left bump
    draw.arc(
        [cx - bw, cy - r // 2, cx, cy + r // 3],
        180, 0, fill=0, width=2,
    )
    # right bump (taller)
    draw.arc(
        [cx - r // 4, cy - r * 3 // 4, cx + bw, cy + r // 3],
        180, 0, fill=0, width=2,
    )


# ── HomeScreen ──────────────────────────────────────────────────


class HomeScreen(Screen):
    """Two tappable icons: Weather (left, live conditions) · Subway (right)."""

    _LEFT = Rect(0, 0, SCREEN_W // 2, SCREEN_H)
    _RIGHT = Rect(SCREEN_W // 2, 0, SCREEN_W // 2, SCREEN_H)

    def __init__(self, summary: str = "", high_low: str = "Weather") -> None:
        self._kind = _weather_kind(summary) if summary else "partly"
        self._temps = high_low

    def render(self) -> Image.Image:
        img, draw = self._canvas()
        mid = SCREEN_W // 2

        draw.line([(mid, 8), (mid, SCREEN_H - 8)], fill=0)

        # live weather icon + today's high/low
        cx, cy = mid // 2, SCREEN_H // 2 - 10
        _draw_weather_icon(draw, cx, cy, 40, self._kind)
        draw.text((cx, cy + 28), self._temps, font=MD, fill=0, anchor="mt")

        # MTA logo — filled circle with white "MTA" text
        sx, sy, sr = mid + mid // 2, SCREEN_H // 2 - 10, 22
        draw.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=0)
        draw.text((sx, sy), "MTA", font=MD, fill=255, anchor="mm")
        draw.text((sx, sy + sr + 12), "Subway", font=MD, fill=0, anchor="mt")

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


class WeatherScreen(PaginatedScreen):
    def __init__(self, data: Weather) -> None:
        self.data = data
        self.page = 0
        extra = max(0, len(data.hourly) - _WX_HOURLY_PAGE0)
        self._total = 1 + math.ceil(extra / _WX_HOURLY_PER_PAGE) if extra else 1

    @property
    def total_pages(self) -> int:
        return self._total

    def render(self) -> Image.Image:
        img, draw = self._canvas()
        _back_arrow(draw)
        draw.text((40, 4), "NYC Weather", font=LG, fill=0)
        draw.text((160, 6), "Wk▸", font=SM, fill=0)
        _page_nav(draw, self.page, self.total_pages)

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
        return self._page_touch(pt)


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
            kind = _weather_kind(day.summary)
            temps = f"{day.high}/{day.low}" if day.low is not None else f"{day.high}"

            # day name (short)
            name = day.name[:3] if len(day.name) > 5 else day.name
            draw.text((10, y), name, font=SM, fill=0)
            _draw_weather_icon(draw, 55, y + 6, 12, kind)
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


class SubwayScreen(PaginatedScreen):
    """Nearest stations with next arrival times, 3 per page."""

    _ROW_H = 30
    _TOP = 26

    def __init__(self, stations: list[Station], arrivals: list[list[Arrival]]) -> None:
        self.stations = stations
        self.arrivals = arrivals
        self.page = 0

    @property
    def total_pages(self) -> int:
        return math.ceil(len(self.stations) / _SUBWAY_PER_PAGE)

    def _page_slice(self) -> range:
        start = self.page * _SUBWAY_PER_PAGE
        return range(start, min(start + _SUBWAY_PER_PAGE, len(self.stations)))

    def render(self) -> Image.Image:
        img, draw = self._canvas()
        _back_arrow(draw)
        draw.text((40, 4), "Nearby Stations", font=MD, fill=0)
        _page_nav(draw, self.page, self.total_pages)
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
        if paged := self._page_touch(pt):
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
        return SelectStation(station=self.station)  # tap anywhere = refresh


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
