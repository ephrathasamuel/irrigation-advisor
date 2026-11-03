"""Whole-season water budget from planting to harvest, and the storage pond to dig for it.

ET0 for each month comes from long-term NASA POWER averages through the FAO-56 Penman-Monteith
equation (Allen et al. 1998, eqs. 6-43 with monthly data). Each day of the season gets its crop
coefficient from the growth stage, so ETc = Kc x ET0. Useful rain uses the USDA-SCS monthly method
used by FAO CROPWAT. The irrigation need is ETc minus useful rain, divided by the watering method's
efficiency. The pond must hold that water plus what it loses to evaporation and seepage.
"""

import calendar
import math
from datetime import date, timedelta

from .crops import CROPS, METHODS
from .fao56 import crop_stage, season_length

# Share of stored water lost before use (evaporation from the open surface plus seepage).
POND_LOSSES = {"lined": 0.15, "unlined": 0.40}
POND_DEPTH_M = 2.0   # typical depth for hand- or machine-dug farm ponds
POND_SIDE_SLOPE = 1.0  # 1 m out for every 1 m down, so the walls stay stable


class SeasonError(ValueError):
    """Missing or invalid input, or climate data that can't support the budget."""


def _sat_vp(t):
    """Saturation vapour pressure, kPa (FAO-56 eq. 11)."""
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


def _extraterrestrial_radiation(lat_deg, doy):
    """Ra in MJ/m2/day (FAO-56 eqs. 21-25)."""
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)
    delta = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(delta))))
    return 24 * 60 / math.pi * 0.0820 * dr * (
        ws * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(ws))


def monthly_et0(months, lat, elevation_m):
    """Reference ET0 (mm/day) for each calendar month from monthly climate averages.

    months: 12 dicts with temp_c, temp_range_c, rh_pct, wind_ms, solar_mj.
    """
    needed = ("temp_c", "temp_range_c", "rh_pct", "wind_ms", "solar_mj")
    if len(months) != 12 or any(m.get(k) is None for m in months for k in needed):
        raise SeasonError("Long-term climate data for this spot is incomplete, so a season budget can't be made.")
    z = elevation_m or 0.0
    pressure = 101.3 * ((293 - 0.0065 * z) / 293) ** 5.26              # eq. 7
    gamma = 0.000665 * pressure                                         # eq. 8
    out = []
    for i, m in enumerate(months):
        t = m["temp_c"]
        tmax, tmin = t + m["temp_range_c"] / 2, t - m["temp_range_c"] / 2
        es = (_sat_vp(tmax) + _sat_vp(tmin)) / 2                        # eq. 12
        ea = m["rh_pct"] / 100 * es                                      # eq. 19 with mean RH
        slope = 4098 * _sat_vp(t) / (t + 237.3) ** 2                     # eq. 13
        doy = (date(2001, i + 1, 15) - date(2001, 1, 1)).days + 1
        ra = _extraterrestrial_radiation(lat, doy)
        rs = m["solar_mj"]
        rso = (0.75 + 2e-5 * z) * ra                                     # eq. 37
        rns = 0.77 * rs                                                  # eq. 38, albedo 0.23
        ratio = min(rs / rso, 1.0) if rso > 0 else 0.5
        rnl = 4.903e-9 * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 \
            * (0.34 - 0.14 * math.sqrt(max(ea, 0))) * (1.35 * ratio - 0.35)  # eq. 39
        rn = rns - rnl
        g = 0.07 * (months[(i + 1) % 12]["temp_c"] - months[i - 1]["temp_c"])  # eq. 43
        u2 = m["wind_ms"]
        et0 = (0.408 * slope * (rn - g) + gamma * 900 / (t + 273) * u2 * (es - ea)) \
            / (slope + gamma * (1 + 0.34 * u2))                          # eq. 6
        out.append(round(max(et0, 0.0), 2))
    return out


def effective_rain_month(p):
    """Useful rain for a month (mm), USDA-SCS method as used in FAO CROPWAT."""
    return p * (125 - 0.2 * p) / 125 if p <= 250 else 125 + 0.1 * p


def pond_size(volume_m3, depth=POND_DEPTH_M, slope=POND_SIDE_SLOPE):
    """Square pond with sloped sides holding volume_m3: returns top and bottom side lengths.

    The pit is a frustum: V = d/3 (t^2 + b^2 + t*b) with t = b + 2*slope*d.
    """
    if volume_m3 <= 0:
        return None
    k = 2 * slope * depth
    # Shallow ponds for small volumes, so the bottom stays wider than about 0.5 m.
    while depth > 1.0 and volume_m3 / depth < k * k / 3 + 1:
        depth -= 0.5
        k = 2 * slope * depth
    disc = k * k - 4 * (k * k / 3 - volume_m3 / depth)
    bottom = max((-k + math.sqrt(max(disc, 0))) / 2, 0.5)
    top = bottom + k
    return {"depth_m": round(depth, 1), "top_side_m": round(top, 1), "bottom_side_m": round(bottom, 1),
            "side_slope": slope, "dug_volume_m3": round(depth / 3 * (top * top + bottom * bottom + top * bottom), 1)}


