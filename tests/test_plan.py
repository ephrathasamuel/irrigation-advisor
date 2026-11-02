from datetime import date, timedelta

import pytest

from app.plan import InputError, build_plan, parse_inputs

TODAY = date(2026, 11, 2)


def forecast(et0=6.0, rain=0.0, past=14, future=7):
    first = TODAY - timedelta(days=past)
    days = [{"date": first + timedelta(days=i), "et0": et0, "rain": rain, "tmax": 25, "tmin": 10}
            for i in range(past + future)]
    return {"today": TODAY, "timezone": "Africa/Addis_Ababa", "elevation": 1900, "days": days}


def inputs(**overrides):
    body = {"lat": 8.75, "lon": 38.98, "crop": "wheat", "soil": "loam", "method": "furrow",
            "planting_date": (TODAY - timedelta(days=70)).isoformat(), "last_wet_date": None}
    body.update(overrides)
    return parse_inputs(body)


def test_parse_rejects_bad_input():
    with pytest.raises(InputError):
        parse_inputs({"lat": "x", "lon": 1})
    with pytest.raises(InputError):
        inputs(crop="banana")
    with pytest.raises(InputError):
        inputs(planting_date="not a date")
    with pytest.raises(InputError):
        inputs(lat=95)


def test_perennial_needs_no_planting_date():
    parsed = inputs(crop="coffee", planting_date=None)
    plan = build_plan(parsed, forecast())
    assert plan["summary"]["stage"] == "mature"


def test_future_planting_and_finished_season_are_rejected():
    with pytest.raises(InputError):
        build_plan(inputs(planting_date=(TODAY + timedelta(days=3)).isoformat()), forecast())
    with pytest.raises(InputError):
        build_plan(inputs(planting_date=(TODAY - timedelta(days=200)).isoformat()), forecast())


def test_dry_hot_week_needs_irrigation():
    plan = build_plan(inputs(), forecast(et0=7.0))
    s = plan["summary"]
    assert s["irrigation_events"], "a dry week at 7 mm/day must trigger irrigation"
    assert s["irrigation_litres_per_ha"] == round(s["irrigation_gross_mm"] * 10_000)
    assert s["irrigation_gross_mm"] == pytest.approx(s["irrigation_net_mm"] / 0.6, rel=0.01)
    assert len([d for d in plan["days"] if d["forecast"]]) == 7


def test_steady_rain_means_no_irrigation():
    plan = build_plan(inputs(), forecast(et0=4.0, rain=10.0))
    assert plan["summary"]["irrigation_events"] == []
    assert plan["summary"]["next_irrigation"] is None


def test_last_watering_date_sets_the_start_and_missing_one_is_flagged():
    plan = build_plan(inputs(), forecast())
    assert any("No last watering date" in w for w in plan["warnings"])
    wet = (TODAY - timedelta(days=2)).isoformat()
    plan = build_plan(inputs(last_wet_date=wet), forecast())
    assert plan["balance_start"] == wet
    assert not any("No last watering date" in w for w in plan["warnings"])


def test_climate_context_is_attached_for_this_month():
    climate = {"months": [{"month": m, "rain_mm": i * 10, "temp_c": 15.0} for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])],
        "annual_rain_mm": 660, "period": "2001-2025"}
    plan = build_plan(inputs(), forecast(), climate)
    assert plan["climate"]["this_month"]["month"] == "Nov"


def test_climate_failure_becomes_a_warning_not_an_error():
    plan = build_plan(inputs(), forecast(), None, "NASA POWER climate data is unavailable right now.")
    assert plan["climate"] is None
    assert any("NASA POWER" in w for w in plan["warnings"])
