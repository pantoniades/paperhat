"""Tests for StationFinder, MTAService, haversine, and data models."""

from __future__ import annotations

import json
import time as time_mod
from unittest.mock import patch

import pytest
import responses
from google.transit import gtfs_realtime_pb2

from services.mta import (
    _ROUTE_FEED,
    Arrival,
    MTAService,
    Station,
    StationFinder,
    StopInfo,
    _haversine,
)

# ── haversine ───────────────────────────────────────────────────


class TestHaversine:
    def test_same_point_is_zero(self):
        assert _haversine(0, 0, 0, 0) == 0.0

    def test_known_distance(self):
        # Statue of Liberty → Empire State Building ≈ 8.3 km
        d = _haversine(40.6892, -74.0445, 40.7484, -73.9857)
        assert d == pytest.approx(8_300, rel=0.05)

    def test_symmetry(self):
        assert _haversine(40.0, -74.0, 41.0, -73.0) == pytest.approx(
            _haversine(41.0, -73.0, 40.0, -74.0)
        )


# ── data models ─────────────────────────────────────────────────


class TestStopInfo:
    def test_frozen(self):
        s = StopInfo("239", ("2", "3"), "Manhattan", "Flatbush")
        with pytest.raises(AttributeError):
            s.gtfs_id = "999"


class TestStation:
    def test_routes_deduplicates(self):
        s = Station(
            name="X", lat=0, lon=0,
            stops=[
                StopInfo("A", ("2", "3"), "", ""),
                StopInfo("B", ("3", "4"), "", ""),
            ],
        )
        assert s.routes == ["2", "3", "4"]

    def test_routes_preserves_order(self):
        s = Station(
            name="X", lat=0, lon=0,
            stops=[
                StopInfo("A", ("B", "Q"), "", ""),
                StopInfo("B", ("A", "C"), "", ""),
            ],
        )
        assert s.routes == ["B", "Q", "A", "C"]

    def test_labels_from_first_stop(self):
        s = Station(
            name="X", lat=0, lon=0,
            stops=[StopInfo("A", (), "Manhattan", "Brooklyn")],
        )
        assert s.north_label == "Manhattan"
        assert s.south_label == "Brooklyn"

    def test_labels_default_when_no_stops(self):
        s = Station(name="X", lat=0, lon=0, stops=[])
        assert s.north_label == "Uptown"
        assert s.south_label == "Downtown"


class TestArrival:
    def test_frozen(self):
        a = Arrival(line="2", direction="N", minutes=3)
        with pytest.raises(AttributeError):
            a.line = "3"


# ── route → feed mapping ───────────────────────────────────────


class TestRouteFeedMapping:
    @pytest.mark.parametrize("route", list("1234567"))
    def test_numbered_routes(self, route):
        assert _ROUTE_FEED[route] == "123456S7"

    @pytest.mark.parametrize("route,feed", [
        ("A", "ACE"), ("C", "ACE"), ("E", "ACE"),
        ("B", "BDFM"), ("D", "BDFM"), ("F", "BDFM"), ("M", "BDFM"),
        ("G", "G"),
        ("J", "JZ"), ("Z", "JZ"),
        ("N", "NQRW"), ("Q", "NQRW"), ("R", "NQRW"), ("W", "NQRW"),
        ("L", "L"),
    ])
    def test_letter_routes(self, route, feed):
        assert _ROUTE_FEED[route] == feed


# ── StationFinder._build_stations ───────────────────────────────


class TestBuildStations:
    def test_groups_by_complex_id(self, mta_stations_api_response):
        result = StationFinder._build_stations(mta_stations_api_response)
        names = {s.name for s in result}
        assert "7 Av" in names
        seven_av = [s for s in result if s.name == "7 Av"][0]
        assert len(seven_av.stops) == 2  # D25 + D26

    def test_skips_missing_coordinates(self):
        rows = [{"complex_id": "1", "stop_name": "X", "gtfs_stop_id": "Z01", "daytime_routes": "A"}]
        assert StationFinder._build_stations(rows) == []

    def test_skips_invalid_coordinates(self):
        rows = [{
            "complex_id": "1", "stop_name": "X", "gtfs_stop_id": "Z01",
            "daytime_routes": "A", "gtfs_latitude": "bad", "gtfs_longitude": "-73.0",
        }]
        assert StationFinder._build_stations(rows) == []

    def test_parses_routes(self, mta_stations_api_response):
        result = StationFinder._build_stations(mta_stations_api_response)
        gap = [s for s in result if s.name == "Grand Army Plaza"][0]
        assert gap.stops[0].routes == ("2", "3")


