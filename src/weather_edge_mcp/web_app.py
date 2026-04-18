"""Optional FastAPI surface for Weather Edge."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .core import CACHE_TTL, CITIES, compute_signals

logger = logging.getLogger(__name__)
VERSION = "0.2.0"
WALLET_ADDRESS = os.environ.get("X402_WALLET", "0x1D61dB3cB15472D7aec995Da956A7cDF022a29e7")
PRICE_PER_CALL = os.environ.get("X402_PRICE", "$0.01")
NETWORK = os.environ.get("X402_NETWORK", "eip155:84532")
X402_ENABLED = os.environ.get("X402_ENABLED", "1") == "1"
_metrics = {"total_calls": 0, "paid_calls": 0, "free_calls": 0, "started_at": datetime.now(timezone.utc).isoformat()}


def track_call(*, paid: bool = False) -> None:
    _metrics["total_calls"] += 1
    _metrics["paid_calls" if paid else "free_calls"] += 1


def build_x402_middleware() -> tuple[bool, Any | None]:
    if not X402_ENABLED:
        return False, None
    try:
        from x402 import x402ResourceServer
        from x402.http import HTTPFacilitatorClient
        from x402.http.middleware.fastapi import payment_middleware
        from x402.mechanisms.evm.exact import ExactEvmServerScheme

        routes = {
            "GET /api/signals": {
                "accepts": {"scheme": "exact", "payTo": WALLET_ADDRESS, "price": PRICE_PER_CALL, "network": NETWORK}
            },
            "GET /api/all-signals": {
                "accepts": {"scheme": "exact", "payTo": WALLET_ADDRESS, "price": PRICE_PER_CALL, "network": NETWORK}
            },
        }
        facilitator = HTTPFacilitatorClient()
        server = x402ResourceServer(facilitator)
        server.register(NETWORK, ExactEvmServerScheme())
        logger.info("x402 enabled for Weather Edge web API")
        return True, payment_middleware(routes, server)
    except Exception as exc:
        logger.warning("x402 init failed; falling back to free mode: %s", exc)
        return False, None


def create_app() -> FastAPI:
    app = FastAPI(
        title="Weather Edge API",
        version=VERSION,
        description="Calibrated weather signals for Kalshi prediction markets.",
    )
    x402_active, middleware_fn = build_x402_middleware()

    if middleware_fn:
        @app.middleware("http")
        async def x402_gate(request: Request, call_next):
            return await middleware_fn(request, call_next)

    @app.get("/", response_class=HTMLResponse)
    async def home():
        return HTMLResponse(
            "<h1>Weather Edge</h1>"
            "<p>Calibrated weather prediction signals for Kalshi markets.</p>"
            "<p><a href='/api/health'>Health</a> | <a href='/dashboard'>Dashboard</a> | <a href='/docs'>API Docs</a></p>"
        )

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "version": VERSION,
            "x402_enabled": x402_active,
            "price": PRICE_PER_CALL if x402_active else "free",
            "network": NETWORK if x402_active else None,
            "wallet": WALLET_ADDRESS[:12] + "..." if x402_active else None,
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
        }

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard():
        summary = []
        for city_key, cfg in CITIES.items():
            try:
                data = await compute_signals(city_key)
                strong = len([signal for signal in data.get("signals", []) if signal.get("verdict") == "STRONG"])
                summary.append(f"<li><b>{cfg.label}</b>: {strong} STRONG / {len(data.get('signals', []))} total</li>")
            except Exception:
                summary.append(f"<li><b>{cfg.label}</b>: error</li>")
        return HTMLResponse(
            "<h1>Weather Edge Dashboard</h1>"
            "<p>Signal summary (full details via API):</p>"
            f"<ul>{''.join(summary)}</ul>"
            "<p><a href='/subscribe'>Payment Info</a> | <a href='/docs'>API Docs</a></p>"
        )

    @app.get("/api/signals")
    async def api_signals(city: str = "nyc"):
        track_call(paid=x402_active)
        key = city.lower().strip()
        if key not in CITIES:
            return JSONResponse({"error": f"Unknown city: {city}", "available": list(CITIES.keys())}, status_code=400)
        return JSONResponse(await compute_signals(key))

    @app.get("/api/all-signals")
    async def api_all_signals():
        track_call(paid=x402_active)
        results = {}
        for city_key in CITIES:
            results[city_key] = await compute_signals(city_key)
        return JSONResponse(results)

    return app


app = create_app()
