"""CLI entrypoint for Weather Edge MCP."""
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Weather Edge MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")
    parser.add_argument("--port", type=int, default=8050)
    return parser


def main() -> None:
    from .mcp_server import mcp

    args = build_parser().parse_args()
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport == "sse":
        mcp.run(transport="sse", port=args.port)
    else:
        mcp.run(transport="streamable-http", port=args.port)
