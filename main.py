"""PaperHat — touch e-Paper dashboard for Raspberry Pi Zero W.

Tappable home screen with NYC weather and nearby subway arrivals
on a Waveshare 2.13" Touch e-Paper HAT (250×122, B/W).
"""

from __future__ import annotations

import signal
import sys
import time
from typing import Callable

from config import APP
from drivers import EPD, TouchPanel
from services import MTAService, StationFinder, WeatherService
from ui import (
    Action,
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


class App:
    """Screen state machine with a navigation stack."""

    def __init__(self) -> None:
        self.weather = WeatherService()
        self.stations = StationFinder()
        self.mta = MTAService()
        self._screen: Screen = HomeScreen()
        self._stack: list[Screen] = []

    def run(self) -> None:
        with EPD() as epd, TouchPanel() as touch:
            epd.clear()
            self._refresh(epd)

            while True:
                if not (points := touch.wait(timeout=30)):
                    continue
                if (action := self._screen.on_touch(points[0])) is not None:
                    self._dispatch(action, epd)
                    time.sleep(0.3)

    # ── navigation ──────────────────────────────────────────────

    def _dispatch(self, action: Action, epd: EPD) -> None:
        match action:
            case ShowWeather():
                self._push(self._load(epd, "Fetching weather…",
                    lambda: WeatherScreen(self.weather.fetch())), epd)
            case ShowSubway():
                self._push(self._load(epd, "Finding stations…",
                    lambda: SubwayScreen(
                        self.stations.nearest(APP.lat, APP.lon))), epd)
            case SelectStation(station=s):
                self._push(self._load(epd, "Fetching arrivals…",
                    lambda: StationScreen(self.mta.fetch(s), s)), epd)
            case GoBack():
                self._pop(epd)

    def _push(self, screen: Screen, epd: EPD) -> None:
        self._stack.append(self._screen)
        self._screen = screen
        self._refresh(epd)

    def _pop(self, epd: EPD) -> None:
        self._screen = self._stack.pop() if self._stack else HomeScreen()
        self._refresh(epd)

    def _refresh(self, epd: EPD) -> None:
        epd.show(self._screen.render())

    @staticmethod
    def _load(epd: EPD, msg: str, build: Callable[[], Screen]) -> Screen:
        """Show a loading message, run *build*, return the new screen."""
        epd.show(MessageScreen(msg).render())
        try:
            return build()
        except Exception as exc:
            return MessageScreen(str(exc)[:50], show_back=True)


def main() -> None:
    app = App()

    def _quit(sig: int, _: object) -> None:
        print(f"\nSignal {sig} — shutting down")
        sys.exit(0)

    signal.signal(signal.SIGINT, _quit)
    signal.signal(signal.SIGTERM, _quit)

    try:
        app.run()
    except Exception as exc:
        print(f"Fatal: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
