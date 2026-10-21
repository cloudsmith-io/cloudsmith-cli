# AGENTS.md

This file provides guidance to coding agents when working with code in this repository.

## Development setup

See [CONTRIBUTING.md](./CONTRIBUTING.md) for environment setup, tests, linting, and releases. In short: `uv sync --locked --group dev`, then `pre-commit install`.

All dependencies live in `pyproject.toml` (production under `[project.dependencies]`, tooling under the `dev`, `binary`, and `release` dependency groups); exact versions are pinned in `uv.lock`, which is what CI uses. Regenerate the lock with `uv lock` after editing deps.

Python `>=3.11` is required (CI tests 3.11–3.14).

## Common commands

- Run the CLI locally: `cloudsmith ...` (console_script) or `python -m cloudsmith_cli ...`.
- Run the unit tests: `pytest -m "not integration"`. Run with coverage: `pytest --cov=cloudsmith_cli`.
- Run the live-service tests: `pytest -m integration` (requires the `PYTEST_CLOUDSMITH_*` environment variables). Mark each test that calls the live Cloudsmith service with `@pytest.mark.integration`.
- Run a single test: `pytest cloudsmith_cli/cli/tests/test_push.py::TestClass::test_name` or by node id / `-k <expr>`.
- Lint/format (all run via pre-commit): `pre-commit run --all-files`. Individual tools: `ruff format .`, `ruff check .`, `pyupgrade --py310-plus <files>`.
- Release: see [CONTRIBUTING.md](./CONTRIBUTING.md#release-a-new-version). The `VERSION` symlink in repo root points at `cloudsmith_cli/data/VERSION`.

## Architecture

The CLI is a Click app that wraps the auto-generated `cloudsmith-api` Python SDK plus some non-SDK HTTP/SAML/keyring logic.

### Layered layout

- `cloudsmith_cli/cli/` — Click commands, decorators, output formatting, validators, config-file parsing, SAML browser-callback webserver. API **call sites** belong in `core/api/*`; commands invoke those wrappers rather than calling the SDK directly. (A few commands — `login`, `logout`, `check` — do import `cloudsmith_api` for `Configuration` defaults or exception classes; that's fine, but new request code should go through `core/api/*`.)
  - `cli/commands/main.py` defines the top-level `main` Click group (`cls=AliasGroup`). Every other command module imports `main` and registers itself with `@main.command(...)` or `@main.group(...)`. Command modules are imported lazily: `cli/commands/registry.py` maps each command name (and alias) to its module, and `AliasGroup` imports the module on first use. When you add, rename or alias a top-level command, update the registry; `cli/tests/test_lazy_commands.py` fails on drift.
  - `cli/command.py` provides `AliasGroup` (DYM + alias support) and JSON-aware Click exception formatting — Click errors are serialized to JSON when `-F json|pretty_json` is in effect (checked from both Click context and `sys.argv`).
  - `cli/decorators.py` is the seam between CLI and API: `@common_cli_config_options`, `@common_cli_output_options`, `@common_api_auth_options`, and `@initialise_api` (which calls `core.api.init.initialise_api` to configure the `cloudsmith_api` SDK with key/host/proxy/SSL/retry/SAML token). `@initialise_mcp` wires up the MCP server.
  - `cli/config.py` reads `config.ini` and `credentials.ini` via `click-configfile`. Search path: cwd, `click.get_app_dir("cloudsmith")`, `~/.cloudsmith`. Profiles use `[profile:NAME]` sections.
  - `cli/metadata_common.py` holds the shared metadata-payload helpers used by both `metadata` subcommands and the `--metadata-*` flags on every `push <format>` subcommand. Don't duplicate metadata-resolution logic in callers.

- `cloudsmith_cli/core/` — non-CLI logic: API initialization, REST helpers, pagination, rate-limit handling, keyring access-token storage, file download streaming, and the MCP server.
  - `core/api/*.py` — one module per resource (packages, repos, entitlements, metadata, ...). These call the generated `cloudsmith_api` SDK and translate its exceptions into `core.api.exceptions.ApiException` for the CLI layer to render.
  - `core/mcp/` — dynamically builds an MCP (Model Context Protocol) server from the Cloudsmith OpenAPI specs at runtime. `server.py` discovers tools from `swagger/?format=openapi` (v1) and `openapi/?format=json` (v2). `mcp_allowed_tools` / `mcp_allowed_tool_groups` config keys gate exposure. `cli/commands/mcp.py` exposes `mcp start`, `mcp list_tools`, `mcp list_groups`, and `mcp configure` (which writes server configs into Claude Desktop / Cursor / VS Code / Gemini-CLI config files).

- `cloudsmith_cli/data/` — packaged data files including `VERSION`, default `config.ini`, default `credentials.ini`.

### Push + metadata coupling

`cli/commands/push.py` is the most complex command. The per-format subcommands and their options are generated from the API's package-format model, so format-specific client-side behavior is layered on top of that loop rather than branching inside it — see the `deb`-only `--dsc-file` registration at the end of `create_push_handlers()`, which pairs with `cli/dsc_parser.py` to derive `sources_file`/`changes_file` from a Debian `.dsc`. Every `push <format>` subcommand accepts `--metadata-*` flags resolved via `metadata_common`. Push validates metadata both locally and against the API **before** any file upload so malformed SBOM/BuildInfo payloads cannot leave orphan packages behind. Failure behavior is configurable with precedence: `--on-metadata-failure` flag > `$CLOUDSMITH_METADATA_FAILURE_MODE` env > `metadata_failure_mode` config key > `error` default. The kwarg names listed in `METADATA_KWARG_NAMES` and `METADATA_FAILURE_MODE_KWARG` must be popped off the kwargs before they reach the API client, which will reject unknown keys.

### Output formatting convention

Most commands support `-F/--output-format {pretty,json,pretty_json}`. The pattern is: do work (often inside `utils.maybe_spinner(opts)`), then `if utils.maybe_print_as_json(opts, data): return` before falling through to the human-readable rendering. Use `utils.should_use_stderr(opts)` to silence "OK"/progress text when JSON mode is on.

### Authentication

`core/credentials/chain.py` evaluates providers in order and uses the first match:
1. API key: `-k/--api-key` flag, `$CLOUDSMITH_API_KEY`, or `credentials.ini`.
2. SAML via `cloudsmith auth` — opens IdP URL, runs a localhost callback webserver (`cli/webserver.py`, `cli/saml.py`), stores access/refresh tokens in the OS keyring (`core/keyring.py`).
3. OIDC auto-discovery for CI/CD and cloud environments (`core/credentials/oidc/detectors/`), exchanged for a Cloudsmith token.

`logout` clears keyring entries and the credentials file but only warns about `$CLOUDSMITH_API_KEY` (env vars can't be unset from a child process).

## Tests

Tests live alongside code: `cloudsmith_cli/cli/tests/` and `cloudsmith_cli/core/tests/`. The CLI tests use Click's `CliRunner`; API tests stub HTTP with `httpretty` and freeze time with `freezegun`. `bin/` and `.venv/` are excluded from pytest discovery (`norecursedirs` in `pyproject.toml`). Tests that call the live Cloudsmith service carry the `integration` marker.

## Style notes specific to this repo

- `ruff format` and `ruff check` run via pre-commit; Ruff config lives in `pyproject.toml`. Ruff's `TID253` bans module-level imports of heavy modules (`cloudsmith_api`, `requests`, `keyring`, etc.) outside lazily loaded files to keep startup fast — import them inside functions.
- `pyupgrade --py310-plus` runs on every commit, so use modern syntax (`X | Y` unions, `dict[str, ...]` generics, etc.).
- Adding a new top-level command: create a module under `cli/commands/`, attach it to `main` with `@main.command(...)` or `@main.group(cls=AliasGroup, ...)`, and add it (and any aliases) to `cli/commands/registry.py`. Don't import command modules from `cli/commands/__init__.py`.
- Adding a new API call: put SDK wrapping in `core/api/<resource>.py`, translate exceptions to `ApiException`, and call it from the command layer. Avoid making fresh `cloudsmith_api` request calls from `cli/commands/*`; importing `cloudsmith_api` for `Configuration` defaults or exception types is OK and matches what `login`/`logout`/`check` already do.
- Documentation: `README.md` holds badges, a short description, and links; installation, authentication, configuration, and usage live on [docs.cloudsmith.com](https://docs.cloudsmith.com/developer-tools/cli) and in `cloudsmith --help`, and are not duplicated in the README; `CONTRIBUTING.md` covers development. In user-facing text, follow the docs.cloudsmith.com style: lowercase "workspace" (not "organization", "owner", or "namespace"), "SAML" (not "SSO"), and sentence-case headings.
