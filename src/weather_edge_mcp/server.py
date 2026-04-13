"""Weather Edge MCP Server — self-contained.

Provides calibrated weather probability signals for Kalshi prediction
markets via Model Context Protocol. Uses NWS forecasts (bias-corrected)
and GFS 31-member ensemble for real probability distributions.

All data sources are free and require no API keys.
"""

from __future__ import annotations

import math
import re
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# City configuration — NWS gridpoints + calibration
# ---------------------------------------------------------------------------

CITIES = {
    "nyc": {
        "label": "New York City (Central Park)",
        "nws_office": "OKX", "nws_grid_x": 33, "nws_grid_y": 37,
        "kalshi_series": "KXHIGHNY",
        "sigma": 3.0, "forecast_bias": -1.0,
        "metar_icao": "KNYC", "tz_offset": -4,
        "ensemble_lat": 40.7828, "ensemble_lon": -73.9653,
    },
    "chicago": {
        "label": "Chicago (Midway)",
        "nws_office": "LOT", "nws_grid_x": 76, "nws_grid_y": 73,
        "kalshi_series": "KXHIGHCHI",
        "sigma": 3.0, "forecast_bias": -0.5,
        "metar_icao": "KMDW", "tz_offset": -5,
        "ensemble_lat": 41.7868, "ensemble_lon": -87.7522,
    },
    "denver": {
        "label": "Denver",
        "nws_office": "BOU", "nws_grid_x": 62, "nws_grid_y": 60,
        "kalshi_series": "KXHIGHDEN",
        "sigma": 4.0, "forecast_bias": 0.0,
        "metar_icao": "KDEN", "tz_offset": -6,
        "ensemble_lat": 39.8561, "ensemble_lon": -104.6737,
    },
    "miami": {
        "label": "Miami (MIA Airport)",
        "nws_office": "MFL", "nws_grid_x": 75, "nws_grid_y": 54,
        "kalshi_series": "KXHIGHMIA",
        "sigma": 3.5, "forecast_bias": -3.0,
        "metar_icao": "KMIA", "tz_offset": -4,
        "ensemble_lat": 25.7959, "ensemble_lon": -80.2870,
    },
    "la": {
        "label": "Los Angeles (Downtown)",
        "nws_office": "LOX", "nws_grid_x": 154, "nws_grid_y": 44,
        "kalshi_series": "HIGHLA",
        "sigma": 3.5, "forecast_bias": 0.0,
        "metar_icao": "KLAX", "tz_offset": -7,
        "ensemble_lat": 34.0522, "ensemble_lon": -118.2437,
    },
}

NWS_BASE = "https://api.weather.gov"
NWS_UA = "WeatherEdgeMCP/1.0 (weather-edge-mcp; contact: weatheredge@proton.me)"
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
ENSEMBLE_API = "https://ensemble-api.open-meteo.com/v1/ensemble"
METAR_API = "https://aviationweather.gov/api/data/metar"

# Cache
_cache: dict[str, tuple[float, object]] = {}
CACHE_TTL = 300


def _cached(key: str, ttl: int = CACHE_TTL):
    """Simple cache decorator helper."""
    if key in _cache:
        t, val = _cache[key]
        if time.time() - t < ttl:
            return val
    return None


def _set_cache(key: str, val):
    _cache[key] = (time.time(), val)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


def _fetch_nws(city_key: str) -> list[dict]:
    cfg = CITIES[city_key]
    url = f"{NWS_BASE}/gridpoints/{cfg['nws_office']}/{cfg['nws_grid_x']},{cfg['nws_grid_y']}/forecast"
    cached = _cached(f"nws_{city_key}")
    if cached:
        return cached

    with httpx.Client(timeout=15, headers={"User-Agent": NWS_UA}) as c:
        resp = c.get(url)
        resp.raise_for_status()
        data = resp.json()

    forecasts = []
    for period in data.get("properties", {}).get("periods", []):
        if not period.get("isDaytime", True):
            continue
        temp = period.get("temperature")
        unit = period.get("temperatureUnit", "F")
        if temp is None:
            continue
        temp_f = temp if unit == "F" else int(temp * 9 / 5 + 32)
        start = period.get("startTime", "")
        forecasts.append({
            "date": start[:10] if start else "unknown",
            "high_f": temp_f,
            "short_forecast": period.get("shortForecast", ""),
        })

    _set_cache(f"nws_{city_key}", forecasts)
    return forecasts


