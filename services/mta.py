"""MTA subway: station discovery + real-time arrivals.

Station metadata comes from the MTA open-data portal (data.ny.gov).
Real-time arrivals come from GTFS-RT protobuf feeds (no key required).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path

import requests
from google.transit import gtfs_realtime_pb2

logger = logging.getLogger(__name__)

# ── GTFS-RT feed URLs (one per line group) ──────────────────────

_FEEDS: dict[str, str] = {
    "123456S7": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
    "ACE":      "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace",
    "BDFM":     "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",
    "G":        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-g",
    "JZ":       "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-jz",
    "NQRW":     "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-nqrw",
    "L":        "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l",
    "SI":       "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-si",
}

_ROUTE_FEED: dict[str, str] = {
    r: k for k, url in _FEEDS.items() for r in k if r.isalpha()
} | {str(n): "123456S7" for n in range(1, 8)} | {"S": "123456S7", "SI": "SI"}


# ── data models ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class StopInfo:
    """One GTFS stop inside a station complex."""

    gtfs_id: str
    routes: tuple[str, ...]
    north_label: str
    south_label: str


@dataclass(slots=True)
class Station:
    """A station complex (may span multiple GTFS stops / line groups)."""

    name: str
    lat: float
    lon: float
    stops: list[StopInfo]
    distance_m: float = 0.0

    @property
    def routes(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for s in self.stops:
            for r in s.routes:
                if r not in seen:
                    seen.add(r)
                    out.append(r)
        return out

    @property
    def north_label(self) -> str:
        return self.stops[0].north_label if self.stops else "Uptown"

    @property
    def south_label(self) -> str:
        return self.stops[0].south_label if self.stops else "Downtown"


@dataclass(frozen=True, slots=True)
class Arrival:
    """A single upcoming train."""

    line: str
    direction: str  # "N" or "S"
    arrival_time: float  # unix timestamp

    @property
    def minutes(self) -> int:
        return max(0, int((self.arrival_time - time.time()) / 60))

    @property
    def is_future(self) -> bool:
        return self.arrival_time > time.time()


# ── station finder ──────────────────────────────────────────────


class StationFinder:
    """Discovers nearby subway stations via MTA open data."""

    _API = "https://data.ny.gov/resource/39hk-dx4f.json?$limit=1000"
    _CACHE = Path.home() / ".cache" / "paperhat" / "stations.json"
    _MAX_AGE = 30 * 86_400  # 30 days

    def nearest(self, lat: float, lon: float, n: int = 3) -> list[Station]:
        stations = self._build_stations(self._load())
        for s in stations:
            s.distance_m = _haversine(lat, lon, s.lat, s.lon)
        stations.sort(key=lambda s: s.distance_m)
        return stations[:n]

    # ── data loading with cache ──

    def _load(self) -> list[dict]:
        if self._CACHE.exists() and self._fresh():
            return json.loads(self._CACHE.read_text())
        try:
            data = requests.get(self._API, timeout=15).json()
            self._CACHE.parent.mkdir(parents=True, exist_ok=True)
            self._CACHE.write_text(json.dumps(data))
            return data
        except Exception:
            if self._CACHE.exists():
                return json.loads(self._CACHE.read_text())
            raise

    def _fresh(self) -> bool:
        return (time.time() - self._CACHE.stat().st_mtime) < self._MAX_AGE

    # ── grouping rows → Station objects ──

    @staticmethod
    def _build_stations(rows: list[dict]) -> list[Station]:
        by_complex: dict[str, Station] = {}
        for row in rows:
            cid = row.get("complex_id", row.get("station_id", ""))
            try:
                lat = float(row["gtfs_latitude"])
                lon = float(row["gtfs_longitude"])
            except (KeyError, ValueError, TypeError):
                continue

            stop = StopInfo(
                gtfs_id=row.get("gtfs_stop_id", ""),
                routes=tuple(row.get("daytime_routes", "").split()),
                north_label=row.get("north_direction_label", "Uptown"),
                south_label=row.get("south_direction_label", "Downtown"),
            )

            if cid in by_complex:
                by_complex[cid].stops.append(stop)
            else:
                by_complex[cid] = Station(
                    name=row.get("stop_name", "Unknown"),
                    lat=lat,
                    lon=lon,
                    stops=[stop],
                )

        return list(by_complex.values())


# ── real-time arrivals ──────────────────────────────────────────


class MTAService:
    """Fetches live arrivals from GTFS-RT feeds."""

    def fetch(self, station: Station) -> list[Arrival]:
        """Arrivals for a single station."""
        return self.fetch_batch([station])[0]

    def fetch_batch(self, stations: list[Station]) -> list[list[Arrival]]:
        """Arrivals for multiple stations, querying each feed at most once."""
        # map base stop id → which station indices it belongs to
        stop_to_idx: dict[str, list[int]] = {}
        feed_keys: set[str] = set()
        target_ids: set[str] = set()

        for idx, station in enumerate(stations):
            for stop in station.stops:
                for d in ("N", "S"):
                    target_ids.add(f"{stop.gtfs_id}{d}")
                stop_to_idx.setdefault(stop.gtfs_id, []).append(idx)
                for route in stop.routes:
                    if route in _ROUTE_FEED:
                        feed_keys.add(_ROUTE_FEED[route])

        logger.info("Querying %d feed(s) for %d station(s)", len(feed_keys), len(stations))

        now = time.time()
        results: list[list[Arrival]] = [[] for _ in stations]

        for key in feed_keys:
            url = _FEEDS.get(key)
            if not url:
                continue
            try:
                feed = gtfs_realtime_pb2.FeedMessage()
                feed.ParseFromString(requests.get(url, timeout=15).content)
            except Exception:
                logger.warning("Failed to fetch feed %s", key, exc_info=True)
                continue

            for entity in feed.entity:
                if not entity.HasField("trip_update"):
                    continue
                route = entity.trip_update.trip.route_id
                for stu in entity.trip_update.stop_time_update:
                    if stu.stop_id not in target_ids or stu.arrival.time <= now:
                        continue
                    base_id = stu.stop_id[:-1]
                    arrival = Arrival(
                        line=route,
                        direction="N" if stu.stop_id[-1] == "N" else "S",
                        arrival_time=float(stu.arrival.time),
                    )
                    for si in stop_to_idx.get(base_id, []):
                        results[si].append(arrival)

        for arr_list in results:
            arr_list.sort(key=lambda a: a.arrival_time)
        return results


# ── helpers ─────────────────────────────────────────────────────


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    R = 6_371_000
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))
