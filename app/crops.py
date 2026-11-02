"""Crop and soil tables used by the water balance.

Every number comes from FAO Irrigation and Drainage Paper No. 56
(Allen, Pereira, Raes & Smith, 1998), "Crop evapotranspiration":
  - Kc values: Table 12 (single crop coefficients, sub-humid climate, RHmin ~45%, u2 ~2 m/s)
  - Stage lengths: Table 11 (lengths of crop development stages, days)
  - Rooting depth and depletion fraction p: Table 22
  - Soil water held between field capacity and wilting point: Table 19

Where FAO-56 gives a range, the middle of the range is used.
"""

# kc: (initial, mid-season, end of late season)
# stages: (initial, development, mid-season, late season) in days
# root_max_m: maximum effective rooting depth in metres
# p: fraction of total available water the crop can use before it is stressed
CROPS = {
    "wheat": {
        "name": "Wheat (spring)",
        "kc": (0.30, 1.15, 0.25),        # Table 12, spring wheat, harvested dry
        "stages": (20, 25, 60, 30),       # Table 11, spring wheat
        "root_max_m": 1.25,               # Table 22: 1.0-1.5 m
        "p": 0.55,                        # Table 22
    },
    "teff": {
        # Teff is not listed in FAO-56. Values for small grains (barley/oats,
        # Table 12) are used as an approximation, with a shorter season and
        # shallower roots as is typical for teff. Treat results as indicative.
        "name": "Teff (approx. small grains)",
        "kc": (0.30, 1.15, 0.25),
        "stages": (15, 25, 50, 30),
        "root_max_m": 0.60,
        "p": 0.55,
    },
    "maize": {
        "name": "Maize (grain)",
        "kc": (0.30, 1.20, 0.35),         # Table 12, maize field corn (grain)
        "stages": (30, 40, 50, 30),       # Table 11, maize grain (typical values)
        "root_max_m": 1.35,               # Table 22: 1.0-1.7 m
        "p": 0.55,                        # Table 22
    },
    "tomato": {
        "name": "Tomato",
        "kc": (0.60, 1.15, 0.80),         # Table 12, tomato
        "stages": (30, 40, 40, 25),       # Table 11, tomato
        "root_max_m": 1.10,               # Table 22: 0.7-1.5 m
        "p": 0.40,                        # Table 22
    },
    "onion": {
        "name": "Onion (dry bulb)",
        "kc": (0.70, 1.05, 0.75),         # Table 12, onion dry
        "stages": (15, 25, 70, 40),       # Table 11, onion dry
        "root_max_m": 0.45,               # Table 22: 0.3-0.6 m
        "p": 0.30,                        # Table 22
    },
    "coffee": {
        # Perennial: treated as a mature crop all year (no growth stages).
        "name": "Coffee (mature, bare ground)",
        "kc": (0.90, 0.95, 0.95),         # Table 12, coffee, bare ground cover
        "stages": None,
        "root_max_m": 1.20,               # Table 22: 0.9-1.5 m
        "p": 0.40,                        # Table 22
    },
}

# Rooting depth used at sowing/planting (FAO-56 suggests 0.15-0.20 m).
ROOT_INITIAL_M = 0.20

# Total available water per metre of soil: (field capacity - wilting point) x 1000.
# Table 19 ranges for (theta_FC - theta_WP), middle value used.
SOILS = {
    "sand":       {"name": "Sand",                 "taw_mm_per_m": 80},   # 0.05-0.11
    "sandy_loam": {"name": "Sandy loam",           "taw_mm_per_m": 130},  # 0.11-0.15
    "loam":       {"name": "Loam",                 "taw_mm_per_m": 155},  # 0.13-0.18
    "clay_loam":  {"name": "Clay loam",            "taw_mm_per_m": 155},  # 0.13-0.18
    "clay":       {"name": "Clay (e.g. vertisol)", "taw_mm_per_m": 160},  # 0.12-0.20
}

# Application efficiency: share of the water applied that ends up in the root zone.
# Typical design values (FAO Irrigation Water Management Training Manual No. 4).
METHODS = {
    "furrow":    {"name": "Furrow / basin", "efficiency": 0.60},
    "sprinkler": {"name": "Sprinkler",      "efficiency": 0.75},
    "drip":      {"name": "Drip",           "efficiency": 0.90},
}