def _fetch_ensemble(city_key: str) -> dict[str, list[float]]:
    cfg = CITIES[city_key]
    cached = _cached(f"ens_{city_key}")
    if cached:
        return cached

    params = {
        "latitude": cfg["ensemble_lat"], "longitude": cfg["ensemble_lon"],
        "hourly": "temperature_2m", "models": "gfs025",
        "forecast_days": 3, "temperature_unit": "fahrenheit",
    }
    with httpx.Client(timeout=15) as c:
        resp = c.get(ENSEMBLE_API, params=params)
        resp.raise_for_status()
        data = resp.json()

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    members = sorted(k for k in hourly if k.startswith("temperature_2m"))

    dates: dict[str, list[float]] = {}
    for target in sorted(set(t[:10] for t in times)):
        highs = []
        for mk in members:
            vals = hourly[mk]
            day_vals = [vals[i] for i, t in enumerate(times) if t.startswith(target) and vals[i] is not None]
            if day_vals:
                highs.append(max(day_vals))
        if highs:
            dates[target] = highs

    _set_cache(f"ens_{city_key}", dates)
    return dates


def _fetch_kalshi(city_key: str) -> dict[str, list[dict]]:
    cfg = CITIES[city_key]
    cached = _cached(f"kalshi_{city_key}")
    if cached:
        return cached

    with httpx.Client(timeout=15) as c:
        resp = c.get(f"{KALSHI_BASE}/markets", params={"series_ticker": cfg["kalshi_series"], "status": "open", "limit": 100})
        resp.raise_for_status()
        data = resp.json()

    by_date: dict[str, list[dict]] = {}
    for m in data.get("markets", []):
        ticker = m.get("ticker", "")
        subtitle = m.get("subtitle", m.get("yes_sub_title", ""))
        dm = re.search(r"-26([A-Z]{3})(\d{2})-", ticker)
        if dm:
            months = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
                       "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
            month = months.get(dm.group(1), 0)
            date_str = f"2026-{month:02d}-{int(dm.group(2)):02d}" if month else "unknown"
        else:
            date_str = "unknown"

        # Parse bucket
        low_f = high_f = None
        is_over = is_under = False
        bm = re.search(r"(\d+)°?\s*to\s*(\d+)", subtitle)
        if bm:
            low_f, high_f = int(bm.group(1)), int(bm.group(2))
        else:
            bm = re.search(r"(\d+)°?\s*or\s*above", subtitle)
            if bm:
                low_f, is_over = int(bm.group(1)), True
            else:
                bm = re.search(r"(\d+)°?\s*or\s*below", subtitle)
                if bm:
                    high_f, is_under = int(bm.group(1)), True
                else:
                    bm = re.search(r"-T(\d+)$", ticker)
                    if bm:
                        threshold = int(bm.group(1))
                        if "below" in subtitle.lower():
                            high_f, is_under = threshold, True
                        else:
                            low_f, is_over = threshold, True
                    else:
                        bm = re.search(r"-B(\d+)\.5$", ticker)
                        if bm:
                            base = int(bm.group(1))
                            low_f, high_f = base, base + 1

        yes_bid = float(m.get("yes_bid_dollars", 0) or 0)
        yes_ask = float(m.get("yes_ask_dollars", 0) or 0)
        by_date.setdefault(date_str, []).append({
            "ticker": ticker, "subtitle": subtitle,
            "low_f": low_f, "high_f": high_f, "is_over": is_over, "is_under": is_under,
            "yes_bid": yes_bid, "yes_ask": yes_ask,
            "volume": float(m.get("volume_fp", 0) or 0),
        })

    _set_cache(f"kalshi_{city_key}", by_date)
    return by_date


