# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development setup

The repo uses `direnv` (`.envrc`) to bootstrap a `.venv` via `uv`, install the project editable, install dev deps from `requirements.in`, and `pre-commit install`. If you don't use direnv, the equivalent is:

```
python -m venv .venv && source .venv/bin/activate
pip install -e .
pip install -r requirements.txt   # dev deps (locked); requirements.in is the source list
pre-commit install
```

Python `>=3.10` is required (CI tests 3.10–3.14).

## Common commands

- Run the CLI locally: `cloudsmith ...` (console_script) or `python -m cloudsmith_cli ...`.
- Run tests: `pytest` (configured via `setup.cfg` — adds `--cov=cloudsmith_cli`).
- Run a single test: `pytest cloudsmith_cli/cli/tests/test_push.py::TestClass::test_name` or by node id / `-k <expr>`.
- Lint/format (all run via pre-commit): `pre-commit run --all-files`. Individual tools: `black .`, `isort .`, `flake8 --config=.flake8`, `pylint --rcfile=.pylintrc <path>`, `pyupgrade --py310-plus <files>`.
- Release: `bumpversion <major|minor|revision>` then `git push origin <tag>`. The `VERSION` symlink in repo root points at `cloudsmith_cli/data/VERSION`.

## Architecture

The CLI is a Click app that wraps the auto-generated `cloudsmith-api` Python SDK plus some non-SDK HTTP/SAML/keyring logic.

### Layered layout

- `cloudsmith_cli/cli/` — Click commands, decorators, output formatting, validators, config-file parsing, SAML browser-callback webserver. **No direct API calls live here** — commands call into `core/api/*`.
  - `cli/commands/main.py` defines the top-level `main` Click group (`cls=AliasGroup`). Every other command module imports `main` and registers itself with `@main.command(...)` or `@main.group(...)`. `cli/commands/__init__.py` imports every module so registration happens on import.
  - `cli/command.py` provides `AliasGroup` (DYM + alias support) and JSON-aware Click exception formatting — Click errors are serialized to JSON when `-F json|pretty_json` is in effect (checked from both Click context and `sys.argv`).
  - `cli/decorators.py` is the seam between CLI and API: `@common_cli_config_options`, `@common_cli_output_options`, `@common_api_auth_options`, and `@initialise_api` (which calls `core.api.init.initialise_api` to configure the `cloudsmith_api` SDK with key/host/proxy/SSL/retry/SAML token). `@initialise_mcp` wires up the MCP server.
  - `cli/config.py` reads `config.ini` and `credentials.ini` via `click-configfile`. Search path: cwd, `click.get_app_dir("cloudsmith")`, `~/.cloudsmith`. Profiles use `[profile:NAME]` sections.
  - `cli/metadata_common.py` holds the shared metadata-payload helpers used by both `metadata` subcommands and the `--metadata-*` flags on every `push <format>` subcommand. Don't duplicate metadata-resolution logic in callers.

- `cloudsmith_cli/core/` — non-CLI logic: API initialization, REST helpers, pagination, rate-limit handling, keyring access-token storage, file download streaming, and the MCP server.
  - `core/api/*.py` — one module per resource (packages, repos, entitlements, metadata, ...). These call the generated `cloudsmith_api` SDK and translate its exceptions into `core.api.exceptions.ApiException` for the CLI layer to render.
  - `core/mcp/` — dynamically builds an MCP (Model Context Protocol) server from the Cloudsmith OpenAPI specs at runtime. `server.py` discovers tools from `swagger/?format=openapi` (v1) and `openapi/?format=json` (v2). `mcp_allowed_tools` / `mcp_allowed_tool_groups` config keys gate exposure. `cli/commands/mcp.py` exposes `mcp start`, `mcp list_tools`, `mcp list_groups`, and `mcp configure` (which writes server configs into Claude Desktop / Cursor / VS Code / Gemini-CLI config files).

- `cloudsmith_cli/data/` — packaged data files including `VERSION`, default `config.ini`, default `credentials.ini`.

### Push + metadata coupling

`cli/commands/push.py` is the most complex command. Every `push <format>` subcommand accepts `--metadata-*` flags resolved via `metadata_common`. Push validates metadata both locally and against the API **before** any file upload so malformed SBOM/BuildInfo payloads cannot leave orphan packages behind. Failure behavior is configurable with precedence: `--on-metadata-failure` flag > `$CLOUDSMITH_METADATA_FAILURE_MODE` env > `metadata_failure_mode` config key > `error` default. The kwarg names listed in `METADATA_KWARG_NAMES` and `METADATA_FAILURE_MODE_KWARG` must be popped off the kwargs before they reach the API client, which will reject unknown keys.

### Output formatting convention

Most commands support `-F/--output-format {pretty,json,pretty_json}`. The pattern is: do work (often inside `utils.maybe_spinner(opts)`), then `if utils.maybe_print_as_json(opts, data): return` before falling through to the human-readable rendering. Use `utils.should_use_stderr(opts)` to silence "OK"/progress text when JSON mode is on.

### Authentication

Three auth paths feed `core.api.init.initialise_api`:
1. `-k/--api-key` flag, `$CLOUDSMITH_API_KEY`, or `credentials.ini`.
2. SAML SSO via `cloudsmith auth` — opens IdP URL, runs a localhost callback webserver (`cli/webserver.py`, `cli/saml.py`), stores access/refresh tokens in the OS keyring (`core/keyring.py`).
3. `logout` clears keyring entries and the credentials file but only warns about `$CLOUDSMITH_API_KEY` (env vars can't be unset from a child process).

## Tests

Tests live alongside code: `cloudsmith_cli/cli/tests/` and `cloudsmith_cli/core/tests/`. The CLI tests use Click's `CliRunner`; API tests stub HTTP with `httpretty` and freeze time with `freezegun`. `bin/` and `.venv/` are excluded from pytest discovery (`norecursedirs` in `setup.cfg`).

## Style notes specific to this repo

- `flake8` ignores `E203,E501,D107,D102,W503` and uses `max-line-length=100` (but `black` enforces 88). `isort` profile lists known third-party packages explicitly — when adding a new third-party import, add it to `.isort.cfg`'s `known_third_party` if isort puts it in the wrong group.
- `pyupgrade --py310-plus` runs on every commit, so use modern syntax (`X | Y` unions, `dict[str, ...]` generics, etc.).
- Adding a new subcommand: create a module under `cli/commands/`, register it in `cli/commands/__init__.py`, and attach it to `main` (or a subgroup) with the `AliasGroup` for alias support.
- Adding a new API call: put SDK wrapping in `core/api/<resource>.py`, translate exceptions to `ApiException`, and call it from the command layer — don't import `cloudsmith_api` directly from `cli/commands/*`.
