from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicationContractTests(unittest.TestCase):
    def test_project_metadata_declares_public_read_only_shape(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["name"], "weather-edge-mcp")
        self.assertEqual(project["license"], "MIT")
        self.assertIn("weather-edge-mcp", project["scripts"])

    def test_required_public_docs_exist(self) -> None:
        for rel in [
            "README.md",
            "SECURITY.md",
            "AGENTS.md",
            "docs/MCP_SERVER_CONVENTIONS.md",
            "docs/PACKAGE_PUBLISH_POLICY.md",
            "docs/SCHEMA_MONITORING.md",
            "docs/PORTFOLIO_MANIFEST.json",
            "examples/claude-desktop.json",
        ]:
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_portfolio_manifest_is_offline_and_non_executing(self) -> None:
        manifest = json.loads((ROOT / "docs/PORTFOLIO_MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["sideEffects"], "none")
        self.assertEqual(manifest["credentialRequirement"], "none")
        self.assertEqual(manifest["schemaMonitoring"]["defaultMode"], "mocked-offline")
        self.assertEqual(manifest["schemaMonitoring"]["liveNetworkPolicy"], "owner-gated/manual-only")
        self.assertRegex(manifest["executionBoundary"], r"no .*trading")

    def test_release_facing_text_has_no_obvious_secret_or_local_path(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                ROOT / "README.md",
                ROOT / "SECURITY.md",
                ROOT / "AGENTS.md",
                ROOT / "docs/MCP_SERVER_CONVENTIONS.md",
                ROOT / "docs/PACKAGE_PUBLISH_POLICY.md",
                ROOT / "docs/SCHEMA_MONITORING.md",
            ]
        )
        denied = [
            r"sk-[A-Za-z0-9_-]{20,}",
            r"ghp_[A-Za-z0-9_]{20,}",
            r"C:\\Users\\",
            r"/home/ryan/",
            r"\.env\s*=",
        ]
        for pattern in denied:
            self.assertIsNone(re.search(pattern, combined), pattern)


if __name__ == "__main__":
    unittest.main()

