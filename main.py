"""PaperHat — touch e-Paper dashboard for Raspberry Pi Zero W.

Tappable home screen with NYC weather and nearby subway arrivals
on a Waveshare 2.13" Touch e-Paper HAT (250×122, B/W).
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


class App:
    """Screen state machine with a navigation stack."""

    def __init__(self) -> None:
        self.weather = WeatherService()
        self.mta = MTAService()
        self._nearby = StationFinder().nearest(APP.lat, APP.lon)
        logger.info(
            "Cached %d nearby station(s): %s",
            len(self._nearby), ", ".join(s.name for s in self._nearby),
        )
        self._screen: Screen = HomeScreen()
        self._stack: list[Screen] = []

    def run(self) -> None:
        with EPD() as epd, TouchPanel() as touch:
            epd.clear()
            self._refresh(epd)
            logger.info("Ready — showing home screen")

            while True:
                if not (points := touch.wait(timeout=30)):
                    continue
                pt = points[0]
                action = self._screen.on_touch(pt)
                logger.info(
                    "Touch (%d, %d) on %s → %s",
                    pt.x, pt.y,
                    type(self._screen).__name__,
                    type(action).__name__ if action else "None",
                )
                if action is not None:
                    self._dispatch(action, epd)
                    touch.flush()  # wait for finger lift before next event

    # ── navigation ──────────────────────────────────────────────

    def _dispatch(self, action: Action, epd: EPD) -> None:
        match action:
            case ShowWeather():
                self._push(self._load(epd, "Fetching weather…",
                    lambda: WeatherScreen(self.weather.fetch())), epd)
            case ShowSubway():
                self._push(self._load(epd, "Finding stations…",
                    self._build_subway_screen), epd)
            case SelectStation(station=s, arrivals=arr):
                self._push(StationScreen(arr, s), epd)
            case GoBack():
                self._pop(epd)

    def _build_subway_screen(self) -> SubwayScreen:
        arrivals = self.mta.fetch_batch(self._nearby)
        return SubwayScreen(self._nearby, arrivals)

    def _push(self, screen: Screen, epd: EPD) -> None:
        self._stack.append(self._screen)
        self._screen = screen
        logger.info("→ %s (stack depth %d)", type(screen).__name__, len(self._stack))
        self._refresh(epd)

    def _pop(self, epd: EPD) -> None:
        self._screen = self._stack.pop() if self._stack else HomeScreen()
        logger.info("← %s (stack depth %d)", type(self._screen).__name__, len(self._stack))
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
            logger.error("Load failed: %s", exc, exc_info=True)
            return MessageScreen(str(exc)[:50], show_back=True)


def main() -> None:
    debug = "--debug" in sys.argv
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    app = App()

    def _quit(sig: int, _: object) -> None:
        logger.info("Signal %d — shutting down", sig)
        sys.exit(0)

    signal.signal(signal.SIGINT, _quit)
    signal.signal(signal.SIGTERM, _quit)

    try:
        app.run()
    except SystemExit:
        pass
    except Exception as exc:
        logger.exception("Fatal: %s", exc)
        sys.exit(1)
    finally:
        try:
            import RPi.GPIO as GPIO
            GPIO.cleanup()
            logger.info("GPIO cleaned up")
        except ImportError:
            pass


if __name__ == "__main__":
    main()
