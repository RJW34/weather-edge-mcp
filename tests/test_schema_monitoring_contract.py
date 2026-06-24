from __future__ import annotations

import unittest


class WeatherSchemaMonitoringContractTests(unittest.TestCase):
    def test_nws_forecast_payload_shape_supports_daytime_high(self) -> None:
        payload = {
            "properties": {
                "periods": [
                    {
                        "isDaytime": True,
                        "temperature": 83,
                        "startTime": "2026-06-24T08:00:00-04:00",
                        "shortForecast": "Mostly Sunny",
                    }
                ]
            }
        }
        period = payload["properties"]["periods"][0]
        self.assertTrue(period["isDaytime"])
        self.assertIn("temperature", period)
        self.assertIn("startTime", period)
        self.assertIn("shortForecast", period)

    def test_kalshi_market_payload_shape_supports_edge_calculation(self) -> None:
        market = {
            "ticker": "KXHIGHNY-26JUN24-B82.5",
            "subtitle": "82 or above",
            "yes_bid_dollars": "0.42",
            "yes_ask_dollars": "0.44",
            "volume": "1000",
        }
        for key in ["ticker", "subtitle", "yes_bid_dollars", "yes_ask_dollars"]:
            self.assertIn(key, market)
        self.assertGreater(float(market["yes_ask_dollars"]), 0)

    def test_metar_payload_shape_supports_station_observation(self) -> None:
        observation = {
            "obsTime": "2026-06-24T15:00:00Z",
            "temp": 25.0,
            "wspd": 9,
            "rawOb": "KNYC 241500Z AUTO 18009KT 10SM CLR 25/16 A3001",
        }
        for key in ["obsTime", "temp", "wspd", "rawOb"]:
            self.assertIn(key, observation)


if __name__ == "__main__":
    unittest.main()

