"""Kalshi Weather Edge API v3 — x402 Paid Edition.

AI agents discover via MCP directories, pay per call via x402 micropayments.
Free: /api/health, /subscribe, / (landing), /dashboard
Paid: /api/signals, /api/all-signals — $0.01/call USDC on Base

Run: uvicorn x402_app:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import argparse
import asyncio
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from mcp.server.fastmcp import FastMCP

import httpx

# ---------------------------------------------------------------------------
# x402 Payment Configuration
# ---------------------------------------------------------------------------

WALLET_ADDRESS = os.environ.get("X402_WALLET", "0x1D61dB3cB15472D7aec995Da956A7cDF022a29e7")
PRICE_PER_CALL = os.environ.get("X402_PRICE", "$0.01")
NETWORK = os.environ.get("X402_NETWORK", "eip155:84532")  # Base mainnet
X402_ENABLED = os.environ.get("X402_ENABLED", "1") == "1"

x402_middleware_fn = None

if X402_ENABLED:
    try:
        from x402 import x402ResourceServer
        from x402.http import HTTPFacilitatorClient
        from x402.http.middleware.fastapi import payment_middleware
        from x402.mechanisms.evm.exact import ExactEvmServerScheme

        x402_routes = {
            "GET /api/signals": {
                "accepts": {
                    "scheme": "exact",
                    "payTo": WALLET_ADDRESS,
                    "price": PRICE_PER_CALL,
                    "network": NETWORK,
                }
            },
            "GET /api/all-signals": {
                "accepts": {
                    "scheme": "exact",
                    "payTo": WALLET_ADDRESS,
                    "price": PRICE_PER_CALL,
                    "network": NETWORK,
                }
            },
        }

        facilitator = HTTPFacilitatorClient()
        server = x402ResourceServer(facilitator)
        server.register(NETWORK, ExactEvmServerScheme())

        x402_middleware_fn = payment_middleware(x402_routes, server)
        print(f"[x402] ACTIVE — {PRICE_PER_CALL}/call to {WALLET_ADDRESS[:12]}... on {NETWORK}")
    except Exception as e:
        print(f"[x402] Init failed: {e} — FREE mode")
        X402_ENABLED = False

if not X402_ENABLED:
    print("[x402] DISABLED — all endpoints free")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Kalshi Weather Edge",
    version="0.3.0",
    description="Calibrated weather signals for Kalshi prediction markets. x402 micropayments.",
)

if x402_middleware_fn:
    @app.middleware("http")
    async def x402_gate(request: Request, call_next):
        return await x402_middleware_fn(request, call_next)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: dict = {}
CACHE_TTL = 300

def get_cached(key: str):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < CACHE_TTL:
        return entry["data"]
    return None

def set_cached(key: str, data):
    _cache[key] = {"data": data, "ts": time.time()}

# ---------------------------------------------------------------------------
# City Config (calibrated per audit)
# ---------------------------------------------------------------------------

CITIES = {
    "nyc": {"label": "New York City", "station": "Central Park", "metar_station": "KNYC",
            "nws_office": "OKX", "nws_grid_x": 33, "nws_grid_y": 37,
            "kalshi_series": "KXHIGHNY", "sigma": 3.0, "forecast_bias": -1.0},
    "chicago": {"label": "Chicago", "station": "Midway", "metar_station": "KMDW",
                "nws_office": "LOT", "nws_grid_x": 76, "nws_grid_y": 73,
                "kalshi_series": "KXHIGHCHI", "sigma": 3.0, "forecast_bias": -0.5},
    "denver": {"label": "Denver", "station": "Denver", "metar_station": "KDEN",
               "nws_office": "BOU", "nws_grid_x": 62, "nws_grid_y": 60,
               "kalshi_series": "KXHIGHDEN", "sigma": 4.0, "forecast_bias": 0.0},
    "miami": {"label": "Miami", "station": "MIA Airport", "metar_station": "KMIA",
              "nws_office": "MFL", "nws_grid_x": 75, "nws_grid_y": 54,
              "kalshi_series": "KXHIGHMIA", "sigma": 3.5, "forecast_bias": -3.0},
    "la": {"label": "Los Angeles", "station": "Los Angeles Downtown", "metar_station": "KLAX",
            "nws_office": "LOX", "nws_grid_x": 154, "nws_grid_y": 44,
            "kalshi_series": "HIGHLA", "sigma": 3.5, "forecast_bias": 0.0},
}

NWS_BASE = "https://api.weather.gov"
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
AVIATION_WEATHER_BASE = "https://aviationweather.gov/api/data/metar"

mcp = FastMCP(
    name="weather-edge",
    instructions=(
        "Weather Edge MCP Server for calibrated Kalshi weather-market intelligence. "
        "Use list_cities for supported markets, get_weather_signals for one city, "
        "get_all_signals for a full scan, get_forecast for raw forecast context, and "
        "get_station_observation for live settlement-station readings."
    ),
)

# ---------------------------------------------------------------------------
# Data Fetching
# ---------------------------------------------------------------------------

async def fetch_nws_forecast(city_key: str) -> dict | None:
    cached = get_cached(f"nws_{city_key}")
    if cached:
        return cached
    cfg = CITIES[city_key]
    url = f"{NWS_BASE}/gridpoints/{cfg['nws_office']}/{cfg['nws_grid_x']},{cfg['nws_grid_y']}/forecast"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(url, headers={"User-Agent": "weather-edge-mcp"})
            if resp.status_code != 200:
                return None
            for p in resp.json().get("properties", {}).get("periods", []):
                if p["isDaytime"]:
                    result = {"high_f": p["temperature"], "date": p["startTime"][:10], "forecast": p["shortForecast"]}
                    set_cached(f"nws_{city_key}", result)
                    return result
        except Exception:
            return None
    return None

async def fetch_kalshi_markets(city_key: str) -> list[dict]:
    cached = get_cached(f"kalshi_{city_key}")
    if cached:
        return cached
    cfg = CITIES[city_key]
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(f"{KALSHI_BASE}/markets", params={
                "series_ticker": cfg["kalshi_series"], "status": "open", "limit": 20})
            if resp.status_code == 200:
                markets = resp.json().get("markets", [])
                set_cached(f"kalshi_{city_key}", markets)
                return markets
        except Exception:
            pass
    return []

# ---------------------------------------------------------------------------
# Probability Model
# ---------------------------------------------------------------------------

def ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def compute_probability(nws_high, low_f, high_f, is_over, is_under, sigma=3.0, forecast_bias=0.0):
    adjusted = nws_high + forecast_bias
    if is_over and low_f is not None:
        return 1 - ncdf((low_f - 0.5 - adjusted) / sigma)
    if is_under and high_f is not None:
        return ncdf((high_f + 0.5 - adjusted) / sigma)
    if low_f is not None and high_f is not None:
        return ncdf((high_f + 0.5 - adjusted) / sigma) - ncdf((low_f - 0.5 - adjusted) / sigma)
    return 0.0

# ---------------------------------------------------------------------------
# Signal Computation
# ---------------------------------------------------------------------------

async def compute_signals(city_key: str) -> dict:
    cached = get_cached(f"signals_{city_key}")
    if cached:
        return cached

    cfg = CITIES[city_key]
    forecast = await fetch_nws_forecast(city_key)
    if not forecast:
        return {"city": city_key, "error": "NWS unavailable", "signals": []}

    markets = await fetch_kalshi_markets(city_key)
    signals = []

    for m in markets:
        subtitle = m.get("subtitle", m.get("yes_sub_title", ""))
        yes_bid = float(m.get("yes_bid_dollars", 0) or 0)
        yes_ask = float(m.get("yes_ask_dollars", 0) or 0)
        volume = float(m.get("volume_fp", m.get("volume", 0)) or 0)

        is_over = "or above" in subtitle.lower() or "greater" in m.get("strike_type", "")
        is_under = "or below" in subtitle.lower()
        low_f = high_f = None
        nums = re.findall(r"(\d+)", subtitle)
        if is_over and nums:
            low_f = int(nums[0])
        elif is_under and nums:
            high_f = int(nums[0])
        elif len(nums) >= 2:
            low_f, high_f = int(nums[0]), int(nums[1])

        nws_prob = compute_probability(forecast["high_f"], low_f, high_f, is_over, is_under,
                                       sigma=cfg["sigma"], forecast_bias=cfg["forecast_bias"])
        mid_price = (yes_bid + yes_ask) / 2 if yes_ask > 0 else yes_bid
        if mid_price <= 0:
            continue

        edge = nws_prob - mid_price
        fee = 0.07 * mid_price * (1 - mid_price)
        net_ev = nws_prob * (1 - yes_ask) - (1 - nws_prob) * yes_ask - fee if yes_ask > 0 else 0
        verdict = "STRONG" if net_ev > 0.05 else ("GOOD" if net_ev > 0.02 else ("marginal" if net_ev > 0 else ""))

        signals.append({
            "ticker": m.get("ticker", ""),
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
        })

    signals.sort(key=lambda s: s["net_ev_cents"], reverse=True)
    result = {
        "city": city_key, "city_label": cfg["label"], "station": cfg["station"],
        "forecast": forecast, "signals": signals,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    set_cached(f"signals_{city_key}", result)
    return result


async def fetch_station_observation(city_key: str) -> dict:
    cached = get_cached(f"station_{city_key}")
    if cached:
        return cached
    cfg = CITIES[city_key]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(AVIATION_WEATHER_BASE, params={"ids": cfg["metar_station"], "format": "json"})
        resp.raise_for_status()
        payload = resp.json()
        if not payload:
            raise RuntimeError(f"No METAR observation for {cfg['metar_station']}")
        obs = payload[0]
        result = {
            "city": city_key,
            "station": cfg["station"],
            "icao": cfg["metar_station"],
            "observed_at": obs.get("obsTime") or obs.get("observationTime") or "",
            "temp_c": obs.get("temp") if obs.get("temp") is not None else obs.get("tempC"),
            "wind_speed_kt": obs.get("wspd") or obs.get("windSpeed"),
            "raw": obs.get("rawOb") or obs.get("rawText") or "",
        }
        if result["temp_c"] is not None:
            result["temp_f"] = round((float(result["temp_c"]) * 9 / 5) + 32, 1)
        else:
            result["temp_f"] = None
        set_cached(f"station_{city_key}", result)
        return result


def _run(coro):
    return asyncio.run(coro)


@mcp.tool()
def get_weather_signals(city: str) -> str:
    """Get calibrated edge signals for one city's Kalshi weather markets.

    Args:
        city: One of nyc, chicago, denver, miami, la.
    """
    city = city.lower().strip()
    if city not in CITIES:
        return f"Unknown city '{city}'. Valid: {', '.join(CITIES.keys())}"
    data = _run(compute_signals(city))
    if data.get("error"):
        return f"Error: {data['error']}"
    lines = [f"# Weather Edge — {data['city_label']}", f"Station: {data['station']}", ""]
    fc = data["forecast"]
    lines.append(f"Forecast: {fc['high_f']}°F — {fc['forecast']}")
    lines.append("")
    for sig in data.get("signals", [])[:10]:
        if not sig.get("verdict"):
            continue
        lines.append(
            f"- [{sig['verdict']}] {sig['bucket']} | NWS {sig['nws_prob']}% vs market {sig['market_price']}% | edge {sig['edge']:+.1f} pts | EV {sig['net_ev_cents']:+.1f}c"
        )
    if len(lines) <= 4:
        lines.append("No positive-EV signals found.")
    return "\n".join(lines)


@mcp.tool()
def get_all_signals() -> str:
    """Run a full scan across all supported cities and rank top weather-market signals."""
    summaries = []
    for city in CITIES:
        data = _run(compute_signals(city))
        for sig in data.get("signals", [])[:5]:
            if sig.get("verdict"):
                summaries.append((sig["net_ev_cents"], data["city_label"], sig))
    summaries.sort(key=lambda row: row[0], reverse=True)
    lines = ["# Weather Edge — Full Scan", ""]
    for _, city_label, sig in summaries[:15]:
        lines.append(f"- {city_label}: [{sig['verdict']}] {sig['bucket']} | market {sig['market_price']}% | edge {sig['edge']:+.1f} pts | EV {sig['net_ev_cents']:+.1f}c")
    if len(lines) == 2:
        lines.append("No positive-EV signals found across supported cities.")
    return "\n".join(lines)


@mcp.tool()
def get_forecast(city: str) -> str:
    """Get raw calibrated forecast context for one supported city.

    Args:
        city: One of nyc, chicago, denver, miami, la.
    """
    city = city.lower().strip()
    if city not in CITIES:
        return f"Unknown city '{city}'. Valid: {', '.join(CITIES.keys())}"
    fc = _run(fetch_nws_forecast(city))
    if not fc:
        return "Forecast unavailable"
    cfg = CITIES[city]
    adjusted = fc['high_f'] + cfg['forecast_bias']
    return f"# Forecast — {cfg['label']}\n\nRaw NWS high: {fc['high_f']}°F\nBias-adjusted high: {adjusted:.1f}°F\nSigma: {cfg['sigma']}°F\nForecast: {fc['forecast']}\nDate: {fc['date']}"


@mcp.tool()
def get_station_observation(city: str) -> str:
    """Get the latest METAR observation from the settlement station for one city.

    Args:
        city: One of nyc, chicago, denver, miami, la.
    """
    city = city.lower().strip()
    if city not in CITIES:
        return f"Unknown city '{city}'. Valid: {', '.join(CITIES.keys())}"
    obs = _run(fetch_station_observation(city))
    return (
        f"# Station Observation — {CITIES[city]['label']}\n\n"
        f"Station: {obs['station']} ({obs['icao']})\n"
        f"Observed at: {obs['observed_at']}\n"
        f"Temperature: {obs['temp_f']}°F\n"
        f"Wind: {obs['wind_speed_kt']} kt\n"
        f"Raw METAR: {obs['raw']}"
    )


@mcp.tool()
def list_cities() -> str:
    """List supported cities, settlement stations, and calibration parameters."""
    lines = ["# Supported Cities", ""]
    for key, cfg in CITIES.items():
        lines.append(f"- {key}: {cfg['label']} | station={cfg['station']} | metar={cfg['metar_station']} | sigma={cfg['sigma']} | bias={cfg['forecast_bias']:+.1f}")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

_metrics = {"total_calls": 0, "paid_calls": 0, "free_calls": 0, "started_at": datetime.now(timezone.utc).isoformat()}

def track_call(paid=False):
    _metrics["total_calls"] += 1
    _metrics["paid_calls" if paid else "free_calls"] += 1

# ---------------------------------------------------------------------------
# FREE Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(
        "<h1>Kalshi Weather Edge</h1>"
        "<p>Calibrated weather prediction signals for Kalshi markets.</p>"
        "<p>Powered by x402 micropayments — AI agents pay $0.01/call in USDC.</p>"
        "<p><a href='/api/health'>Health</a> | <a href='/subscribe'>Subscribe</a> | <a href='/dashboard'>Dashboard</a> | <a href='/docs'>API Docs</a></p>"
    )

@app.get("/api/health")
async def health():
    return {
        "status": "ok", "version": "0.3.0",
        "x402_enabled": X402_ENABLED,
        "price": PRICE_PER_CALL if X402_ENABLED else "free",
        "network": NETWORK if X402_ENABLED else None,
        "wallet": WALLET_ADDRESS[:12] + "..." if X402_ENABLED else None,
        "cities": list(CITIES.keys()),
        "cache_ttl": CACHE_TTL,
        "metrics": _metrics,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/subscribe")
async def subscribe():
    return {
        "protocol": "x402",
        "price": PRICE_PER_CALL,
        "network": NETWORK,
        "wallet": WALLET_ADDRESS,
        "endpoints": {
            "/api/signals?city=nyc": "Signals for one city ($0.01)",
            "/api/all-signals": "All cities ($0.01)",
        },
        "free": ["/", "/api/health", "/subscribe", "/dashboard", "/docs"],
        "how_to_pay": "AI agents with x402-compatible clients handle payment automatically via the x-payment header.",
    }

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    summary = []
    for ck in CITIES:
        try:
            data = await compute_signals(ck)
            strong = len([s for s in data.get("signals", []) if s.get("verdict") == "STRONG"])
            summary.append(f"<li><b>{CITIES[ck]['label']}</b>: {strong} STRONG / {len(data.get('signals', []))} total</li>")
        except Exception:
            summary.append(f"<li><b>{CITIES[ck]['label']}</b>: error</li>")
    return HTMLResponse(
        "<h1>Weather Edge Dashboard</h1>"
        "<p>Signal summary (full details via paid API):</p>"
        f"<ul>{''.join(summary)}</ul>"
        "<p><a href='/subscribe'>x402 Payment Info</a> | <a href='/docs'>API Docs</a></p>"
    )

# ---------------------------------------------------------------------------
# PAID Routes (x402 gated)
# ---------------------------------------------------------------------------

@app.get("/api/signals")
async def api_signals(city: str = "nyc"):
    track_call(paid=X402_ENABLED)
    if city not in CITIES:
        return JSONResponse({"error": f"Unknown city: {city}", "available": list(CITIES.keys())}, status_code=400)
    return JSONResponse(await compute_signals(city))

@app.get("/api/all-signals")
async def api_all_signals():
    track_call(paid=X402_ENABLED)
    results = {}
    for ck in CITIES:
        results[ck] = await compute_signals(ck)
    return JSONResponse(results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Weather Edge MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")
    parser.add_argument("--port", type=int, default=8050)
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport == "sse":
        mcp.run(transport="sse", port=args.port)
    else:
        mcp.run(transport="streamable-http", port=args.port)


if __name__ == "__main__":
    main()
