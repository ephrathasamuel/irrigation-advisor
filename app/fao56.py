"""FAO-56 crop water use and root-zone soil water balance.

References are to FAO Irrigation and Drainage Paper No. 56 (1998).
All depths are in millimetres of water unless stated otherwise.
"""

from .crops import ROOT_INITIAL_M

# Rain below this depth mostly wets leaves and the soil surface and evaporates.
MIN_EFFECTIVE_RAIN_MM = 2.0
# Share of the remaining rain that reaches the root zone (the rest runs off or
# is lost). A fixed-percentage method; 0.8 is the commonly used value.
EFFECTIVE_RAIN_FRACTION = 0.8


def crop_stage(crop, days_after_planting):
    """Growth stage, crop coefficient Kc and rooting depth (m) for a given day.

    Kc follows the FAO-56 crop coefficient curve (Fig. 34): flat in the initial
    stage, a straight line up during development, flat in mid-season and a
    straight line down in the late season. Roots grow linearly from the
    planting depth to their maximum by the start of mid-season.
    Returns stage None when the crop is not in the field.
    """
    kc_ini, kc_mid, kc_end = crop["kc"]
    if crop["stages"] is None:  # perennial
        return "mature", kc_mid, crop["root_max_m"]

    das = days_after_planting
    l_ini, l_dev, l_mid, l_late = crop["stages"]
    if das < 0 or das >= l_ini + l_dev + l_mid + l_late:
        return None, None, None

    if das < l_ini:
        stage, kc = "initial", kc_ini
    elif das < l_ini + l_dev:
        stage = "development"
        kc = kc_ini + (das - l_ini) / l_dev * (kc_mid - kc_ini)
    elif das < l_ini + l_dev + l_mid:
        stage, kc = "mid-season", kc_mid
    else:
        stage = "late season"
        kc = kc_mid + (das - l_ini - l_dev - l_mid) / l_late * (kc_end - kc_mid)

    grow_days = l_ini + l_dev
    root = ROOT_INITIAL_M + min(das / grow_days, 1.0) * (crop["root_max_m"] - ROOT_INITIAL_M)
    return stage, kc, root


def season_length(crop):
    return None if crop["stages"] is None else sum(crop["stages"])


def effective_rain(rain_mm):
    """Part of a day's rain that refills the root zone."""
    if rain_mm is None or rain_mm < MIN_EFFECTIVE_RAIN_MM:
        return 0.0
    return EFFECTIVE_RAIN_FRACTION * rain_mm


def stress_coefficient(depletion, taw, raw):
    """Water stress coefficient Ks (FAO-56 eq. 84)."""
    if depletion <= raw:
        return 1.0
    if taw <= raw:
        return 0.0
    return max(0.0, (taw - depletion) / (taw - raw))


def water_balance(days, crop, taw_per_m, planting_date, start_date, today, efficiency):
    """Daily root-zone depletion (FAO-56 eq. 85), starting full on start_date.

    days: list of {"date": date, "et0": mm, "rain": mm}, in date order.
    Before today the balance uses what actually happened (no irrigation is
    assumed after start_date, and the crop is slowed down by water stress).
    From today on, the field is irrigated back to field capacity whenever
    depletion passes the readily available water (RAW).

    Returns one record per day from start_date, plus whether the soil ran dry.
    """
    out = []
    depletion = 0.0
    for day in days:
        if day["date"] < start_date:
            continue
        das = (day["date"] - planting_date).days
        stage, kc, root = crop_stage(crop, das)
        forecast = day["date"] >= today
        rec = {
            "date": day["date"].isoformat(),
            "forecast": forecast,
            "et0": round(day["et0"], 2),
            "rain": round(day["rain"] or 0.0, 1),
            "stage": stage,
        }
        if stage is None:
            rec.update(kc=None, etc=0.0, depletion=None, taw=None, raw=None,
                       ks=None, irrigation_net=0.0, irrigation_gross=0.0)
            out.append(rec)
            continue

        taw = taw_per_m * root
        raw = crop["p"] * taw
        peff = effective_rain(day["rain"])
        ks = 1.0 if forecast else stress_coefficient(depletion, taw, raw)
        etc = ks * kc * day["et0"]
        depletion = min(max(depletion - peff + etc, 0.0), taw)

        net = 0.0
        peak = depletion
        if forecast and depletion > raw:
            net = depletion
            depletion = 0.0

        rec.update(
            kc=round(kc, 3),
            root_m=round(root, 2),
            taw=round(taw, 1),
            raw=round(raw, 1),
            ks=round(ks, 2),
            effective_rain=round(peff, 1),
            etc=round(etc, 2),
            depletion=round(depletion, 1),
            depletion_before_irrigation=round(peak, 1),
            irrigation_net=round(net, 1),
            irrigation_gross=round(net / efficiency, 1),
        )
        out.append(rec)
    return out
