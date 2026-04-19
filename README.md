# Weather Edge MCP Server

[![weather-edge-mcp MCP server](https://glama.ai/mcp/servers/RJW34/weather-edge-mcp/badges/card.svg)](https://glama.ai/mcp/servers/RJW34/weather-edge-mcp)

Weather Edge is an MCP server for calibrated Kalshi weather-market signals. It turns public forecast and market data into a compact tool surface for AI agents.

## What it does

- calibrates NWS daily high-temperature forecasts by city
- reads current Kalshi weather market prices
- estimates per-bucket probability, edge, and net expected value
- exposes the results through MCP tools and an optional FastAPI surface

## Install

```bash
pip install weather-edge-mcp
```

## MCP usage

### Claude Desktop

```json
{
  "mcpServers": {
    "weather-edge": {
      "command": "python",
      "args": ["-m", "weather_edge_mcp"]
    }
  }
}
```

### Other MCP clients

Use either of these commands:

```bash
weather-edge-mcp
python -m weather_edge_mcp
```

### Transport options

```bash
weather-edge-mcp --transport stdio
weather-edge-mcp --transport sse --port 8050
weather-edge-mcp --transport streamable-http --port 8050
```

## Tools

| Tool | Description |
|------|-------------|
| `get_weather_signals(city)` | Calibrated signals for one city's Kalshi weather markets |
| `get_all_signals()` | Full scan across all supported cities |
| `get_forecast(city)` | Bias-adjusted forecast context for one supported city |
| `get_station_observation(city)` | Latest METAR observation from the settlement station |
| `list_cities()` | Supported cities and calibration parameters |

Supported cities: `nyc`, `chicago`, `denver`, `miami`, `la`

## Optional web API

Weather Edge also ships an optional FastAPI app:

```bash
python -m uvicorn weather_edge_mcp.web_app:app --host 0.0.0.0 --port 8080
```

Routes:

- `/api/health`
- `/api/signals?city=nyc`
- `/api/all-signals`
- `/dashboard`
- `/subscribe`

If the optional `x402` stack is installed and configured, the paid routes can be gated there. MCP stdio mode stays clean and side-effect free.

## Docker

The repo includes a Dockerfile for Glama/container builds.

```bash
docker build -t weather-edge-mcp .
docker run --rm weather-edge-mcp --help
```

## Architecture

```text
src/weather_edge_mcp/
  core.py        # forecasting, market fetches, calibration, formatting
  mcp_server.py  # MCP tools
  web_app.py     # optional FastAPI surface
  cli.py         # command-line entrypoint
```

## Data sources

- National Weather Service forecast API
- Aviation Weather METAR API
- Kalshi public market API

## Development

```bash
python -m unittest discover -s tests -v
python -m build
```

## License

MIT
