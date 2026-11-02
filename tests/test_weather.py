import pytest
import requests

from app.weather import WeatherError, fetch_climate, fetch_forecast


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if self.error:
            raise self.error
        return self.response


OPEN_METEO = {
    "utc_offset_seconds": 10800,
    "timezone": "Africa/Addis_Ababa",
    "elevation": 1936.0,
    "daily": {
        "time": ["2026-11-01", "2026-11-02", "2026-11-03"],
        "et0_fao_evapotranspiration": [5.9, None, 5.7],
        "precipitation_sum": [0.0, 1.2, None],
        "temperature_2m_max": [26.0, 25.5, 24.9],
        "temperature_2m_min": [11.0, 10.4, 10.1],
    },
}


def test_forecast_parses_days_and_skips_missing_et0():
    session = FakeSession(FakeResponse(200, OPEN_METEO))
    result = fetch_forecast(8.75, 38.98, session=session)
    assert [d["date"].isoformat() for d in result["days"]] == ["2026-11-01", "2026-11-03"]
    assert result["days"][1]["rain"] == 0.0  # missing rain counts as none
    params = session.calls[0][1]
    assert params["past_days"] == 14 and params["forecast_days"] == 7
    assert "et0_fao_evapotranspiration" in params["daily"]


def test_forecast_network_and_api_errors_are_friendly():
    with pytest.raises(WeatherError, match="Could not reach"):
        fetch_forecast(0, 0, session=FakeSession(error=requests.ConnectionError()))
    with pytest.raises(WeatherError, match="Latitude must be"):
        fetch_forecast(0, 0, session=FakeSession(FakeResponse(400, {"error": True, "reason": "Latitude must be in range"})))


def _power(rain=0.5, temp=15.0):
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    return {
        "properties": {"parameter": {
            "PRECTOTCORR": {m: rain for m in months},
            "T2M": {m: temp for m in months},
        }},
        "header": {"range": "25-year climatology (January 2001 - December 2025)"},
    }


def test_climate_converts_mm_per_day_to_monthly_totals():
    result = fetch_climate(8.75, 38.98, session=FakeSession(FakeResponse(200, _power(rain=2.0))))
    jan = result["months"][0]
    assert jan == {"month": "Jan", "rain_mm": 62, "temp_c": 15.0}
    assert result["months"][3]["rain_mm"] == 60  # April has 30 days
    assert result["period"].startswith("25-year")


def test_climate_fill_values_are_rejected():
    with pytest.raises(WeatherError):
        fetch_climate(0, 0, session=FakeSession(FakeResponse(200, _power(rain=-999.0))))
    with pytest.raises(WeatherError):
        fetch_climate(0, 0, session=FakeSession(FakeResponse(500, {"messages": ["error"]})))
