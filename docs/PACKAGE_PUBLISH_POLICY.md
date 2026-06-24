# Package Publish Policy

Publishing this package to an index is owner-gated.

Before publishing:

1. `py -3 -m compileall -q src tests` passes.
2. `PYTHONPATH=src py -3 -m unittest discover -s tests -v` passes.
3. `py -3 -m build --wheel --no-isolation` passes.
4. The README and examples contain no local paths, secrets, endpoints, or private account names.
5. The release remains read-only and informational.

Do not add automatic package publishing without a separate owner-approved release workflow.

