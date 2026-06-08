"""Weather overlay via Open-Meteo (no API key) + a NON-ML solar-drop heuristic.

We fetch hourly cloud cover and wind for the busiest solar buses (projected onto
Czechia) and flag buses where forecast cloud cover is rising — a lightweight,
clearly-labelled heuristic that connects an external signal to grid behaviour.
It is NOT a trained model.
"""
from __future__ import annotations

import httpx

from . import config
from .data_loader import store

# pick the N solar buses with the most installed capacity to sample
_MAX_POINTS = 10


def _solar_sample_points() -> list[dict]:
    ranked = sorted(
        (
            {"bus": b, "solar_mw": v["solar_mw"]}
            for b, v in store.bus_renewable.items()
            if v["solar_mw"] > 0
        ),
        key=lambda d: -d["solar_mw"],
    )[:_MAX_POINTS]
    for p in ranked:
        lon, lat = store.bus_lonlat.get(p["bus"], (None, None))
        p["lon"], p["lat"] = lon, lat
    return [p for p in ranked if p["lon"] is not None]


async def weather_overlay(timestamp: str | None = None) -> dict:
    points = _solar_sample_points()
    if not points:
        return {"points": [], "summary": "No solar buses with coordinates found."}

    lats = ",".join(str(p["lat"]) for p in points)
    lons = ",".join(str(p["lon"]) for p in points)
    params = {
        "latitude": lats,
        "longitude": lons,
        "hourly": "cloud_cover,wind_speed_10m,shortwave_radiation",
        "forecast_days": "2",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(config.OPEN_METEO_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:  # noqa: BLE001
        return {"points": [], "summary": f"Weather unavailable: {e}"}

    # Open-Meteo returns a list of per-location objects when multiple coords given
    blocks = data if isinstance(data, list) else [data]
    out_points = []
    rising = 0
    for p, block in zip(points, blocks):
        hourly = block.get("hourly", {})
        cloud = hourly.get("cloud_cover", []) or []
        wind = hourly.get("wind_speed_10m", []) or []
        rad = hourly.get("shortwave_radiation", []) or []
        now = cloud[0] if cloud else None
        in3h = cloud[3] if len(cloud) > 3 else now
        trend = (in3h - now) if (now is not None and in3h is not None) else 0
        solar_risk = trend >= 15  # cloud cover rising >=15 pts in 3h
        if solar_risk:
            rising += 1
        out_points.append(
            {
                "bus": p["bus"],
                "lon": p["lon"],
                "lat": p["lat"],
                "solar_mw": round(p["solar_mw"], 1),
                "cloud_cover_now": now,
                "cloud_cover_3h": in3h,
                "cloud_trend_3h": trend,
                "wind_speed_10m": wind[0] if wind else None,
                "shortwave_radiation": rad[0] if rad else None,
                "solar_risk": solar_risk,
            }
        )

    if rising:
        summary = (
            f"Heuristic: cloud cover rising at {rising} solar hub(s) over the next "
            f"~3h → expect reduced PV output and steeper net-load ramp. "
            f"(Heuristic, not a trained forecast.)"
        )
    else:
        summary = "Heuristic: stable cloud cover at sampled solar hubs — no near-term PV drop expected."
    return {"points": out_points, "summary": summary}
