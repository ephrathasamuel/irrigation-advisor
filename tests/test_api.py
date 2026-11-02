from datetime import date, timedelta

import pytest

from app import create_app
from app.advisor import AdvisorError
from app.weather import WeatherError

TODAY = date(2026, 11, 2)


def fake_forecast(lat, lon):
    first = TODAY - timedelta(days=14)
    return {"today": TODAY, "timezone": "Africa/Addis_Ababa", "elevation": 1900,
            "days": [{"date": first + timedelta(days=i), "et0": 6.5, "rain": 0.0, "tmax": 26, "tmin": 11}
                     for i in range(21)]}


def failing_climate(lat, lon):
    raise WeatherError("NASA POWER climate data is unavailable right now.")


BODY = {"lat": 8.75, "lon": 38.98, "crop": "wheat", "soil": "loam", "method": "drip",
        "planting_date": (TODAY - timedelta(days=60)).isoformat()}


@pytest.fixture
def explained():
    return []


def make_client(explained, ai=True, explain_error=None):
    def fake_explain(plan, language):
        if explain_error:
            raise AdvisorError(explain_error)
        explained.append((plan, language))
        return {"text": "This week:\n- Water on Tuesday.", "model": "claude-opus-5-5", "language": "English"}

    app = create_app(fetch_forecast=fake_forecast, fetch_climate=failing_climate,
                     explain=fake_explain, ai_available=lambda: ai)
    return app.test_client()


def test_options_lists_crops_and_ai_status(explained):
    data = make_client(explained, ai=False).get("/api/options").get_json()
    assert {c["id"] for c in data["crops"]} >= {"wheat", "teff", "maize", "tomato", "coffee", "onion"}
    assert data["ai_available"] is False


def test_plan_end_to_end_with_climate_outage(explained):
    res = make_client(explained).post("/api/plan", json=BODY)
    assert res.status_code == 200
    plan = res.get_json()
    assert plan["plan_id"]
    assert plan["summary"]["irrigation_events"]
    assert any("NASA POWER" in w for w in plan["warnings"])


def test_plan_validation_error(explained):
    res = make_client(explained).post("/api/plan", json={**BODY, "soil": "rock"})
    assert res.status_code == 400
    assert "soil" in res.get_json()["error"]


def test_weather_outage_returns_502():
    def down(lat, lon):
        raise WeatherError("Could not reach the Open-Meteo weather service.")
    app = create_app(fetch_forecast=down, fetch_climate=failing_climate, ai_available=lambda: False)
    res = app.test_client().post("/api/plan", json=BODY)
    assert res.status_code == 502
    assert "Open-Meteo" in res.get_json()["error"]


def test_explain_uses_the_stored_plan(explained):
    client = make_client(explained)
    plan = client.post("/api/plan", json=BODY).get_json()
    res = client.post("/api/explain", json={"plan_id": plan["plan_id"], "language": "am"})
    assert res.status_code == 200
    stored, language = explained[0]
    assert language == "am"
    assert stored["summary"] == plan["summary"]  # the AI sees exactly what the user saw


def test_explain_without_key_or_with_unknown_plan(explained):
    assert make_client(explained, ai=False).post("/api/explain", json={"plan_id": "x"}).status_code == 503
    assert make_client(explained).post("/api/explain", json={"plan_id": "nope"}).status_code == 404


def test_explain_failure_is_reported(explained):
    client = make_client(explained, explain_error="The AI service is busy (rate limit). Try again in a minute.")
    plan = client.post("/api/plan", json=BODY).get_json()
    res = client.post("/api/explain", json={"plan_id": plan["plan_id"]})
    assert res.status_code == 502
    assert "busy" in res.get_json()["error"]
