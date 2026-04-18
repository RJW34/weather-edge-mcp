import importlib
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class PackageTests(unittest.TestCase):
    def test_import_has_no_stdout_side_effects(self):
        sys.modules.pop("weather_edge_mcp", None)
        buf = io.StringIO()
        with redirect_stdout(buf):
            mod = importlib.import_module("weather_edge_mcp")
        self.assertEqual(buf.getvalue(), "")
        self.assertTrue(hasattr(mod, "__version__"))

    def test_cli_parser_defaults(self):
        from weather_edge_mcp.cli import build_parser

        args = build_parser().parse_args([])
        self.assertEqual(args.transport, "stdio")
        self.assertEqual(args.port, 8050)

    def test_city_listing_contains_expected_keys(self):
        from weather_edge_mcp.core import format_city_list

        listing = format_city_list()
        self.assertIn("nyc", listing)
        self.assertIn("miami", listing)


if __name__ == "__main__":
    unittest.main()
