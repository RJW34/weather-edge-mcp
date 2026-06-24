# Security Policy

`weather-edge-mcp` is a read-only market-intelligence MCP server. It must not place orders, manage positions, hold credentials, or automate financial execution.

## Supported Boundary

- Public weather and market data only.
- No private account data.
- No trading, order placement, signing, custody, or account automation.
- No committed credentials or local machine paths.

## Reporting

Open a GitHub issue for security concerns that do not expose secrets. For credential exposure, rotate the affected credential first, then report the redacted location and commit.

