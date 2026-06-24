# Schema Monitoring

Default mode: `mocked-offline`.

Live network policy: `owner-gated/manual-only`.

CI policy: mocked fixtures only; no live network calls.

## Monitored Contracts

- NWS forecast responses expose daytime periods with temperature, start time, and short forecast.
- Kalshi market rows expose ticker, subtitle, bid/ask price, volume, and market bucket text.
- Aviation Weather METAR rows expose observation time, temperature, wind speed, and raw observation text.

The tests in `tests/test_schema_monitoring_contract.py` exercise representative payloads without contacting live services.

