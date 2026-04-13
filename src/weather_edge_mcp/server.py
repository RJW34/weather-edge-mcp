#!/usr/bin/env python3
"""Weather Edge MCP Server — Kalshi weather prediction market signals.

Exposes calibrated weather probability data via Model Context Protocol.
AI agents can query NWS forecasts, GFS ensemble probabilities, blended
model signals, and real-time settlement station observations.

This is the ONLY MCP server providing dual-model (NWS + ensemble)
calibrated signals for Kalshi weather markets.

Run:
    python mcp_servers/weather_edge_server.py                    # stdio (for Claude Desktop/Cursor)
    python mcp_servers/weather_edge_server.py --transport sse     # SSE (for web clients)
    python mcp_servers/weather_edge_server.py --transport streamable-http  # HTTP

Configure in Claude Desktop (claude_desktop_config.json):
    {
      "mcpServers": {
        "weather-edge": {
          "command": "python",
          "args": ["/path/to/mcp_servers/weather_edge_server.py"]
        }
      }
    }
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add scripts dir for imports
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Server definition
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="weather-edge",
    instructions="""Weather Edge — Kalshi prediction market signals.

Provides calibrated probability data for Kalshi daily high temperature
markets across 5 US cities: NYC, Chicago, Denver, Miami, LA.

Uses two independent forecast models:
1. NWS gridpoint forecast with per-city bias correction
2. GFS 31-member ensemble (real probability distribution)

Plus real-time METAR observations from exact Kalshi settlement stations.