# ── StationFinder.nearest (with mocked HTTP) ───────────────────


class TestStationFinderNearest:
    @responses.activate
    def test_returns_n_closest(self, mta_stations_api_response, tmp_path):
        responses.get(
            "https://data.ny.gov/resource/39hk-dx4f.json?$limit=1000",
            json=mta_stations_api_response,
        )
        finder = StationFinder()
        finder._CACHE = tmp_path / "stations.json"  # isolate cache

        result = finder.nearest(40.6742, -73.9708, n=2)

        assert len(result) == 2
        assert result[0].distance_m <= result[1].distance_m

    @responses.activate
    def test_populates_distance(self, mta_stations_api_response, tmp_path):
        responses.get(
            "https://data.ny.gov/resource/39hk-dx4f.json?$limit=1000",
            json=mta_stations_api_response,
        )
        finder = StationFinder()
        finder._CACHE = tmp_path / "stations.json"

        result = finder.nearest(40.6742, -73.9708)
        assert all(s.distance_m > 0 for s in result)

    def test_uses_fresh_cache(self, mta_stations_api_response, tmp_path):
        cache = tmp_path / "stations.json"
        cache.write_text(json.dumps(mta_stations_api_response))
        finder = StationFinder()
        finder._CACHE = cache

        with patch.object(finder, "_fresh", return_value=True):
            result = finder.nearest(40.6742, -73.9708)

        assert len(result) > 0  # no HTTP call needed

    @responses.activate
    def test_falls_back_to_stale_cache(self, mta_stations_api_response, tmp_path):
        cache = tmp_path / "stations.json"
        cache.write_text(json.dumps(mta_stations_api_response))
        responses.get(
            "https://data.ny.gov/resource/39hk-dx4f.json?$limit=1000",
            body=ConnectionError("no network"),
        )
        finder = StationFinder()
        finder._CACHE = cache

        with patch.object(finder, "_fresh", return_value=False):
            result = finder.nearest(40.6742, -73.9708)

        assert len(result) > 0

    @responses.activate
    def test_raises_without_cache_or_network(self, tmp_path):
        responses.get(
            "https://data.ny.gov/resource/39hk-dx4f.json?$limit=1000",
            body=ConnectionError("no network"),
        )
        finder = StationFinder()
        finder._CACHE = tmp_path / "nonexistent.json"

        with pytest.raises(ConnectionError):
            finder.nearest(40.6742, -73.9708)


# ── MTAService.fetch ────────────────────────────────────────────


def _build_gtfs_feed(stop_updates: list[tuple[str, str, float]]) -> bytes:
    """Build a serialized GTFS-RT FeedMessage.

    Each tuple is (route_id, stop_id, arrival_unix_time).
    """
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = int(time_mod.time())
    for route_id, stop_id, arrival_time in stop_updates:
        entity = feed.entity.add()
        entity.id = f"{route_id}-{stop_id}-{int(arrival_time)}"
        tu = entity.trip_update
        tu.trip.trip_id = f"trip-{entity.id}"
        tu.trip.route_id = route_id
        stu = tu.stop_time_update.add()
        stu.stop_id = stop_id
        stu.arrival.time = int(arrival_time)
    return feed.SerializeToString()


