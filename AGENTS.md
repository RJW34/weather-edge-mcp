# Agent Notes

This repository is a public, read-only MCP server for weather-market intelligence.

## Scope

- Keep the MCP server informational only. Do not add account, order, position, signing, payment, or trading execution behavior.
- Default tests must be offline and deterministic.
- Live NWS, Aviation Weather, and Kalshi checks are manual owner-gated diagnostics, not default CI.
- Do not commit `.env`, local Claude configs, credentials, private endpoints, generated reports, build artifacts, or runtime caches.

## Verification

```powershell
py -3 -m compileall -q src tests
$env:PYTHONPATH='src'; py -3 -m unittest discover -s tests -v
py -3 -m build --wheel --no-isolation
```

