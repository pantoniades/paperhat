"""Tests for WeatherService."""

import pytest
import responses

from services.weather import DayForecast, HourForecast, Weather, WeatherService


class TestWeatherDataclasses:
    def test_hour_forecast_fields(self):
        hf = HourForecast(time="15:00", temp=68, summary="Sunny")
        assert hf.time == "15:00"
        assert hf.temp == 68
        assert hf.summary == "Sunny"

    def test_weather_fields(self, sample_weather):
        assert sample_weather.temp == 72
        assert sample_weather.unit == "F"
        assert len(sample_weather.hourly) == 12

    def test_day_forecast_fields(self):
        d = DayForecast(name="Monday", high=72, low=58, summary="Sunny")
        assert d.name == "Monday"
        assert d.high == 72
        assert d.low == 58
        assert d.summary == "Sunny"

    def test_day_forecast_low_can_be_none(self):
        d = DayForecast(name="Tonight", high=65, low=None, summary="Clear")
        assert d.low is None


class TestWeatherService:
    @responses.activate
    def test_fetch_returns_weather(self, nws_points_response, nws_forecast_response):
        responses.get("https://api.weather.gov/points/40.6742,-73.9708", json=nws_points_response)
        responses.get(nws_points_response["properties"]["forecastHourly"], json=nws_forecast_response)

        svc = WeatherService()
        result = svc.fetch()

        assert isinstance(result, Weather)
        assert result.temp == 45
        assert result.unit == "F"
        assert result.summary == "Cloudy"
        assert result.wind == "7 mph SW"

    @responses.activate
    def test_fetch_hourly_entries(self, nws_points_response, nws_forecast_response):
        responses.get("https://api.weather.gov/points/40.6742,-73.9708", json=nws_points_response)
        responses.get(nws_points_response["properties"]["forecastHourly"], json=nws_forecast_response)

        result = WeatherService().fetch()

        assert len(result.hourly) == 12
        assert all(isinstance(h, HourForecast) for h in result.hourly)
        assert result.hourly[0].time == "11:00"
        assert result.hourly[0].temp == 46

    @responses.activate
    def test_forecast_url_is_cached(self, nws_points_response, nws_forecast_response):
        responses.get("https://api.weather.gov/points/40.6742,-73.9708", json=nws_points_response)
        forecast_url = nws_points_response["properties"]["forecastHourly"]
        responses.get(forecast_url, json=nws_forecast_response)

        svc = WeatherService()
        svc.fetch()
        svc.fetch()

        points_calls = [c for c in responses.calls if "/points/" in c.request.url]
        forecast_calls = [c for c in responses.calls if "/forecast/" in c.request.url]
        assert len(points_calls) == 1  # forecast URL cached
        assert len(forecast_calls) == 1  # weather result cached for 30m

    @responses.activate
    def test_fetch_raises_on_api_failure(self):
        responses.get("https://api.weather.gov/points/40.6742,-73.9708", status=500)

        with pytest.raises(Exception):
            WeatherService().fetch()

    @responses.activate
    def test_user_agent_header_sent(self, nws_points_response, nws_forecast_response):
        responses.get("https://api.weather.gov/points/40.6742,-73.9708", json=nws_points_response)
        responses.get(nws_points_response["properties"]["forecastHourly"], json=nws_forecast_response)

        WeatherService().fetch()

        assert "paperhat-app" in responses.calls[0].request.headers["User-Agent"]


class TestFetchWeekly:
    @responses.activate
    def test_returns_five_days(self, nws_points_response, nws_daily_response):
        responses.get("https://api.weather.gov/points/40.6742,-73.9708", json=nws_points_response)
        responses.get(nws_points_response["properties"]["forecast"], json=nws_daily_response)

        result = WeatherService().fetch_weekly()

        assert len(result) == 5
        assert all(isinstance(d, DayForecast) for d in result)

    @responses.activate
    def test_pairs_high_low(self, nws_points_response, nws_daily_response):
        responses.get("https://api.weather.gov/points/40.6742,-73.9708", json=nws_points_response)
        responses.get(nws_points_response["properties"]["forecast"], json=nws_daily_response)

        result = WeatherService().fetch_weekly()
        today = result[0]

        assert today.name == "Today"
        assert today.high == 60
        assert today.low == 45
        assert today.summary == "Sunny"

    @responses.activate
    def test_skips_leading_nighttime(self, nws_points_response):
        """If fetched at night, first period is nighttime — should be skipped."""
        periods = [
            {"name": "Tonight", "isDaytime": False, "temperature": 40,
             "temperatureUnit": "F", "shortForecast": "Clear"},
            {"name": "Monday", "isDaytime": True, "temperature": 58,
             "temperatureUnit": "F", "shortForecast": "Sunny"},
            {"name": "Monday Night", "isDaytime": False, "temperature": 42,
             "temperatureUnit": "F", "shortForecast": "Clear"},
        ]
        responses.get("https://api.weather.gov/points/40.6742,-73.9708", json=nws_points_response)
        responses.get(nws_points_response["properties"]["forecast"],
                      json={"properties": {"periods": periods}})

        result = WeatherService().fetch_weekly()

        assert result[0].name == "Monday"
        assert result[0].high == 58
        assert result[0].low == 42

    @responses.activate
    def test_cached_for_two_hours(self, nws_points_response, nws_daily_response):
        responses.get("https://api.weather.gov/points/40.6742,-73.9708", json=nws_points_response)
        responses.get(nws_points_response["properties"]["forecast"], json=nws_daily_response)

        svc = WeatherService()
        svc.fetch_weekly()
        svc.fetch_weekly()

        # Only one forecast call — second was served from cache
        daily_calls = [c for c in responses.calls if c.request.url.endswith("/forecast")]
        assert len(daily_calls) == 1

    @responses.activate
    def test_resolves_urls_once(self, nws_points_response, nws_forecast_response, nws_daily_response):
        """fetch() and fetch_weekly() share the same /points/ call."""
        responses.get("https://api.weather.gov/points/40.6742,-73.9708", json=nws_points_response)
        responses.get(nws_points_response["properties"]["forecastHourly"], json=nws_forecast_response)
        responses.get(nws_points_response["properties"]["forecast"], json=nws_daily_response)

        svc = WeatherService()
        svc.fetch()
        svc.fetch_weekly()

        points_calls = [c for c in responses.calls if "/points/" in c.request.url]
        assert len(points_calls) == 1
