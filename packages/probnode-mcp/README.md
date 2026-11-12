# probnode-mcp

An [MCP](https://modelcontextprotocol.io) server that gives an AI agent ProbNode's Polymarket
history: find markets, check recording coverage, list files with sizes and sha256, sign download
links, and pull small windows of rows.

```sh
pip install ./packages/probnode ./packages/probnode-mcp   # from a checkout; on PyPI soon
```

```json
{"mcpServers": {"probnode": {"command": "probnode-mcp", "env": {"PROBNODE_API_KEY": "pmd_..."}}}}
```

Tools: `datasets`, `search_markets`, `coverage`, `list_files`, `sign_files`, `timeseries`,
`samples`. Every call goes through the same API, plan and limits as the `probnode` SDK; refusals
come back as `{"error": ..., "status": ...}`. Bulk data travels as signed URLs, not through the
model's context - `timeseries` returns at most 500 rows.
