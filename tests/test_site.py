from datetime import timedelta

import pytest

from app import create_app
from app.site import SiteError, fetch_elevation, fetch_soil, texture_class
from tests.test_api import BODY, TODAY, failing_climate, fake_forecast


@pytest.mark.parametrize("sand,silt,clay,expected", [
    (92, 4, 4, "sand"),
    (82, 10, 8, "loamy sand"),
    (65, 25, 10, "sandy loam"),
    (40, 40, 20, "loam"),
    (20, 65, 15, "silt loam"),
    (5, 88, 7, "silt"),
    (60, 15, 25, "sandy clay loam"),
    (29, 34, 37, "clay loam"),       # the Bishoftu example field
    (10, 55, 35, "silty clay loam"),
    (50, 10, 40, "sandy clay"),
    (5, 50, 45, "silty clay"),
    (20, 20, 60, "clay"),
])
def test_usda_texture_triangle(sand, silt, clay, expected):
    assert texture_class(sand, silt, clay) == expected


class FakeResponse:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, data, status=200):
        self.data, self.status, self.calls = data, status, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return FakeResponse(self.data, self.status)


def layer(name, values, factor=10):
    labels = ["0-5cm", "5-15cm", "15-30cm", "30-60cm"]
    return {"name": name, "unit_measure": {"d_factor": factor},
            "depths": [{"label": lab, "values": {"mean": v}} for lab, v in zip(labels, values)]}


def soilgrids(clay, sand, silt, ph=(71, 71, 72, 72), soc=(228, 180, 117, 60)):
    return {"properties": {"layers": [layer("clay", clay), layer("sand", sand), layer("silt", silt),
                                      layer("phh2o", ph), layer("soc", soc)]}}


def test_fetch_soil_averages_the_root_zone_by_layer_thickness():
    session = FakeSession(soilgrids(clay=(376, 370, 363, 400), sand=(289, 290, 287, 260), silt=(335, 340, 350, 340)))
    soil = fetch_soil(8.656, 39.035, session=session)
    # weights 5, 10, 15, 30 cm over 60 cm
    assert soil["clay_pct"] == pytest.approx((37.6 * 5 + 37.0 * 10 + 36.3 * 15 + 40.0 * 30) / 60, abs=0.05)
    assert soil["texture"] == "clay loam"
    assert soil["suggested_soil"] == "clay_loam"
    assert soil["ph"] == pytest.approx(7.2, abs=0.05)
    assert soil["likely_vertisol"] is False
    params = dict((k, v) for k, v in session.calls[0][1] if k in ("lat", "lon"))
    assert params == {"lat": 8.656, "lon": 39.035}


def test_heavy_clay_is_flagged_as_likely_vertisol():
    soil = fetch_soil(9.0, 38.7, session=FakeSession(soilgrids(clay=(520,) * 4, sand=(180,) * 4, silt=(300,) * 4)))
    assert soil["suggested_soil"] == "clay"
    assert soil["likely_vertisol"] is True


def test_spot_without_soil_data_raises_a_clear_error():
    empty = {"properties": {"layers": [layer("clay", (None,) * 4), layer("sand", (None,) * 4), layer("silt", (None,) * 4)]}}
    with pytest.raises(SiteError, match="no soil estimate"):
        fetch_soil(8.9, 38.7, session=FakeSession(empty))


def test_soilgrids_error_status_raises():
    with pytest.raises(SiteError, match="SoilGrids"):
        fetch_soil(8.9, 38.7, session=FakeSession({"detail": "busy"}, status=503))


def test_fetch_elevation_reads_the_first_value():
    assert fetch_elevation(8.656, 39.035, session=FakeSession({"elevation": [1896.0]})) == 1896.0


def test_fetch_elevation_bad_response_raises():
    with pytest.raises(SiteError):
        fetch_elevation(8.656, 39.035, session=FakeSession({"error": True}))


def make_client(soil=None, elevation=None, ai=True, explained=None):
    def fake_soil(lat, lon):
        if isinstance(soil, Exception):
            raise soil
        return soil

    def fake_elevation(lat, lon):
        if isinstance(elevation, Exception):
            raise elevation
        return elevation

    def fake_explain(plan, language):
        if explained is not None:
            explained.append(plan)
        return {"text": "ok", "model": "test", "language": "English"}

    app = create_app(fetch_forecast=fake_forecast, fetch_climate=failing_climate, explain=fake_explain,
                     ai_available=lambda: ai, fetch_soil=fake_soil, fetch_elevation=fake_elevation)
    return app.test_client()


def test_site_endpoint_returns_soil_and_elevation():
    client = make_client(soil={"texture": "clay loam", "suggested_soil": "clay_loam"}, elevation=1896.0)
    data = client.get("/api/site?lat=8.656&lon=39.035").get_json()
    assert data["soil"]["suggested_soil"] == "clay_loam"
    assert data["elevation_m"] == 1896.0
    assert data["errors"] == []


def test_site_endpoint_still_answers_when_one_source_fails():
    client = make_client(soil=SiteError("The soil database (SoilGrids) could not be reached."), elevation=1896.0)
    data = client.get("/api/site?lat=8.656&lon=39.035").get_json()
    assert data["soil"] is None
    assert data["elevation_m"] == 1896.0
    assert "SoilGrids" in data["errors"][0]


def test_site_endpoint_rejects_bad_coordinates():
    client = make_client(soil={}, elevation=0.0)
    assert client.get("/api/site?lat=abc&lon=1").status_code == 400
    assert client.get("/api/site?lat=95&lon=1").status_code == 400


def test_plan_includes_weather_days_and_warning_codes():
    data = make_client().post("/api/plan", json=BODY).get_json()
    assert len(data["weather"]) == 21
    assert data["weather"][0]["date"] == (TODAY - timedelta(days=14)).isoformat()
    assert sum(d["forecast"] for d in data["weather"]) == 7
    codes = [w["code"] for w in data["warning_codes"]]
    assert "assumed_wet" in codes and "climate_unavailable" in codes
    assert len(data["warning_codes"]) == len(data["warnings"])


def test_explain_uses_the_plan_sent_by_the_page_when_the_server_forgot_it():
    explained = []
    client = make_client(explained=explained)
    plan = client.post("/api/plan", json=BODY).get_json()
    res = client.post("/api/explain", json={"plan_id": "not-on-this-server", "plan": plan, "language": "am"})
    assert res.status_code == 200
    assert explained[0]["summary"] == plan["summary"]


def test_explain_without_a_usable_plan_is_refused():
    client = make_client()
    assert client.post("/api/explain", json={"plan_id": "missing"}).status_code == 404
    assert client.post("/api/explain", json={"plan_id": "missing", "plan": {"x": 1}}).status_code == 404
