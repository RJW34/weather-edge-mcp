# Weather Edge MCP Server

Calibrated weather probability signals for [Kalshi](https://kalshi.com) prediction markets.

The **only MCP server** for weather prediction market intelligence. Uses dual-model forecasting (NWS + GFS ensemble) to find mispriced temperature markets.

## Install

```bash
pip install weather-edge-mcp
```

## Quick Start

### Claude Desktop

Add to your `claude_desktop_config.json`:

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

Then ask Claude: *"What are today's best Kalshi weather edge opportunities?"*

### Cursor / Windsurf

Add to your MCP settings with the same command: `python -m weather_edge_mcp`

### Command Line

```bash
# stdio mode (for AI tools)
weather-edge-mcp

# SSE mode (for web clients)
weather-edge-mcp --transport sse --port 8050
```

## Tools

| Tool | Description |
|------|-------------|
| `get_weather_signals(city)` | Edge signals for a city's Kalshi weather markets — blended probability vs market price, confidence level, expected value |
| `get_all_signals()` | Full scan across all 5 cities, sorted by confidence |
| `get_forecast(city)` | NWS forecast (bias-corrected) + GFS 31-member ensemble distribution |
| `get_station_observation(city)` | Real-time METAR from the exact ASOS station Kalshi settles on |
| `list_cities()` | Available cities with calibration parameters |

**Cities:** `nyc`, `chicago`, `denver`, `miami`, `la`

## How It Works

Kalshi weather markets settle on NWS Climate Reports from specific ASOS stations. Most traders use the raw NWS forecast, but it has systematic biases:

- **Miami**: NWS gridpoint overshoots MIA Airport by ~3°F
- **NYC**: NWS gridpoint overshoots Central Park by ~1°F
- **Denver**: Mountain terrain makes forecasts ~2-4°F less reliable

Weather Edge corrects for these biases and combines two independent models:

### Model 1: Calibrated NWS Gaussian
Per-city bias correction + calibrated sigma (uncertainty). Coastal cities (sigma=3°F) vs mountain (sigma=4°F).

### Model 2: GFS 31-Member Ensemble
31 different forecast runs from Open-Meteo's free API. Gives real probability distributions, not assumptions.

### Blended Model
Adaptive weighted average. When ensemble members agree (low spread), ensemble gets more weight. When they disagree, NWS stabilizes.

**Confidence levels:**
- **HIGH** — both models agree within 10%, net EV > 5 cents
- **MODERATE** — models agree within 20%
- **LOW** — models diverge but one side shows edge

## Example Output

```
> get_weather_signals("chicago")

# Weather Edge — Chicago (Midway)
NWS forecast: 77°F (adjusted: 76°F) — Mostly Cloudy

## HIGH Confidence
- **BUY YES 76° to 77°** | NWS: 26.1% | Ensemble: 25.8% |
  Blended: 25.9% | Market: $0.01 | Edge: +25.4% | EV: $+0.248
- **BUY NO 78° to 79°** | NWS: 3.8% | Ensemble: 0.0% |
  Blended: 1.3% | Market: $0.73 | Edge: +25.2% | EV: $+0.239

## MODERATE Confidence
- **BUY YES 75° or below** | NWS: 84.1% | Ensemble: 100.0% |
  Blended: 94.7% | Market: $0.11 | Edge: +83.2% | EV: $+0.820

12 positive EV signals found
```

## Data Sources (all free, no API keys)

| Source | What | URL |
|--------|------|-----|
| NWS Weather API | Gridpoint forecasts | api.weather.gov |
| Open-Meteo | GFS 31-member ensemble | open-meteo.com |
| Aviation Weather | Real-time METAR observations | aviationweather.gov |
| Kalshi Trade API | Market pricing (public) | api.elections.kalshi.com |

## Why This Exists

I kept losing money on Kalshi weather markets because the raw NWS forecast is systematically wrong for some cities. This MCP server corrects for those biases and gives AI agents the calibrated probabilities they need to identify genuine mispricings.

## License

MIT