def _fetch_metar(icao: str) -> Optional[dict]:
    cached = _cached(f"metar_{icao}", ttl=120)
    if cached:
        return cached
    with httpx.Client(timeout=10) as c:
        resp = c.get(METAR_API, params={"ids": icao, "format": "json"})
        resp.raise_for_status()
        data = resp.json()
    result = data[0] if data else None
    if result:
        _set_cache(f"metar_{icao}", result)
    return result


# ---------------------------------------------------------------------------
# Probability math
# ---------------------------------------------------------------------------


def _normal_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _nws_probability(nws_high: float, bucket: dict, sigma: float, bias: float) -> float:
    adj = nws_high + bias
    if bucket["is_over"] and bucket["low_f"] is not None:
        z = (bucket["low_f"] - 0.5 - adj) / sigma
        return 1 - _normal_cdf(z)
    if bucket["is_under"] and bucket["high_f"] is not None:
        z = (bucket["high_f"] + 0.5 - adj) / sigma
        return _normal_cdf(z)
    if bucket["low_f"] is not None and bucket["high_f"] is not None:
        z_lo = (bucket["low_f"] - 0.5 - adj) / sigma
        z_hi = (bucket["high_f"] + 0.5 - adj) / sigma
        return _normal_cdf(z_hi) - _normal_cdf(z_lo)
    return 0.0


def _ensemble_probability(highs: list[float], bucket: dict) -> float:
    n = len(highs)
    if n == 0:
        return 0.0
    if bucket["is_over"] and bucket["low_f"] is not None:
        return sum(1 for h in highs if h >= bucket["low_f"]) / n
    if bucket["is_under"] and bucket["high_f"] is not None:
        return sum(1 for h in highs if h <= bucket["high_f"]) / n
    if bucket["low_f"] is not None and bucket["high_f"] is not None:
        return sum(1 for h in highs if bucket["low_f"] <= h <= bucket["high_f"]) / n
    return 0.0


def _blend(p_nws: float, p_ens: float, spread: float) -> float:
    if spread <= 4:
        w_ens = 0.70
    elif spread >= 15:
        w_ens = 0.40
    else:
        t = (spread - 4) / 11
        w_ens = 0.70 - t * 0.30
    return (1 - w_ens) * p_nws + w_ens * p_ens


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="weather-edge",
    instructions=(
        "Weather Edge provides calibrated probability signals for Kalshi daily "
        "high temperature prediction markets across 5 US cities. It combines "
        "NWS gridpoint forecasts (bias-corrected per city) with a GFS 31-member "
        "ensemble for real probability distributions. Use get_weather_signals() "
        "for a specific city or get_all_signals() for a full market scan."
    ),
)


