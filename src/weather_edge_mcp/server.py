"""Backward-compatible exports for Weather Edge surfaces."""

from .cli import main
from .mcp_server import mcp
from .web_app import app

__all__ = ["app", "main", "mcp"]
