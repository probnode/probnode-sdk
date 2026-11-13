# Contributing

Issues and pull requests are welcome. For anything larger than a small fix, please open an issue
first so we can agree on the approach before you write the code.

## Layout

| Path | Package |
|---|---|
| `packages/probnode` | `probnode-sdk`: the Python client (`import probnode`) and the `probnode` command |
| `packages/probnode-mcp` | `probnode-mcp`: the MCP server, a thin layer over `probnode-sdk` |
| `examples/` | short scripts against the public API |

The command line and the MCP server contain no HTTP of their own: every call goes through
`probnode.Client`, so a change to the API surface is made once, in the SDK.

## Development setup

Python 3.10 or newer.

```sh
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e "packages/probnode[dev]" -e "packages/probnode-mcp[dev]"
```

## Tests and style

```sh
pytest -q packages/probnode/tests packages/probnode-mcp/tests
ruff check packages examples
ruff format packages examples
```

CI runs `ruff check` and the tests on Python 3.10 and 3.12 for every pull request. The tests run
against `httpx.MockTransport` or a stub client and need no network and no API key; please keep it that way, and add a test
with every change in behaviour.

Style: what ruff enforces (line length 100, the rules in each `pyproject.toml`), type hints on
public functions, and docstrings that say what a function returns and when it raises.

## Pull requests

- One change per pull request, with a description of what it changes and why.
- Update `CHANGELOG.md` under `[Unreleased]`.
- No sign-off or CLA is required: by opening a pull request you agree that your contribution is
  licensed under the repository's MIT license.

## Releases

Maintainers release both packages together, with the same version, from a `pypi-vX.Y.Z` tag.
