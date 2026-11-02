"""Turns the user's inputs and the weather into a 7-day irrigation plan."""

from datetime import date

from .crops import CROPS, METHODS, SOILS
from .fao56 import crop_stage, season_length, water_balance


class InputError(ValueError):
    """The request is missing something or has a value out of range."""


def parse_inputs(body):
    if not isinstance(body, dict):
        raise InputError("Send the plan request as JSON.")
    try:
        lat, lon = float(body["lat"]), float(body["lon"])
    except (KeyError, TypeError, ValueError):
        raise InputError("Pick a location on the map.")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise InputError("That location is outside the map.")

    crop, soil, method = body.get("crop"), body.get("soil"), body.get("method")
    if crop not in CROPS:
        raise InputError("Choose a crop.")
    if soil not in SOILS:
        raise InputError("Choose a soil type.")
    if method not in METHODS:
        raise InputError("Choose an irrigation method.")

    def as_date(field, label, required):
        raw = body.get(field)
        if not raw:
            if required:
                raise InputError(f"Enter the {label}.")
            return None
        try:
            return date.fromisoformat(raw)
        except (TypeError, ValueError):
            raise InputError(f"The {label} is not a valid date.")

    perennial = CROPS[crop]["stages"] is None
    planting = as_date("planting_date", "planting date", required=not perennial)
    last_wet = as_date("last_wet_date", "date the field was last fully watered", required=False)
    return {
        "lat": round(lat, 4), "lon": round(lon, 4),
        "crop": crop, "soil": soil, "method": method,
        "planting_date": planting, "last_wet_date": last_wet,
    }


def build_plan(inputs, forecast, climate=None, climate_error=None):
    crop = CROPS[inputs["crop"]]
    soil = SOILS[inputs["soil"]]
    method = METHODS[inputs["method"]]
    today = forecast["today"]
    days = forecast["days"]
    first_day = days[0]["date"]
    warnings = []

    planting = inputs["planting_date"] or date(today.year - 5, 1, 1)  # perennials: long established
    if planting > today:
        raise InputError("The planting date is in the future. Plans start once the crop is in the ground.")
    length = season_length(crop)
    if length is not None and (today - planting).days >= length:
        raise InputError(
            f"A {crop['name'].lower()} crop planted on {planting.isoformat()} would have been "
            f"harvested by now (season of about {length} days). Check the planting date."
        )
    last_wet = inputs["last_wet_date"]
    if last_wet and last_wet > today:
        raise InputError("The last watering date can't be in the future.")

    # The balance starts with the soil at field capacity on the latest of:
    # the first day of weather data, the last full watering, or planting.
    start = max(d for d in (first_day, last_wet, planting) if d is not None)
    if last_wet is None:
        warnings.append(
            f"No last watering date was given, so the soil is assumed to have been fully wet on "
            f"{start.isoformat()}. Enter the real date for a more accurate plan."
        )
    elif last_wet < first_day:
        warnings.append(
            f"Weather history only goes back to {first_day.isoformat()}, so the soil is assumed "
            f"full on that day rather than on {last_wet.isoformat()}. The real soil may be drier."
        )

    records = water_balance(days, crop, soil["taw_mm_per_m"], planting, start, today, method["efficiency"])
    past = [r for r in records if not r["forecast"] and r["stage"]]
    future = [r for r in records if r["forecast"]]
    if not future:
        raise InputError("There is no forecast data for the coming days at this location.")

    if any(r["ks"] is not None and r["ks"] < 1 for r in past):
        warnings.append("The crop was probably under water stress on some recent days (soil below the readily available water).")
    if any(r["depletion"] is not None and r["taw"] and r["depletion"] >= r["taw"] for r in past):
        warnings.append("The soil reached wilting point recently. Irrigate as soon as possible.")
    if any(r["stage"] is None for r in future):
        warnings.append("The season ends during this week; days after harvest need no water.")

    events = [r for r in future if r["irrigation_net"] > 0]
    stage, kc, root = crop_stage(crop, (today - planting).days)
    today_rec = next((r for r in records if r["date"] == today.isoformat()), None)
    net_total = round(sum(r["irrigation_net"] for r in future), 1)
    gross_total = round(sum(r["irrigation_gross"] for r in future), 1)

    summary = {
        "today": today.isoformat(),
        "stage": stage,
        "days_after_planting": None if inputs["planting_date"] is None else (today - planting).days,
        "kc_today": round(kc, 2) if kc else None,
        "root_depth_m": round(root, 2) if root else None,
        "taw_mm": round(soil["taw_mm_per_m"] * root, 1) if root else None,
        "raw_mm": round(crop["p"] * soil["taw_mm_per_m"] * root, 1) if root else None,
        "soil_depletion_start_of_today_mm": _depletion_before(records, today),
        "week_et0_mm": round(sum(r["et0"] for r in future), 1),
        "week_crop_water_use_mm": round(sum(r["etc"] for r in future), 1),
        "week_rain_mm": round(sum(r["rain"] for r in future), 1),
        "week_effective_rain_mm": round(sum(r.get("effective_rain", 0.0) for r in future), 1),
        "irrigation_net_mm": net_total,
        "irrigation_gross_mm": gross_total,
        "irrigation_litres_per_ha": round(gross_total * 10_000),
        "irrigation_events": [
            {"date": r["date"], "net_mm": r["irrigation_net"], "gross_mm": r["irrigation_gross"],
             "litres_per_ha": round(r["irrigation_gross"] * 10_000)}
            for r in events
        ],
        "next_irrigation": events[0]["date"] if events else None,
        "irrigate_today": bool(today_rec and today_rec["irrigation_net"] > 0),
    }

    climate_context = None
    if climate:
        month = climate["months"][today.month - 1]
        climate_context = {**climate, "this_month": month}
    elif climate_error:
        warnings.append(climate_error)

    return {
        "inputs": {
            **{k: v for k, v in inputs.items() if k not in ("planting_date", "last_wet_date")},
            "planting_date": inputs["planting_date"].isoformat() if inputs["planting_date"] else None,
            "last_wet_date": last_wet.isoformat() if last_wet else None,
            "crop_name": crop["name"],
            "soil_name": soil["name"],
            "method_name": method["name"],
            "efficiency": method["efficiency"],
            "depletion_fraction_p": crop["p"],
        },
        "location": {"timezone": forecast.get("timezone"), "elevation_m": forecast.get("elevation")},
        "balance_start": start.isoformat(),
        "summary": summary,
        "days": records,
        "climate": climate_context,
        "warnings": warnings,
    }


def _depletion_before(records, today):
    """Depletion at the end of yesterday, i.e. the soil state this morning."""
    previous = [r for r in records if r["date"] < today.isoformat() and r["depletion"] is not None]
    return previous[-1]["depletion"] if previous else 0.0
