from datetime import date, timedelta

import pytest

from app.crops import CROPS, ROOT_INITIAL_M
from app.fao56 import adjust_kc, crop_stage, effective_rain, stress_coefficient, water_balance, wind_at_2m

WHEAT = CROPS["wheat"]  # stages 20/25/60/30, Kc 0.30/1.15/0.25, roots to 1.25 m


def test_initial_stage_uses_kc_ini_and_shallow_roots():
    stage, kc, root = crop_stage(WHEAT, 0)
    assert stage == "initial"
    assert kc == pytest.approx(0.30)
    assert root == pytest.approx(ROOT_INITIAL_M)


def test_development_stage_interpolates_kc_linearly():
    # Halfway through development (day 20 + 12.5) Kc is halfway between 0.30 and 1.15.
    stage, kc, _ = crop_stage(WHEAT, 20)
    assert stage == "development"
    assert kc == pytest.approx(0.30)
    _, kc_mid_dev, _ = crop_stage(WHEAT, 30)
    assert kc_mid_dev == pytest.approx(0.30 + 10 / 25 * (1.15 - 0.30))


def test_mid_season_is_flat_and_roots_are_full():
    stage, kc, root = crop_stage(WHEAT, 60)
    assert stage == "mid-season"
    assert kc == pytest.approx(1.15)
    assert root == pytest.approx(1.25)


def test_late_season_declines_to_kc_end():
    stage, kc, _ = crop_stage(WHEAT, 20 + 25 + 60 + 15)
    assert stage == "late season"
    assert kc == pytest.approx(1.15 + 15 / 30 * (0.25 - 1.15))


def test_no_crop_before_planting_or_after_harvest():
    assert crop_stage(WHEAT, -1) == (None, None, None)
    assert crop_stage(WHEAT, 135) == (None, None, None)


def test_perennial_is_always_mature():
    stage, kc, root = crop_stage(CROPS["coffee"], 4000)
    assert (stage, kc, root) == ("mature", 0.95, 1.20)


def test_effective_rain():
    assert effective_rain(0) == 0
    assert effective_rain(1.9) == 0          # light showers evaporate
    assert effective_rain(10) == pytest.approx(8.0)
    assert effective_rain(None) == 0


def test_stress_coefficient_fao56_eq84():
    assert stress_coefficient(10, taw=100, raw=50) == 1.0
    assert stress_coefficient(75, taw=100, raw=50) == pytest.approx(0.5)
    assert stress_coefficient(100, taw=100, raw=50) == 0.0


def _days(start, et0s, rains=None):
    rains = rains or [0.0] * len(et0s)
    return [{"date": start + timedelta(days=i), "et0": e, "rain": r} for i, (e, r) in enumerate(zip(et0s, rains))]


def test_balance_accumulates_crop_water_use():
    planting = date(2026, 1, 1)
    start = planting + timedelta(days=60)  # mid-season, Kc 1.15, roots 1.25 m
    days = _days(start, [5.0, 5.0, 5.0])
    today = start + timedelta(days=10)     # all three days are history
    out = water_balance(days, WHEAT, 155, planting, start, today, 0.6)
    assert [r["etc"] for r in out] == [5.75, 5.75, 5.75]
    assert [r["depletion"] for r in out] == [5.8, 11.5, 17.2]  # rounded to 0.1 mm
    assert all(r["irrigation_net"] == 0 for r in out)


def test_rain_refills_and_cannot_overfill():
    planting = date(2026, 1, 1)
    start = planting + timedelta(days=60)
    days = _days(start, [5.0, 5.0], [0.0, 40.0])
    out = water_balance(days, WHEAT, 155, planting, start, start + timedelta(days=5), 0.6)
    assert out[1]["depletion"] == 0.0  # surplus drains away, depletion never negative


def test_forecast_irrigates_when_raw_is_reached():
    # Mid-season wheat on loam: TAW = 155 * 1.25 = 193.75 mm, RAW = 0.55 * TAW = 106.6 mm.
    planting = date(2026, 1, 1)
    start = planting + timedelta(days=60)
    days = _days(start, [10.0] * 12)       # 11.5 mm/day crop use
    today = start                          # every day is forecast
    out = water_balance(days, WHEAT, 155, planting, start, today, 0.75)
    events = [r for r in out if r["irrigation_net"] > 0]
    assert len(events) == 1
    event = events[0]
    assert event["date"] == (start + timedelta(days=9)).isoformat()  # 10 x 11.5 = 115 > 106.6
    assert event["irrigation_net"] == pytest.approx(115.0)
    assert event["irrigation_gross"] == pytest.approx(round(115.0 / 0.75, 1))
    assert event["depletion"] == 0.0


def test_past_days_never_irrigate_and_stress_slows_use():
    planting = date(2026, 1, 1)
    start = planting + timedelta(days=60)
    days = _days(start, [10.0] * 20)
    out = water_balance(days, WHEAT, 155, planting, start, start + timedelta(days=30), 0.6)
    assert all(r["irrigation_net"] == 0 for r in out)
    assert out[-1]["ks"] < 1.0
    assert out[-1]["depletion"] <= out[-1]["taw"]


def test_capped_waterings_refill_in_smaller_doses():
    # Same field as above, but no watering may put in more than 35 mm.
    planting = date(2026, 1, 1)
    start = planting + timedelta(days=60)
    days = _days(start, [10.0] * 12)       # 11.5 mm/day crop use
    out = water_balance(days, WHEAT, 155, planting, start, start, 0.75, max_net_mm=35)
    events = [r for r in out if r["irrigation_net"] > 0]
    assert all(e["irrigation_net"] <= 35 for e in events)
    assert events[0]["date"] == (start + timedelta(days=3)).isoformat()  # 4 x 11.5 = 46 > 35
    assert all(r["depletion"] <= r["raw"] for r in out)


def test_wind_at_2m_follows_eq_47():
    assert wind_at_2m(3.2) == pytest.approx(3.2 * 0.748, abs=0.01)


def test_kc_adjustment_follows_eq_62():
    # Dry, windy air raises Kc mid for a 1 m crop: (0.04*2 - 0.004*(-15)) * (1/3)**0.3 = 0.1007
    wheat = adjust_kc(WHEAT, u2=4.0, rh_min=30.0)
    assert wheat["kc"][1] == pytest.approx(1.15 + 0.1007, abs=1e-3)
    assert wheat["kc"][2] == WHEAT["kc"][2]  # Kc end 0.25 < 0.45: harvested dry, not adjusted
    assert WHEAT["kc"][1] == 1.15             # the table itself is left alone
    # Standard climate: no change. Values outside the valid range are clipped.
    assert adjust_kc(WHEAT, 2.0, 45.0)["kc"] == WHEAT["kc"]
    assert adjust_kc(WHEAT, 20.0, 5.0)["kc"] == adjust_kc(WHEAT, 6.0, 20.0)["kc"]
