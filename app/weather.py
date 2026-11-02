"""Weather (Open-Meteo) and long-term climate (NASA POWER) for a point."""

import calendar
from datetime import date, datetime, timedelta, timezone

import requests

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/climatology/point"
PAST_DAYS = 14
FORECAST_DAYS = 7  # today plus the next six days
TIMEOUT = 25


class WeatherError(Exception):
    """A data source could not be reached or returned something unusable."""


def fetch_forecast(lat, lon, session=requests):
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "et0_fao_evapotranspiration,precipitation_sum,temperature_2m_max,temperature_2m_min",
        "past_days": PAST_DAYS,
        "forecast_days": FORECAST_DAYS,
        "timezone": "auto",
    }
    try:
        res = session.get(OPEN_METEO_URL, params=params, timeout=TIMEOUT)
        data = res.json()
    except (requests.RequestException, ValueError) as exc:
        raise WeatherError("Could not reach the Open-Meteo weather service. Check the connection and try again.") from exc
    if res.status_code != 200 or "daily" not in data:
        reason = data.get("reason") if isinstance(data, dict) else None
        raise WeatherError(f"Open-Meteo returned an error{': ' + reason if reason else ''}.")

    daily = data["daily"]
    days = []
    for i, iso in enumerate(daily["time"]):
        et0 = daily["et0_fao_evapotranspiration"][i]
        if et0 is None:
            continue  # no reference ET for this day; skip rather than guess
        days.append({
            "date": date.fromisoformat(iso),
            "et0": et0,
            "rain": daily["precipitation_sum"][i] or 0.0,
            "tmax": daily["temperature_2m_max"][i],
            "tmin": daily["temperature_2m_min"][i],
        })
    if not days:
        raise WeatherError("Open-Meteo has no evapotranspiration data for this location.")

    offset = timedelta(seconds=data.get("utc_offset_seconds", 0))
    today = (datetime.now(timezone.utc) + offset).date()
    return {
        "today": today,
        "timezone": data.get("timezone"),
        "elevation": data.get("elevation"),
        "days": days,
    }


def fetch_climate(lat, lon, session=requests):
    """Monthly normals (rain in mm/month, mean temperature) from NASA POWER."""
    params = {
        "parameters": "PRECTOTCORR,T2M",
        "community": "AG",
        "latitude": lat,
        "longitude": lon,
        "format": "JSON",
    }
    try:
        res = session.get(NASA_POWER_URL, params=params, timeout=TIMEOUT * 2)
        data = res.json()
        values = data["properties"]["parameter"]
        rain, temp = values["PRECTOTCORR"], values["T2M"]
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        raise WeatherError("NASA POWER climate data is unavailable right now.") from exc

    months = []
    for m in range(1, 13):
        key = calendar.month_abbr[m].upper()
        mm_per_day, t = rain.get(key), temp.get(key)
        if mm_per_day is None or mm_per_day < 0 or t is None or t <= -999:
            raise WeatherError("NASA POWER returned incomplete climate data for this location.")
        days_in_month = 28.25 if m == 2 else calendar.monthrange(2001, m)[1]
        months.append({
            "month": calendar.month_abbr[m],
            "rain_mm": round(mm_per_day * days_in_month),
            "temp_c": round(t, 1),
        })
    return {
        "months": months,
        "annual_rain_mm": sum(m["rain_mm"] for m in months),
        "period": data.get("header", {}).get("range", "long-term average"),
    }
