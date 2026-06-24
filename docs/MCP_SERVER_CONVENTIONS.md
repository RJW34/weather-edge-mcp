# MCP Server Conventions

This repo is part of a small public MCP portfolio. The conventions are:

- Keep the tool surface read-only and side-effect free.
- Put all execution, credential, and account automation outside public MCP packages.
- Use public data sources that can be queried without secrets.
- Keep CI offline unless a workflow is explicitly documented as manual and owner-gated.
- Include one Claude Desktop example that uses the installed module entrypoint.
- Document expected upstream payload shapes with mocked fixtures.
- Treat package publication as a separate owner-approved release action.

