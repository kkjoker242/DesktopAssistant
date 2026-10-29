"""Optional live POI, route, and weather adapters for the travel planner."""

from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone

import httpx

from weather.weather_serve import AMAP_API_KEY as WEATHER_AMAP_API_KEY


class AMapAdapter:
    def __init__(self, key: str | None = None, client: httpx.Client | None = None) -> None:
        self.key = key or os.getenv("AMAP_API_KEY") or WEATHER_AMAP_API_KEY
        if not self.key:
            raise ValueError("Set AMAP_API_KEY to use live AMap routes")
        self.client = client or httpx.Client(timeout=15)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _get(self, path: str, params: dict) -> dict:
        try:
            response = self.client.get(
                f"https://restapi.amap.com{path}",
                params={"key": self.key, **params},
            )
        except httpx.RequestError:
            raise RuntimeError("AMap network request failed") from None
        if response.status_code >= 400:
            raise RuntimeError(f"AMap HTTP {response.status_code}")
        data = response.json()
        if data.get("status") != "1":
            raise RuntimeError(f"AMap request failed: {data.get('info', 'unknown error')}")
        return data

    def search_poi(self, city: str, name: str) -> dict:
        data = self._get(
            "/v3/place/text",
            {"keywords": name, "city": city, "citylimit": "true", "offset": 10},
        )
        pois = [poi for poi in data.get("pois", []) if isinstance(poi.get("location"), str)]
        if not pois:
            raise LookupError(f"No AMap POI for {city}: {name}")
        chosen = next((poi for poi in pois if poi.get("name") == name), pois[0])
        return {"id": chosen.get("id"), "name": chosen.get("name"), "location": chosen["location"]}

    def driving_minutes(self, origin: str, destination: str) -> int:
        data = self._get(
            "/v5/direction/driving",
            {"origin": origin, "destination": destination, "show_fields": "cost"},
        )
        paths = data.get("route", {}).get("paths", [])
        if not paths:
            raise LookupError("AMap returned no driving route")
        seconds = paths[0].get("cost", {}).get("duration")
        if seconds is None:
            raise ValueError("AMap route has no cost.duration")
        return max(1, math.ceil(float(seconds) / 60))

    def transit_minutes(self, origin: str, destination: str, citycode: str) -> int:
        data = self._get(
            "/v5/direction/transit/integrated",
            {
                "origin": origin, "destination": destination,
                "city1": citycode, "city2": citycode,
                "strategy": 7, "show_fields": "cost",
            },
        )
        transits = data.get("route", {}).get("transits", [])
        durations = [
            float(item["cost"]["duration"])
            for item in transits
            if isinstance(item.get("cost"), dict) and item["cost"].get("duration")
        ]
        if not durations:
            raise LookupError("AMap returned no public-transit route with duration")
        return max(1, math.ceil(min(durations) / 60))

    def route_matrix(
        self, catalog: dict, attraction_ids: set[str], *, mode: str = "transit"
    ) -> tuple[dict, dict]:
        if mode not in {"transit", "driving"}:
            raise ValueError(f"Unsupported route mode: {mode}")
        citycode = catalog.get("citycode")
        if mode == "transit" and not citycode:
            raise ValueError("A citycode is required for AMap public-transit routes")
        places = [*catalog["hubs"], *[
            attraction for attraction in catalog["attractions"]
            if attraction["id"] in attraction_ids
        ]]
        pois = {place["id"]: self.search_poi(catalog["city"], place["name"]) for place in places}
        routes: dict[str, dict[str, int]] = {}
        for start in places:
            routes[start["id"]] = {}
            for end in places:
                if start["id"] == end["id"]:
                    continue
                origin = pois[start["id"]]["location"]
                destination = pois[end["id"]]["location"]
                try:
                    routes[start["id"]][end["id"]] = (
                        self.transit_minutes(origin, destination, citycode)
                        if mode == "transit" else self.driving_minutes(origin, destination)
                    )
                except LookupError:
                    continue
        evidence = {
            "source": f"AMap Web Service {mode} 2.0",
            "queried_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "strategy": "subway_priority" if mode == "transit" else None,
            "poi_matches": pois,
            "note": "Query-time estimate; not a future departure or service guarantee",
        }
        return routes, evidence


async def forecast_from_weather_mcp(city: str, date: str) -> dict:
    """Read an existing MCP tool result, selecting only the requested date."""
    from weather.weather_serve import call_weather_tool

    results = await call_weather_tool(
        "weather-get-forecast", {"district": city}, prefix="weather-"
    )
    report = "\n".join(item.text for item in results if getattr(item, "type", None) == "text")
    report_time = re.search(r"发布时间:\s*([^\n]+)", report)
    for block in report.split("---"):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines or not lines[0].startswith(date):
            continue
        day = next((line for line in lines if line.startswith("白天:")), "")
        condition = day.removeprefix("白天:").strip().split(" ", 1)[0]
        return {
            "condition": condition or "未知",
            "date": date,
            "source": "weather-get-forecast MCP",
            "report_time": report_time.group(1).strip() if report_time else "unknown",
            "is_sample": False,
        }
    return {
        "condition": "未知",
        "date": date,
        "source": "weather-get-forecast MCP",
        "report_time": report_time.group(1).strip() if report_time else "unknown",
        "is_sample": False,
        "note": "No forecast for the requested date",
    }