@mcp.tool()
def get_weather_signals(city: str) -> str:
    """Get edge signals for a city's Kalshi weather markets.

    Returns blended model (NWS + ensemble) probability vs market price
    for each temperature bucket, with confidence and expected value.

    Args:
        city: City code — one of: nyc, chicago, denver, miami, la
    """
    city = city.lower().strip()
    if city not in CITIES:
        return f"Unknown city '{city}'. Valid: {', '.join(CITIES.keys())}"

    cfg = CITIES[city]
    try:
        forecasts = _fetch_nws(city)
        kalshi = _fetch_kalshi(city)
        ensemble = _fetch_ensemble(city)
    except Exception as e:
        return f"Error fetching data for {city}: {e}"

    if not forecasts:
        return f"No NWS forecast available for {city}."

    adj = forecasts[0]["high_f"] + cfg["forecast_bias"]
    lines = [
        f"# Weather Edge — {cfg['label']}",
        f"NWS forecast: {forecasts[0]['high_f']}°F (adjusted: {adj:.0f}°F) — {forecasts[0]['short_forecast']}",
        "",
    ]

    for date_str, buckets in sorted(kalshi.items()):
        highs = ensemble.get(date_str, [])
        ens_spread = (max(highs) - min(highs)) if highs else 0
        fc = next((f for f in forecasts if f["date"] == date_str), None)
        if not fc:
            continue

        signals = []
        for b in buckets:
            yes_mid = (b["yes_bid"] + b["yes_ask"]) / 2 if b["yes_ask"] > 0 else b["yes_bid"]
            if yes_mid <= 0:
                continue

            p_nws = _nws_probability(fc["high_f"], b, cfg["sigma"], cfg["forecast_bias"])
            p_ens = _ensemble_probability(highs, b) if highs else p_nws
            p_blend = _blend(p_nws, p_ens, ens_spread)

            # Evaluate YES and NO
            fee = 0.07 * yes_mid * (1 - yes_mid)
            ev_yes = p_blend * (1 - yes_mid) - (1 - p_blend) * yes_mid - fee
            ev_no = (1 - p_blend) * yes_mid - p_blend * (1 - yes_mid) - 0.07 * (1 - yes_mid) * yes_mid

            if ev_yes >= ev_no and ev_yes > 0:
                direction, edge, net_ev = "BUY YES", p_blend - yes_mid, ev_yes
            elif ev_no > 0:
                direction, edge, net_ev = "BUY NO", (1 - p_blend) - (1 - yes_mid), ev_no
            else:
                continue

            # Confidence
            agree = (p_nws > 0.5 and p_ens > 0.5) or (p_nws < 0.5 and p_ens < 0.5)
            diff = abs(p_nws - p_ens)
            if agree and diff < 0.10 and net_ev > 0.05:
                conf = "HIGH"
            elif agree and diff < 0.20 and net_ev > 0.02:
                conf = "MODERATE"
            else:
                conf = "LOW"

            signals.append((conf, direction, b["subtitle"] or b["ticker"], p_nws, p_ens, p_blend, yes_mid, edge, net_ev))

        conf_order = {"HIGH": 0, "MODERATE": 1, "LOW": 2}
        signals.sort(key=lambda s: (conf_order.get(s[0], 9), -s[8]))

        for conf in ["HIGH", "MODERATE", "LOW"]:
            group = [s for s in signals if s[0] == conf]
            if group:
                lines.append(f"## {conf} Confidence")
                for s in group[:5]:
                    lines.append(
                        f"- **{s[1]} {s[2]}** | NWS: {s[3]:.1%} | Ensemble: {s[4]:.1%} | "
                        f"Blended: {s[5]:.1%} | Market: ${s[6]:.2f} | Edge: {s[7]:+.1%} | EV: ${s[8]:+.3f}"
                    )
                lines.append("")

    positive = sum(1 for line in lines if "EV: $+" in line)
    lines.append(f"**{positive} positive EV signals found**")
    return "\n".join(lines)


@mcp.tool()
def get_all_signals() -> str:
    """Scan ALL 5 cities for Kalshi weather edge opportunities.

    Returns top signals sorted by confidence and expected value.
    """
    all_lines = ["# Weather Edge — Full Scan", ""]
    for city_key in CITIES:
        result = get_weather_signals(city_key)
        all_lines.append(result)
        all_lines.append("---")
    return "\n".join(all_lines)


