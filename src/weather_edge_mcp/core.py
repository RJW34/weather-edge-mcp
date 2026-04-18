"""Core weather signal logic shared by MCP and web transports."""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

NWS_BASE = "https://api.weather.gov"
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
AVIATION_WEATHER_BASE = "https://aviationweather.gov/api/data/metar"
CACHE_TTL = 300


@dataclass(frozen=True)
class CityConfig:
    key: str
    label: str
    station: str
    metar_station: str
    nws_office: str
    nws_grid_x: int
    nws_grid_y: int
    kalshi_series: str
    sigma: float
    forecast_bias: float


CITIES: dict[str, CityConfig] = {
    "nyc": CityConfig("nyc", "New York City", "Central Park", "KNYC", "OKX", 33, 37, "KXHIGHNY", 3.0, -1.0),
    "chicago": CityConfig("chicago", "Chicago", "Midway", "KMDW", "LOT", 76, 73, "KXHIGHCHI", 3.0, -0.5),
    "denver": CityConfig("denver", "Denver", "Denver", "KDEN", "BOU", 62, 60, "KXHIGHDEN", 4.0, 0.0),
    "miami": CityConfig("miami", "Miami", "MIA Airport", "KMIA", "MFL", 75, 54, "KXHIGHMIA", 3.5, -3.0),
    "la": CityConfig("la", "Los Angeles", "Los Angeles Downtown", "KLAX", "LOX", 154, 44, "HIGHLA", 3.5, 0.0),
}

_cache: dict[str, dict[str, Any]] = {}


def list_supported_cities() -> list[str]:
    return list(CITIES.keys())


def get_city(city: str) -> CityConfig:
    key = city.lower().strip()
    if key not in CITIES:
        raise ValueError(f"Unknown city '{city}'. Valid: {', '.join(CITIES.keys())}")
    return CITIES[key]


def get_cached(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < CACHE_TTL:
        return entry["data"]
    return None


def set_cached(key: str, data: Any) -> None:
    _cache[key] = {"data": data, "ts": time.time()}


def ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def compute_probability(
    nws_high: float,
    low_f: int | None,
    high_f: int | None,
    is_over: bool,
    is_under: bool,
    *,
    sigma: float,
    forecast_bias: float,
) -> float:
    adjusted = nws_high + forecast_bias
    if is_over and low_f is not None:
        return 1 - ncdf((low_f - 0.5 - adjusted) / sigma)
    if is_under and high_f is not None:
        return ncdf((high_f + 0.5 - adjusted) / sigma)
    if low_f is not None and high_f is not None:
        return ncdf((high_f + 0.5 - adjusted) / sigma) - ncdf((low_f - 0.5 - adjusted) / sigma)
    return 0.0


async def fetch_nws_forecast(city_key: str) -> dict[str, Any] | None:
    cached = get_cached(f"nws_{city_key}")
    if cached:
        return cached
    cfg = CITIES[city_key]
    url = f"{NWS_BASE}/gridpoints/{cfg.nws_office}/{cfg.nws_grid_x},{cfg.nws_grid_y}/forecast"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(url, headers={"User-Agent": "weather-edge-mcp"})
            if resp.status_code != 200:
                return None
            for period in resp.json().get("properties", {}).get("periods", []):
                if period["isDaytime"]:
                    result = {
                        "high_f": period["temperature"],
                        "date": period["startTime"][:10],
                        "forecast": period["shortForecast"],
                    }
                    set_cached(f"nws_{city_key}", result)
                    return result
        except Exception:
            return None
    return None


async def fetch_kalshi_markets(city_key: str) -> list[dict[str, Any]]:
    cached = get_cached(f"kalshi_{city_key}")
    if cached:
        return cached
    cfg = CITIES[city_key]
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                f"{KALSHI_BASE}/markets",
                params={"series_ticker": cfg.kalshi_series, "status": "open", "limit": 20},
            )
            if resp.status_code == 200:
                markets = resp.json().get("markets", [])
                set_cached(f"kalshi_{city_key}", markets)
                return markets
        except Exception:
            return []
    return []


async def fetch_station_observation(city_key: str) -> dict[str, Any]:
    cached = get_cached(f"station_{city_key}")
    if cached:
        return cached
    cfg = CITIES[city_key]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(AVIATION_WEATHER_BASE, params={"ids": cfg.metar_station, "format": "json"})
        resp.raise_for_status()
        payload = resp.json()
        if not payload:
            raise RuntimeError(f"No METAR observation for {cfg.metar_station}")
        obs = payload[0]
        result = {
            "city": city_key,
            "station": cfg.station,
            "icao": cfg.metar_station,
            "observed_at": obs.get("obsTime") or obs.get("observationTime") or "",
            "temp_c": obs.get("temp") if obs.get("temp") is not None else obs.get("tempC"),
            "wind_speed_kt": obs.get("wspd") or obs.get("windSpeed"),
            "raw": obs.get("rawOb") or obs.get("rawText") or "",
        }
        result["temp_f"] = round((float(result["temp_c"]) * 9 / 5) + 32, 1) if result["temp_c"] is not None else None
        set_cached(f"station_{city_key}", result)
        return result