class TestMTAServiceFetch:
    @responses.activate
    def test_parses_arrivals(self, sample_station):
        now = time_mod.time()
        data = _build_gtfs_feed([
            ("2", "239N", now + 180),
            ("3", "239S", now + 300),
        ])
        responses.get(
            "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
            body=data, content_type="application/octet-stream",
        )
        result = MTAService().fetch(sample_station)

        assert len(result) == 2
        assert result[0].line == "2"
        assert result[0].direction == "N"
        assert result[0].minutes in (2, 3)  # timing-sensitive

    @responses.activate
    def test_filters_unrelated_stops(self, sample_station):
        now = time_mod.time()
        data = _build_gtfs_feed([
            ("2", "239N", now + 180),
            ("5", "999N", now + 60),  # different station
        ])
        responses.get(
            "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
            body=data, content_type="application/octet-stream",
        )
        result = MTAService().fetch(sample_station)
        assert len(result) == 1
        assert result[0].line == "2"

    @responses.activate
    def test_filters_past_arrivals(self, sample_station):
        now = time_mod.time()
        data = _build_gtfs_feed([
            ("2", "239N", now - 60),  # in the past
            ("3", "239S", now + 300),
        ])
        responses.get(
            "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
            body=data, content_type="application/octet-stream",
        )
        result = MTAService().fetch(sample_station)
        assert len(result) == 1
        assert result[0].line == "3"

    @responses.activate
    def test_sorts_by_minutes(self, sample_station):
        now = time_mod.time()
        data = _build_gtfs_feed([
            ("3", "239N", now + 600),
            ("2", "239S", now + 60),
        ])
        responses.get(
            "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
            body=data, content_type="application/octet-stream",
        )
        result = MTAService().fetch(sample_station)
        assert result[0].minutes <= result[1].minutes

    @responses.activate
    def test_direction_from_stop_suffix(self, sample_station):
        now = time_mod.time()
        data = _build_gtfs_feed([("2", "239N", now + 120), ("3", "239S", now + 180)])
        responses.get(
            "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
            body=data, content_type="application/octet-stream",
        )
        result = MTAService().fetch(sample_station)
        dirs = {a.direction for a in result}
        assert dirs == {"N", "S"}

    @responses.activate
    def test_queries_correct_feeds(self):
        """Station with B/D routes should only hit the BDFM feed."""
        station = Station(
            name="Test", lat=0, lon=0,
            stops=[StopInfo("D25", ("B", "D"), "", "")],
        )
        now = time_mod.time()
        data = _build_gtfs_feed([("B", "D25N", now + 120)])
        responses.get(
            "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",
            body=data, content_type="application/octet-stream",
        )
        result = MTAService().fetch(station)

        assert len(result) == 1
        assert len(responses.calls) == 1  # only BDFM feed queried

    @responses.activate
    def test_continues_on_feed_error(self):
        """If one feed fails, results from the other should still appear."""
        station = Station(
            name="Test", lat=0, lon=0,
            stops=[
                StopInfo("239", ("2",), "", ""),
                StopInfo("D25", ("B",), "", ""),
            ],
        )
        now = time_mod.time()
        responses.get(
            "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
            body=ConnectionError("fail"),
        )
        data = _build_gtfs_feed([("B", "D25N", now + 120)])
        responses.get(
            "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",
            body=data, content_type="application/octet-stream",
        )
        result = MTAService().fetch(station)
        assert len(result) == 1
        assert result[0].line == "B"


class TestFetchBatch:
    @responses.activate
    def test_batch_distributes_to_correct_stations(self):
        """Two stations sharing a feed should each get their own arrivals."""
        stations = [
            Station(name="A", lat=0, lon=0,
                    stops=[StopInfo("239", ("2",), "", "")]),
            Station(name="B", lat=0, lon=0,
                    stops=[StopInfo("238", ("3",), "", "")]),
        ]
        now = time_mod.time()
        data = _build_gtfs_feed([
            ("2", "239N", now + 120),
            ("3", "238S", now + 180),
        ])
        responses.get(
            "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
            body=data, content_type="application/octet-stream",
        )
        results = MTAService().fetch_batch(stations)

        assert len(results) == 2
        assert len(results[0]) == 1
        assert results[0][0].line == "2"
        assert len(results[1]) == 1
        assert results[1][0].line == "3"

    @responses.activate
    def test_batch_queries_each_feed_once(self):
        """Two stations on the same feed should produce only one HTTP call."""
        stations = [
            Station(name="A", lat=0, lon=0,
                    stops=[StopInfo("239", ("2",), "", "")]),
            Station(name="B", lat=0, lon=0,
                    stops=[StopInfo("238", ("3",), "", "")]),
        ]
        now = time_mod.time()
        data = _build_gtfs_feed([
            ("2", "239N", now + 120),
            ("3", "238S", now + 180),
        ])
        responses.get(
            "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
            body=data, content_type="application/octet-stream",
        )
        MTAService().fetch_batch(stations)
        assert len(responses.calls) == 1  # single feed queried once

    @responses.activate
    def test_fetch_delegates_to_fetch_batch(self, sample_station):
        """fetch() for a single station should use fetch_batch internally."""
        now = time_mod.time()
        data = _build_gtfs_feed([("2", "239N", now + 120)])
        responses.get(
            "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs",
            body=data, content_type="application/octet-stream",
        )
        result = MTAService().fetch(sample_station)
        assert len(result) == 1
        assert result[0].line == "2"
