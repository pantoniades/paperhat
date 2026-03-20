"""Tests for WeatherService."""

import responses

from services.weather import HourForecast, Weather, WeatherService


class TestWeatherDataclasses:
    def test_hour_forecast_fields(self):
        hf = HourForecast(time="15:00", temp=68, summary="Sunny")
        assert hf.time == "15:00"
        assert hf.temp == 68
        assert hf.summary == "Sunny"

    def test_weather_fields(self, sample_weather):
        assert sample_weather.temp == 72
        assert sample_weather.unit == "F"
        assert len(sample_weather.hourly) == 3


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
        assert result.summary == "Mostly Sunny"
        assert result.wind == "7 mph SW"

    @responses.activate
    def test_fetch_hourly_has_three_entries(self, nws_points_response, nws_forecast_response):
        responses.get("https://api.weather.gov/points/40.6742,-73.9708", json=nws_points_response)
        responses.get(nws_points_response["properties"]["forecastHourly"], json=nws_forecast_response)

        result = WeatherService().fetch()

        assert len(result.hourly) == 3
        assert all(isinstance(h, HourForecast) for h in result.hourly)
        assert result.hourly[0].time == "11:00"
        assert result.hourly[0].temp == 47

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
        assert len(points_calls) == 1  # cached after first call
        assert len(forecast_calls) == 2

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


import pytest  # noqa: E402 (grouped with usage above)
