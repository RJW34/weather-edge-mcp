"""MCP transport surface for Weather Edge."""
from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP

from .core import (
    CITIES,
    compute_signals,
    fetch_nws_forecast,
    fetch_station_observation,
    format_all_signals,
    format_city_list,
    format_forecast,
    format_station_observation,
    format_weather_signals,
    get_city,
)

mcp = FastMCP(
    name="weather-edge",
    instructions=(
        "Weather Edge MCP Server for calibrated Kalshi weather-market intelligence. "
        "Use list_cities for supported markets, get_weather_signals for one city, "
        "get_all_signals for a full scan, get_forecast for raw forecast context, and "
        "get_station_observation for live settlement-station readings."
    ),
)


def _run(coro):
    return asyncio.run(coro)


@mcp.tool()
def get_weather_signals(city: str) -> str:
    """Get calibrated edge signals for one city's Kalshi weather markets.

    Args:
        city: One of nyc, chicago, denver, miami, la.
    """
    cfg = get_city(city)
    return format_weather_signals(_run(compute_signals(cfg.key)))


@mcp.tool()
def get_all_signals() -> str:
    """Run a full scan across all supported cities and rank top weather-market signals."""
    items = []
    for key, cfg in CITIES.items():
        items.append((cfg.label, _run(compute_signals(key))))
    return format_all_signals(items)


@mcp.tool()
def get_forecast(city: str) -> str:
    """Get raw calibrated forecast context for one supported city.

    Args:
        city: One of nyc, chicago, denver, miami, la.
    """
    cfg = get_city(city)
    forecast = _run(fetch_nws_forecast(cfg.key))
    if not forecast:
        return "Forecast unavailable"
    return format_forecast(cfg.key, forecast)


@mcp.tool()
def get_station_observation(city: str) -> str:
    """Get the latest METAR observation from the settlement station for one city.

    Args:
        city: One of nyc, chicago, denver, miami, la.
    """
    cfg = get_city(city)
    return format_station_observation(cfg.key, _run(fetch_station_observation(cfg.key)))


@mcp.tool()
def list_cities() -> str:
    """List supported cities, settlement stations, and calibration parameters."""
    return format_city_list()