def parse_season_inputs(body, today):
    if not isinstance(body, dict):
        raise SeasonError("Send the request as JSON.")
    try:
        lat, lon = float(body["lat"]), float(body["lon"])
    except (KeyError, TypeError, ValueError):
        raise SeasonError("Pick a location on the map.")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise SeasonError("That location is outside the map.")
    crop, method = body.get("crop"), body.get("method")
    if crop not in CROPS:
        raise SeasonError("Choose a crop.")
    if method not in METHODS:
        raise SeasonError("Choose an irrigation method.")
    try:
        start = date.fromisoformat(body.get("planting_date") or "")
    except ValueError:
        raise SeasonError("Enter the planting date (it can be a future date).")
    if not (today - timedelta(days=400) <= start <= today + timedelta(days=400)):
        raise SeasonError("Choose a planting date within about a year of today.")
    try:
        area = float(body.get("area_m2"))
    except (TypeError, ValueError):
        raise SeasonError("Enter the field size.")
    if not (1 <= area <= 1_000_000):
        raise SeasonError("The field size must be between 1 m² and 100 hectares.")
    lining = body.get("lining", "lined")
    if lining not in POND_LOSSES:
        raise SeasonError("Choose whether the pond is lined.")
    return {"lat": lat, "lon": lon, "crop": crop, "method": method, "start": start, "area_m2": area, "lining": lining}


def build_season(inputs, climate, today):
    """Daily need from planting to harvest, monthly totals, and the pond to store the water."""
    crop, method = CROPS[inputs["crop"]], METHODS[inputs["method"]]
    et0_by_month = monthly_et0(climate["months"], inputs["lat"], climate.get("elevation_m"))
    peff_by_month = [effective_rain_month(m["rain_mm"]) for m in climate["months"]]
    length = season_length(crop) or 365  # perennials: the next 12 months
    start, area, eff = inputs["start"], inputs["area_m2"], method["efficiency"]

    days, monthly = [], {}
    for i in range(length):
        d = start + timedelta(days=i)
        m = d.month - 1
        stage, kc, _ = crop_stage(crop, i if crop["stages"] else 5 * 365)
        dim = calendar.monthrange(d.year, d.month)[1]
        et0 = et0_by_month[m]
        etc = (kc or 0) * et0
        rain = climate["months"][m]["rain_mm"] / dim
        peff = peff_by_month[m] / dim
        net = max(etc - peff, 0.0)
        gross = net / eff
        days.append({"date": d.isoformat(), "stage": stage, "kc": round(kc or 0, 2), "et0": et0,
                     "etc": round(etc, 2), "rain": round(rain, 2), "effective_rain": round(peff, 2),
                     "net_mm": round(net, 2), "gross_mm": round(gross, 2),
                     "litres": round(gross * area), "remaining": d >= today})
        key = d.strftime("%Y-%m")
        row = monthly.setdefault(key, {"month": key, "days": 0, "etc_mm": 0.0, "effective_rain_mm": 0.0,
                                       "gross_mm": 0.0, "m3": 0.0})
        row["days"] += 1
        row["etc_mm"] += etc
        row["effective_rain_mm"] += peff
        row["gross_mm"] += gross
        row["m3"] += gross * area / 1000

    def total(key, only_remaining=False):
        return sum(x[key] for x in days if x["remaining"] or not only_remaining)

    gross_mm = total("gross_mm")
    remaining_gross_mm = total("gross_mm", True)
    loss = POND_LOSSES[inputs["lining"]]
    pond_m3 = remaining_gross_mm * area / 1000 / (1 - loss)
    peak = max(days, key=lambda x: x["litres"])

    for row in monthly.values():
        for k in ("etc_mm", "effective_rain_mm", "gross_mm", "m3"):
            row[k] = round(row[k], 1)

    return {
        "inputs": {"lat": round(inputs["lat"], 4), "lon": round(inputs["lon"], 4), "crop": inputs["crop"],
                   "method": inputs["method"], "planting_date": start.isoformat(), "area_m2": area,
                   "lining": inputs["lining"], "efficiency": eff},
        "harvest_date": (start + timedelta(days=length - 1)).isoformat(),
        "season_days": length,
        "perennial": crop["stages"] is None,
        "planted": start <= today,
        "remaining_days": sum(1 for x in days if x["remaining"]),
        "totals": {
            "etc_mm": round(total("etc"), 1),
            "effective_rain_mm": round(total("effective_rain"), 1),
            "net_mm": round(total("net_mm"), 1),
            "gross_mm": round(gross_mm, 1),
            "gross_m3": round(gross_mm * area / 1000, 1),
            "remaining_gross_mm": round(remaining_gross_mm, 1),
            "remaining_m3": round(remaining_gross_mm * area / 1000, 1),
            "peak_day": {"date": peak["date"], "litres": peak["litres"], "gross_mm": peak["gross_mm"]},
            "average_litres_per_day": round(sum(x["litres"] for x in days if x["remaining"]) / max(1, sum(1 for x in days if x["remaining"]))),
        },
        "pond": {"storage_m3": round(pond_m3, 1), "loss_share": loss, "size": pond_size(pond_m3)},
        "monthly": list(monthly.values()),
        "days": days,
        "et0_by_month": et0_by_month,
        "climate_period": climate.get("period"),
    }