async def compute_signals(city_key: str) -> dict[str, Any]:
    cached = get_cached(f"signals_{city_key}")
    if cached:
        return cached

    cfg = CITIES[city_key]
    forecast = await fetch_nws_forecast(city_key)
    if not forecast:
        return {"city": city_key, "error": "NWS unavailable", "signals": []}

    markets = await fetch_kalshi_markets(city_key)
    signals: list[dict[str, Any]] = []

    for market in markets:
        subtitle = market.get("subtitle", market.get("yes_sub_title", ""))
        yes_bid = float(market.get("yes_bid_dollars", 0) or 0)
        yes_ask = float(market.get("yes_ask_dollars", 0) or 0)
        volume = float(market.get("volume_fp", market.get("volume", 0)) or 0)

        is_over = "or above" in subtitle.lower() or "greater" in market.get("strike_type", "")
        is_under = "or below" in subtitle.lower()
        low_f = high_f = None
        nums = re.findall(r"(\d+)", subtitle)
        if is_over and nums:
            low_f = int(nums[0])
        elif is_under and nums:
            high_f = int(nums[0])
        elif len(nums) >= 2:
            low_f, high_f = int(nums[0]), int(nums[1])

        nws_prob = compute_probability(
            forecast["high_f"],
            low_f,
            high_f,
            is_over,
            is_under,
            sigma=cfg.sigma,
            forecast_bias=cfg.forecast_bias,
        )
        mid_price = (yes_bid + yes_ask) / 2 if yes_ask > 0 else yes_bid
        if mid_price <= 0:
            continue

        edge = nws_prob - mid_price
        fee = 0.07 * mid_price * (1 - mid_price)
        net_ev = nws_prob * (1 - yes_ask) - (1 - nws_prob) * yes_ask - fee if yes_ask > 0 else 0
        verdict = "STRONG" if net_ev > 0.05 else ("GOOD" if net_ev > 0.02 else ("MARGINAL" if net_ev > 0 else ""))

        signals.append(
            {
                "ticker": market.get("ticker", ""),
                "bucket": subtitle,
                "date": forecast["date"],
                "nws_high": forecast["high_f"],
                "nws_prob": round(nws_prob * 100, 1),
                "market_price": round(mid_price * 100, 1),
                "edge": round(edge * 100, 1),
                "net_ev_cents": round(net_ev * 100, 1),
                "volume": int(volume),
                "yes_bid": yes_bid,
                "yes_ask": yes_ask,
                "verdict": verdict,
            }
        )

    signals.sort(key=lambda signal: signal["net_ev_cents"], reverse=True)
    result = {
        "city": city_key,
        "city_label": cfg.label,
        "station": cfg.station,
        "forecast": forecast,
        "signals": signals,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    set_cached(f"signals_{city_key}", result)
    return result


def format_weather_signals(data: dict[str, Any]) -> str:
    if data.get("error"):
        return f"Error: {data['error']}"
    lines = [f"# Weather Edge — {data['city_label']}", f"Station: {data['station']}", ""]
    forecast = data["forecast"]
    lines.append(f"Forecast: {forecast['high_f']}°F — {forecast['forecast']}")
    lines.append("")
    for signal in data.get("signals", [])[:10]:
        if not signal.get("verdict"):
            continue
        lines.append(
            f"- [{signal['verdict']}] {signal['bucket']} | NWS {signal['nws_prob']}% vs market {signal['market_price']}% | edge {signal['edge']:+.1f} pts | EV {signal['net_ev_cents']:+.1f}c"
        )
    if len(lines) <= 4:
        lines.append("No positive-EV signals found.")
    return "\n".join(lines)


def format_all_signals(items: list[tuple[str, dict[str, Any]]]) -> str:
    summaries: list[tuple[float, str, dict[str, Any]]] = []
    for city_label, data in items:
        for signal in data.get("signals", [])[:5]:
            if signal.get("verdict"):
                summaries.append((signal["net_ev_cents"], city_label, signal))
    summaries.sort(key=lambda row: row[0], reverse=True)
    lines = ["# Weather Edge — Full Scan", ""]
    for _, city_label, signal in summaries[:15]:
        lines.append(
            f"- {city_label}: [{signal['verdict']}] {signal['bucket']} | market {signal['market_price']}% | edge {signal['edge']:+.1f} pts | EV {signal['net_ev_cents']:+.1f}c"
        )
    if len(lines) == 2:
        lines.append("No positive-EV signals found across supported cities.")
    return "\n".join(lines)


def format_forecast(city_key: str, forecast: dict[str, Any]) -> str:
    cfg = CITIES[city_key]
    adjusted = forecast["high_f"] + cfg.forecast_bias
    return (
        f"# Forecast — {cfg.label}\n\n"
        f"Raw NWS high: {forecast['high_f']}°F\n"
        f"Bias-adjusted high: {adjusted:.1f}°F\n"
        f"Sigma: {cfg.sigma}°F\n"
        f"Forecast: {forecast['forecast']}\n"
        f"Date: {forecast['date']}"
    )


def format_station_observation(city_key: str, obs: dict[str, Any]) -> str:
    return (
        f"# Station Observation — {CITIES[city_key].label}\n\n"
        f"Station: {obs['station']} ({obs['icao']})\n"
        f"Observed at: {obs['observed_at']}\n"
        f"Temperature: {obs['temp_f']}°F\n"
        f"Wind: {obs['wind_speed_kt']} kt\n"
        f"Raw METAR: {obs['raw']}"
    )


def format_city_list() -> str:
    lines = ["# Supported Cities", ""]
    for cfg in CITIES.values():
        lines.append(
            f"- {cfg.key}: {cfg.label} | station={cfg.station} | metar={cfg.metar_station} | sigma={cfg.sigma} | bias={cfg.forecast_bias:+.1f}"
        )
    return "\n".join(lines)