@mcp.tool()
def get_forecast(city: str) -> str:
    """Get NWS + GFS ensemble forecast for a city.

    Returns the bias-corrected NWS forecast and 31-member ensemble
    distribution with probability thresholds.

    Args:
        city: City code — one of: nyc, chicago, denver, miami, la
    """
    city = city.lower().strip()
    if city not in CITIES:
        return f"Unknown city '{city}'. Valid: {', '.join(CITIES.keys())}"

    cfg = CITIES[city]
    lines = [f"# Forecast — {cfg['label']}", ""]

    try:
        forecasts = _fetch_nws(city)
        bias = cfg["forecast_bias"]
        lines.append(f"## NWS Forecast (bias: {bias:+.1f}°F, sigma: {cfg['sigma']}°F)")
        for fc in forecasts[:4]:
            adj = fc["high_f"] + bias
            lines.append(f"- **{fc['date']}**: {fc['high_f']}°F (adj: {adj:.0f}°F) — {fc['short_forecast']}")
        lines.append("")
    except Exception as e:
        lines.append(f"NWS error: {e}\n")

    try:
        ensemble = _fetch_ensemble(city)
        lines.append("## GFS 31-Member Ensemble")
        for date_str, highs in sorted(ensemble.items())[:4]:
            mean = sum(highs) / len(highs)
            spread = max(highs) - min(highs)
            lines.append(f"- **{date_str}**: mean={mean:.1f}°F [{min(highs):.0f}–{max(highs):.0f}°F] spread={spread:.0f}°F")
            thresholds = []
            for t in range(40, 100, 2):
                pct = sum(1 for h in highs if h >= t) / len(highs) * 100
                if 5 < pct < 95:
                    thresholds.append(f"P(>={t}°F)={pct:.0f}%")
            if thresholds:
                lines.append(f"  {', '.join(thresholds[:6])}")
        lines.append("")
    except Exception as e:
        lines.append(f"Ensemble error: {e}\n")

    return "\n".join(lines)


@mcp.tool()
def get_station_observation(city: str) -> str:
    """Get real-time temperature from the Kalshi settlement station.

    Returns current METAR observation from the exact ASOS station
    that Kalshi uses for settlement.

    Args:
        city: City code — one of: nyc, chicago, denver, miami, la
    """
    city = city.lower().strip()
    if city not in CITIES:
        return f"Unknown city '{city}'. Valid: {', '.join(CITIES.keys())}"

    cfg = CITIES[city]
    try:
        obs = _fetch_metar(cfg["metar_icao"])
    except Exception as e:
        return f"METAR error: {e}"

    if not obs:
        return f"No observation available for {cfg['metar_icao']}."

    temp_c = obs.get("temp")
    temp_f = temp_c * 9 / 5 + 32 if temp_c is not None else None
    now_utc = datetime.now(timezone.utc)
    local_hour = (now_utc.hour + cfg["tz_offset"]) % 24

    lines = [
        f"# Station — {obs.get('name', cfg['metar_icao'])} ({cfg['metar_icao']})",
        f"- Current temp: {temp_f:.1f}°F ({temp_c}°C)" if temp_f else "- Temp: unavailable",
        f"- Observation: {obs.get('reportTime', '?')}",
        f"- Local hour: ~{local_hour}:00",
        f"- Conditions: {obs.get('cover', '?')} / {obs.get('rawOb', '')[:60]}",
    ]

    if local_hour >= 16:
        lines.append("\n**Peak likely passed — daily high may be locked in.**")
    elif local_hour < 8:
        lines.append("\n*Too early — high hasn't been reached yet.*")

    return "\n".join(lines)


@mcp.tool()
def list_cities() -> str:
    """List available cities with calibration data."""
    lines = ["# Available Cities", ""]
    for key, cfg in CITIES.items():
        lines.append(
            f"- **{key}** — {cfg['label']} | sigma={cfg['sigma']}°F | "
            f"bias={cfg['forecast_bias']:+.1f}°F | station={cfg['metar_icao']} | "
            f"series={cfg['kalshi_series']}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Run the MCP server."""
    import argparse
    parser = argparse.ArgumentParser(description="Weather Edge MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")
    parser.add_argument("--port", type=int, default=8050)
    args = parser.parse_args()

    mcp.run(transport=args.transport, **({"port": args.port} if args.transport != "stdio" else {}))


if __name__ == "__main__":
    main()
