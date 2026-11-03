from datetime import date

import pytest

from app import create_app
from app.season import (SeasonError, build_season, effective_rain_month, monthly_et0,
                        parse_season_inputs, pond_size)
from app.weather import WeatherError
from tests.test_api import fake_forecast

TODAY = date(2026, 11, 3)


def month(temp=17.0, rng=13.0, rh=60.0, wind=2.4, solar=21.0, rain=30):
    return {"month": "x", "rain_mm": rain, "temp_c": temp, "temp_range_c": rng, "rh_pct": rh,
            "wind_ms": wind, "solar_mj": solar}


def test_et0_matches_fao56_example_17_bangkok_april():
    # FAO-56 Example 17: Bangkok (13°44'N, 2 m), April. Tmax 34.8, Tmin 25.6, ea 2.85 kPa,
    # Rs 22.65 MJ/m2/day, u2 2 m/s, March 29.2 °C, May 30.4 °C. Published ET0 = 5.72 mm/day.
    es = (0.6108 * 2.718281828 ** (17.27 * 34.8 / (34.8 + 237.3)) + 0.6108 * 2.718281828 ** (17.27 * 25.6 / (25.6 + 237.3))) / 2
    months = [month() for _ in range(12)]
    months[2]["temp_c"] = 29.2
    months[3] = month(temp=30.2, rng=9.2, rh=2.85 / es * 100, wind=2.0, solar=22.65)
    months[4]["temp_c"] = 30.4
    et0 = monthly_et0(months, 13 + 44 / 60, 2)
    assert et0[3] == pytest.approx(5.72, abs=0.15)


def test_et0_needs_complete_climate():
    months = [month() for _ in range(12)]
    months[5]["rh_pct"] = None
    with pytest.raises(SeasonError, match="incomplete"):
        monthly_et0(months, 8.6, 2000)


@pytest.mark.parametrize("p,expected", [(0, 0.0), (100, 84.0), (250, 150.0), (300, 155.0)])
def test_effective_rain_usda_scs(p, expected):
    assert effective_rain_month(p) == pytest.approx(expected)


def test_pond_holds_the_requested_volume():
    size = pond_size(294.5)
    assert size["depth_m"] == 2.0
    assert size["dug_volume_m3"] == pytest.approx(294.5, rel=0.01)
    assert size["top_side_m"] - size["bottom_side_m"] == pytest.approx(2 * size["depth_m"] * size["side_slope"], abs=0.1)


def test_small_ponds_are_shallower_so_the_bottom_stays_usable():
    size = pond_size(6)
    assert size["depth_m"] < 2.0
    assert size["bottom_side_m"] >= 0.5


def test_no_pond_when_no_water_is_needed():
    assert pond_size(0) is None


CLIMATE = {"months": [month(rain=r) for r in (10, 20, 49, 79, 72, 90, 172, 169, 104, 33, 17, 12)],
           "elevation_m": 2070, "period": "2001–2025 average"}


def inputs(**over):
    base = {"lat": 8.656, "lon": 39.035, "crop": "wheat", "method": "furrow", "start": date(2026, 9, 9),
            "area_m2": 500.0, "lining": "lined"}
    base.update(over)
    return base


def test_season_runs_from_planting_to_harvest_and_adds_up():
    r = build_season(inputs(), CLIMATE, TODAY)
    assert r["season_days"] == 135
    assert r["harvest_date"] == "2027-01-21"
    assert len(r["days"]) == 135
    t = r["totals"]
    assert t["gross_mm"] == pytest.approx(t["net_mm"] / 0.6, rel=0.01)
    assert t["gross_m3"] == pytest.approx(t["gross_mm"] * 500 / 1000, rel=0.01)
    assert sum(m["days"] for m in r["monthly"]) == 135
    assert sum(m["m3"] for m in r["monthly"]) == pytest.approx(t["gross_m3"], abs=0.5)


def test_pond_covers_only_the_rest_of_the_season_plus_losses():
    r = build_season(inputs(), CLIMATE, TODAY)
    assert r["planted"] is True
    assert r["remaining_days"] < r["season_days"]
    assert r["pond"]["storage_m3"] == pytest.approx(r["totals"]["remaining_m3"] / 0.85, rel=0.01)
    unlined = build_season(inputs(lining="unlined"), CLIMATE, TODAY)
    assert unlined["pond"]["storage_m3"] > r["pond"]["storage_m3"]


def test_future_planting_plans_the_whole_season():
    r = build_season(inputs(start=date(2027, 1, 15)), CLIMATE, TODAY)
    assert r["planted"] is False
    assert r["remaining_days"] == r["season_days"]
    assert r["totals"]["remaining_m3"] == r["totals"]["gross_m3"]


def test_drip_needs_less_water_than_furrow():
    furrow = build_season(inputs(), CLIMATE, TODAY)["totals"]["gross_mm"]
    drip = build_season(inputs(method="drip"), CLIMATE, TODAY)["totals"]["gross_mm"]
    assert drip == pytest.approx(furrow * 0.6 / 0.9, rel=0.01)


def test_perennial_coffee_uses_the_next_twelve_months():
    r = build_season(inputs(crop="coffee"), CLIMATE, TODAY)
    assert r["perennial"] is True
    assert r["season_days"] == 365


@pytest.mark.parametrize("body,msg", [
    ({"lat": 8.6, "lon": 39.0, "crop": "rice", "method": "drip", "planting_date": "2026-11-01", "area_m2": 500}, "crop"),
    ({"lat": 8.6, "lon": 39.0, "crop": "wheat", "method": "drip", "planting_date": "soon", "area_m2": 500}, "planting date"),
    ({"lat": 8.6, "lon": 39.0, "crop": "wheat", "method": "drip", "planting_date": "2026-11-01", "area_m2": 0}, "field size"),
    ({"lat": 8.6, "lon": 39.0, "crop": "wheat", "method": "drip", "planting_date": "2029-01-01", "area_m2": 500}, "within about a year"),
])
def test_season_inputs_are_checked(body, msg):
    with pytest.raises(SeasonError, match=msg):
        parse_season_inputs(body, TODAY)


def client(climate=CLIMATE):
    def fake_climate(lat, lon):
        if isinstance(climate, Exception):
            raise climate
        return climate
    return create_app(fetch_forecast=fake_forecast, fetch_climate=fake_climate, today=lambda: TODAY).test_client()


BODY = {"lat": 8.656, "lon": 39.035, "crop": "wheat", "method": "furrow", "planting_date": "2026-09-09",
        "area_m2": 500, "lining": "lined"}


def test_season_endpoint_returns_budget_and_pond():
    data = client().post("/api/season", json=BODY).get_json()
    assert data["harvest_date"] == "2027-01-21"
    assert data["pond"]["size"]["depth_m"] == 2.0
    assert len(data["et0_by_month"]) == 12


def test_season_endpoint_rejects_bad_input_and_reports_climate_problems():
    assert client().post("/api/season", json={**BODY, "area_m2": -5}).status_code == 400
    assert client(WeatherError("NASA POWER climate data is unavailable right now.")).post("/api/season", json=BODY).status_code == 502
    old = {"months": [{"month": "x", "rain_mm": 10, "temp_c": 17.0} for _ in range(12)]}
    assert client(old).post("/api/season", json=BODY).status_code == 502
