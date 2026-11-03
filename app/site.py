"""What the ground is like at a field: soil texture from SoilGrids and elevation from Open-Meteo.

SoilGrids (ISRIC, 250 m global soil maps) gives sand, silt and clay percentages, pH and organic
carbon by depth. The root zone (0-60 cm) average is classified with the USDA texture triangle and
mapped to the app's five soil choices, so a farmer who is unsure can start from a measured suggestion.
"""

import requests

SOILGRIDS_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
TIMEOUT = 25

# SoilGrids depth layers in the root zone and their thickness in cm, used as averaging weights.
DEPTHS = {"0-5cm": 5, "5-15cm": 10, "15-30cm": 15, "30-60cm": 30}
PROPERTIES = ("sand", "silt", "clay", "phh2o", "soc")

# USDA texture class -> the app's soil id.
TEXTURE_TO_SOIL = {
    "sand": "sand", "loamy sand": "sand",
    "sandy loam": "sandy_loam",
    "loam": "loam", "silt loam": "loam", "silt": "loam",
    "sandy clay loam": "clay_loam", "clay loam": "clay_loam", "silty clay loam": "clay_loam",
    "sandy clay": "clay", "silty clay": "clay", "clay": "clay",
}


class SiteError(Exception):
    """A soil or elevation service failed or had no data for the spot."""


def texture_class(sand, silt, clay):
    """USDA soil texture triangle. Inputs are percentages that add up to about 100."""
    if silt + 1.5 * clay < 15:
        return "sand"
    if silt + 1.5 * clay < 30:
        return "loamy sand"
    if (7 <= clay < 20 and sand > 52 and silt + 2 * clay >= 30) or (clay < 7 and silt < 50 and silt + 2 * clay >= 30):
        return "sandy loam"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52:
        return "loam"
    if (silt >= 50 and 12 <= clay < 27) or (50 <= silt < 80 and clay < 12):
        return "silt loam"
    if silt >= 80 and clay < 12:
        return "silt"
    if 20 <= clay < 35 and silt < 28 and sand > 45:
        return "sandy clay loam"
    if 27 <= clay < 40 and 20 < sand <= 45:
        return "clay loam"
    if 27 <= clay < 40 and sand <= 20:
        return "silty clay loam"
    if clay >= 35 and sand > 45:
        return "sandy clay"
    if clay >= 40 and silt >= 40:
        return "silty clay"
    return "clay"


def fetch_soil(lat, lon, session=requests):
    params = [("lon", lon), ("lat", lat), ("value", "mean")]
    params += [("property", p) for p in PROPERTIES] + [("depth", d) for d in DEPTHS]
    try:
        res = session.get(SOILGRIDS_URL, params=params, timeout=TIMEOUT)
        data = res.json()
    except (requests.RequestException, ValueError) as exc:
        raise SiteError("The soil database (SoilGrids) could not be reached.") from exc
    if res.status_code != 200 or "properties" not in data:
        raise SiteError("The soil database (SoilGrids) returned an error.")

    values = {}
    for layer in data["properties"].get("layers", []):
        factor = layer.get("unit_measure", {}).get("d_factor") or 1
        total, weight = 0.0, 0
        for depth in layer.get("depths", []):
            mean = depth.get("values", {}).get("mean")
            thickness = DEPTHS.get(depth.get("label"))
            if mean is not None and thickness:
                total += mean / factor * thickness
                weight += thickness
        if weight:
            values[layer["name"]] = total / weight

    if not all(k in values for k in ("sand", "silt", "clay")):
        # Water bodies, towns and some rock outcrops have no soil estimate.
        raise SiteError("There is no soil estimate for this exact spot. Choose the soil type yourself.")

    texture = texture_class(values["sand"], values["silt"], values["clay"])
    return {
        "sand_pct": round(values["sand"], 1),
        "silt_pct": round(values["silt"], 1),
        "clay_pct": round(values["clay"], 1),
        "ph": round(values["phh2o"], 1) if "phh2o" in values else None,
        "organic_carbon_g_per_kg": round(values["soc"], 1) if "soc" in values else None,
        "texture": texture,
        "suggested_soil": TEXTURE_TO_SOIL[texture],
        "likely_vertisol": values["clay"] >= 40,  # dark cracking clays ("black cotton soil")
        "depth": "0-60 cm average",
        "source": "SoilGrids 2.0 (ISRIC), 250 m resolution",
    }


def fetch_elevation(lat, lon, session=requests):
    try:
        res = session.get(ELEVATION_URL, params={"latitude": lat, "longitude": lon}, timeout=TIMEOUT)
        data = res.json()
        return float(data["elevation"][0])
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
        raise SiteError("The elevation service could not be reached.") from exc