Use get_weather_signals() for edge opportunities on a specific city,
get_all_signals() for a full scan, get_forecast() for raw forecast data,
and get_station_observation() for live settlement station temperatures.""",
)


# ---------------------------------------------------------------------------
# Lazy-loaded scanner modules (avoid slow imports at startup)
# ---------------------------------------------------------------------------

_scanners = {}


def _get_scanners():
    """Lazy-load the scanner modules on first call."""
    if not _scanners:
        from noaa_weather_edge import (
            CITIES,
            fetch_kalshi_weather,
            fetch_nws_forecast,
            find_edges,
            estimate_nws_probability,
        )
        from ensemble_weather_scanner import (
            ENSEMBLE_STATIONS,
            fetch_ensemble_forecasts,
            compute_ensemble_probability,
        )
        from blended_weather_scanner import (
            scan_blended,
            blend_probabilities,
        )

        _scanners["CITIES"] = CITIES
        _scanners["ENSEMBLE_STATIONS"] = ENSEMBLE_STATIONS
        _scanners["fetch_nws"] = fetch_nws_forecast
        _scanners["fetch_kalshi"] = fetch_kalshi_weather
        _scanners["fetch_ensemble"] = fetch_ensemble_forecasts
        _scanners["find_edges"] = find_edges
        _scanners["scan_blended"] = scan_blended
        _scanners["compute_ensemble_prob"] = compute_ensemble_probability
        _scanners["estimate_nws_prob"] = estimate_nws_probability

    return _scanners


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_weather_signals(city: str) -> str:
    """Get edge signals for a specific city's Kalshi weather markets.

    Returns the blended model (NWS + ensemble) probability vs market price
    for each temperature bucket, with confidence classification and net
    expected value per contract.

    Args:
        city: City code — one of: nyc, chicago, denver, miami, la
    """
    s = _get_scanners()
    city = city.lower().strip()

    if city not in s["CITIES"]:
        return f"Unknown city '{city}'. Valid: {', '.join(s['CITIES'].keys())}"

    try:
        forecasts = s["fetch_nws"](city)
        kalshi_data = s["fetch_kalshi"](city)
        ensemble_data = s["fetch_ensemble"](city) if city in s["ENSEMBLE_STATIONS"] else {}
        signals = s["scan_blended"](forecasts, ensemble_data, kalshi_data, city)
    except Exception as e:
        return f"Error scanning {city}: {e}"

    if not signals:
        return f"No open Kalshi markets found for {city}."

    cfg = s["CITIES"][city]
    lines = [
        f"# Weather Edge Signals — {cfg['label']}",
        f"NWS forecast: {forecasts[0].high_f}°F (adjusted: {forecasts[0].high_f + cfg.get('forecast_bias', 0):.0f}°F)",
        "",
    ]

    # Group by confidence
    for conf in ["HIGH", "MODERATE", "LOW"]:
        group = [sig for sig in signals if sig.confidence == conf and sig.net_ev > 0]
        if not group:
            continue
        lines.append(f"## {conf} Confidence")
        for sig in group[:5]:
            label = sig.bucket.subtitle or sig.bucket.ticker
            lines.append(
                f"- **{sig.direction} {label}** | "
                f"NWS: {sig.p_nws:.1%} | Ensemble: {sig.p_ensemble:.1%} | "
                f"Blended: {sig.p_blended:.1%} | Market: ${sig.market_price:.2f} | "
                f"Edge: {sig.edge:+.1%} | Net EV: ${sig.net_ev:+.3f}"
            )
        lines.append("")

    positive = sum(1 for sig in signals if sig.net_ev > 0)
    lines.append(f"**Total: {positive} positive EV signals out of {len(signals)} markets**")

    return "\n".join(lines)


@mcp.tool()
def get_all_signals() -> str:
    """Scan ALL cities for Kalshi weather edge opportunities.

    Returns the top signals across NYC, Chicago, Denver, Miami, and LA,
    sorted by confidence and net expected value.
    """
    s = _get_scanners()
    all_signals = []
    forecast_summary = []

    for city_key in s["CITIES"]:
        try:
            forecasts = s["fetch_nws"](city_key)
            kalshi_data = s["fetch_kalshi"](city_key)
            ensemble_data = s["fetch_ensemble"](city_key) if city_key in s["ENSEMBLE_STATIONS"] else {}
            signals = s["scan_blended"](forecasts, ensemble_data, kalshi_data, city_key)
            all_signals.extend(signals)

            cfg = s["CITIES"][city_key]
            adj = forecasts[0].high_f + cfg.get("forecast_bias", 0)
            forecast_summary.append(
                f"- **{cfg['label']}**: {forecasts[0].high_f}°F (adj: {adj:.0f}°F) — {forecasts[0].short_forecast}"
            )
        except Exception as e:
            forecast_summary.append(f"- **{city_key}**: Error — {e}")

    # Sort by confidence then net_ev
    conf_order = {"HIGH": 0, "MODERATE": 1, "LOW": 2, "CONFLICT": 3, "NEGATIVE": 4}
    all_signals.sort(key=lambda sig: (conf_order.get(sig.confidence, 9), -sig.net_ev))

    lines = ["# Weather Edge — Full Scan (All Cities)", ""]
    lines.append("## Forecasts")
    lines.extend(forecast_summary)
    lines.append("")

    positive = [sig for sig in all_signals if sig.net_ev > 0]
    lines.append(f"## Top Signals ({len(positive)} positive EV)")

    for sig in positive[:15]:
        label = sig.bucket.subtitle or sig.bucket.ticker
        city_label = s["CITIES"][sig.city]["label"].split("(")[0].strip()
        lines.append(
            f"- [{sig.confidence}] **{sig.direction} {city_label} — {label}** | "
            f"Blended: {sig.p_blended:.1%} vs Market: ${sig.market_price:.2f} | "
            f"Edge: {sig.edge:+.1%} | Net EV: ${sig.net_ev:+.3f}"
        )

    return "\n".join(lines)


@mcp.tool()
def get_forecast(city: str) -> str:
    """Get detailed weather forecast for a city — NWS + GFS ensemble.

    Returns the NWS gridpoint forecast (with bias correction) and the
    GFS 31-member ensemble distribution for the next 2-3 days.

    Args:
        city: City code — one of: nyc, chicago, denver, miami, la
    """
    s = _get_scanners()
    city = city.lower().strip()

    if city not in s["CITIES"]:
        return f"Unknown city '{city}'. Valid: {', '.join(s['CITIES'].keys())}"

    cfg = s["CITIES"][city]
    lines = [f"# Forecast — {cfg['label']}", ""]

    # NWS forecast
    try:
        forecasts = s["fetch_nws"](city)
        bias = cfg.get("forecast_bias", 0)
        sigma = cfg.get("sigma", 3.0)
        lines.append(f"## NWS Gridpoint Forecast (bias: {bias:+.1f}°F, σ: {sigma}°F)")
        for fc in forecasts[:4]:
            adj = fc.high_f + bias
            lines.append(f"- **{fc.date}**: {fc.high_f}°F (adjusted: {adj:.0f}°F) — {fc.short_forecast}")
        lines.append("")
    except Exception as e:
        lines.append(f"NWS fetch failed: {e}\n")

    # Ensemble forecast
    if city in s["ENSEMBLE_STATIONS"]:
        try:
            ensemble_data = s["fetch_ensemble"](city)
            lines.append("## GFS 31-Member Ensemble")
            for date_str, highs in sorted(ensemble_data.items())[:4]:
                mean = sum(highs) / len(highs)
                spread = max(highs) - min(highs)
                lines.append(
                    f"- **{date_str}**: mean={mean:.1f}°F "
                    f"[{min(highs):.0f}–{max(highs):.0f}°F] "
                    f"spread={spread:.0f}°F ({len(highs)} members)"
                )

                # Key thresholds
                thresholds = []
                for t in range(40, 100, 2):
                    above = sum(1 for h in highs if h >= t)
                    pct = above / len(highs) * 100
                    if 5 < pct < 95:
                        thresholds.append(f"P(≥{t}°F)={pct:.0f}%")
                if thresholds:
                    lines.append(f"  Probabilities: {', '.join(thresholds[:6])}")

            lines.append("")
        except Exception as e:
            lines.append(f"Ensemble fetch failed: {e}\n")

    return "\n".join(lines)


@mcp.tool()
def get_station_observation(city: str) -> str:
    """Get real-time METAR observation from the Kalshi settlement station.

    Returns the current temperature from the EXACT ASOS station that
    Kalshi uses for settlement, plus trend analysis and whether the
    daily high appears to be locked in.

    Args:
        city: City code — one of: nyc, chicago, denver, miami, la
    """
    try:
        from weather_intraday_monitor import get_station_snapshot, METAR_STATIONS
    except ImportError:
        return "Intraday monitor module not available."

    city = city.lower().strip()
    if city not in METAR_STATIONS:
        return f"Unknown city '{city}'. Valid: {', '.join(METAR_STATIONS.keys())}"

    try:
        snap = get_station_snapshot(city)
    except Exception as e:
        return f"Failed to get station data for {city}: {e}"

    if not snap:
        return f"No data available for {city}."

    lines = [
        f"# Station Observation — {snap.station_name} ({snap.icao})",
        "",
        f"- **Current temp:** {snap.current_temp_f:.1f}°F",
        f"- **Observation time:** {snap.current_time_utc}",
        f"- **Local hour:** ~{snap.local_hour}:00",
        f"- **Temperature trend:** {snap.temp_trend}",
        f"- **Daylight remaining:** {snap.hours_of_daylight_remaining:.1f} hours",
    ]

    if snap.nws_forecast_f:
        lines.append(f"- **NWS forecast high:** {snap.nws_forecast_f}°F (adjusted: {snap.nws_adjusted_f:.0f}°F)")
        diff = snap.current_temp_f - snap.nws_adjusted_f
        lines.append(f"- **Current vs forecast:** {diff:+.0f}°F")

    if snap.high_locked_in:
        lines.append("")
        lines.append("**⚠️ DAILY HIGH APPEARS LOCKED IN** — peak likely passed.")

    lines.append("")
    lines.append(f"*{snap.confidence_note}*")

    return "\n".join(lines)


@mcp.tool()
def list_cities() -> str:
    """List all available cities with their settlement stations and calibration data."""
    s = _get_scanners()
    lines = ["# Available Cities", ""]
    for key, cfg in s["CITIES"].items():
        lines.append(
            f"- **{key}** — {cfg['label']} | "
            f"σ={cfg.get('sigma', 3.0)}°F | "
            f"bias={cfg.get('forecast_bias', 0):+.1f}°F | "
            f"series={cfg['kalshi_series']}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Weather Edge MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport mode (default: stdio for Claude Desktop)",
    )
    parser.add_argument("--port", type=int, default=8050, help="Port for SSE/HTTP transport")
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport == "sse":
        mcp.run(transport="sse", port=args.port)
    elif args.transport == "streamable-http":
        mcp.run(transport="streamable-http", port=args.port)
