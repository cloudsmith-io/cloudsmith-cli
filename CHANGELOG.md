# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Credential helper lookups against custom domains are now faster. The domain cache file is read once per process instead of on every request, and read-only lookups no longer create the cache directory.

## [1.25.0] - 2026-08-24

### Added

- Added a Cargo credential provider for Cloudsmith registries. `cloudsmith credential-helper install cargo` installs a `cargo-credential-cloudsmith` launcher binary and registers it in `$CARGO_HOME/config.toml`, so Cargo authenticates to Cloudsmith registries automatically using your existing CLI credentials — no `cargo login` and no token in `credentials.toml`. `cloudsmith credential-helper cargo` speaks Cargo's [credential provider protocol](https://doc.rust-lang.org/cargo/reference/credential-provider-protocol.html): a newline-delimited JSON exchange that answers `get` with the resolved token, and answers a registry that is not a Cloudsmith one with `url-not-supported` so Cargo falls through to the next configured provider — registering globally cannot break authentication to crates.io. The provider is appended to `registry.global-credential-providers` (keeping `cargo:token` as the fallback) and pinned on any `[registries.*]` entry whose index points at a known Cloudsmith Cargo host. Custom Cloudsmith registry domains are discovered via the API and cached locally; add extra hostnames with `--domain` (repeatable), disable discovery with `--no-discover`, or preview changes with `--dry-run`. Manage installed helpers with `cloudsmith credential-helper uninstall cargo` and `cloudsmith credential-helper list`.
- Added Nix package and upstream support. Use `cloudsmith push nix` to upload Nix packages and `cloudsmith upstream nix` to manage Nix channel upstreams.
- Added a pnpm credential helper. `cloudsmith credential-helper install pnpm` registers `pnpm-credential-cloudsmith` in the user-level `.npmrc`, using existing CLI credentials for Cloudsmith registries. It supports custom-domain discovery, additional `--domain` values, `--no-discover`, `--dry-run`, listing, and uninstalling.
- Added `CLOUDSMITH_KEYRING_FILE_PATH` and `CLOUDSMITH_KEYRING_DIR` to relocate tokens stored by the bundled file-based keyring backends. An explicit file path takes precedence over the directory, and `KEYRING_PROPERTY_FILE_PATH` takes precedence over its Cloudsmith alias.

### Changed

- API hosts supplied by `--api-host`, `CLOUDSMITH_API_HOST`, or `api_host` are now normalised by trimming whitespace and trailing slashes and adding `https://` when no scheme is present. If a previously configured host ended in a slash, run `cloudsmith auth` again because its keyring key has changed.
- Non-MCP commands now start faster by loading the MCP dependency only when an `mcp` command runs.

### Fixed

- Failed package synchronisation in JSON output mode now returns a machine-readable error containing the API's reason, status, and stage.
- `cloudsmith entitlements list` now shows pagination details in human-readable output and correctly distinguishes the visible page from results retrieved with `--page-all`.
- SAML authentication now directs users from the browser to the terminal for 2FA, retries rejected codes until cancelled, and includes API error details when authentication fails.

## [1.24.0] - 2026-08-18

### Added

- `CLOUDSMITH_KEYRING_BACKEND` is now accepted as an alias for `PYTHON_KEYRING_BACKEND`. If both are set, `PYTHON_KEYRING_BACKEND` takes precedence.
- `CLOUDSMITH_KEYRING_KEY` is now accepted as an alias for `KEYRING_PROPERTY_KEYRING_KEY`, letting the bundled `keyrings.cryptfile`/`keyrings.alt` encrypted backends be unlocked non-interactively (e.g. in headless containers) without an interactive `getpass()` prompt. If both are set, `KEYRING_PROPERTY_KEYRING_KEY` takes precedence. Note: both bundled backends override `KeyringBackend.__init__` without calling `super().__init__()`, so `keyring`'s own automatic `KEYRING_PROPERTY_*` handling never runs for them — we apply it ourselves after resolving the backend.
- `cloudsmith auth --no-browser` skips the automatic browser launch and prints the SAML IDP URL to open manually, for shells where launching a browser is unwanted or unreliable.

### Fixed

- `cloudsmith auth` no longer fails when it can't launch a browser. `webbrowser.open()` raises `webbrowser.Error` where no runnable browser is found (Cygwin, headless shells) and returns `False` on other launch failures; neither outcome was handled, so the command either crashed or silently waited on a callback the user had no way to trigger. Either outcome now prints the IDP URL with instructions to open it manually, and authentication continues against the same local callback.
- `python -m cloudsmith_cli` now exits non-zero when a command fails. `AliasGroup.main` runs click with `standalone_mode=False` so click returns the exit code from `ctx.exit()` rather than raising `SystemExit`, and the module entrypoint discarded that return value — so a failed push, or an unauthorised request, exited 0. The `cloudsmith` console script and the standalone binaries already wrapped `main()` in `sys.exit()` and were unaffected.
- The hint shown for a 401 when a credential is set no longer claims the cause is a missing permission. A 401 does not tell the CLI whether the credential is invalid, expired, or simply has no access to the resource, so the hint now names those possibilities and asks the user to check their credentials, instead of contradicting the `401 - Unauthorized` status it accompanies.
- The AWS OIDC detector now resolves the AWS region for its STS client with the AWS CLI precedence: explicit session region, `AWS_REGION`, `AWS_DEFAULT_REGION`, the shared config file, then EC2 instance metadata. botocore's own session resolution does not read `AWS_REGION` and never consults instance metadata, so on hosts that configure the region only through those sources the client targeted the legacy global STS endpoint instead of the regional one.
- `--debug` now prints the CLI's debug log records to stderr; previously the flag was recorded but no log handler was installed, so the records went nowhere. The flag is also honoured when set on the group (`cloudsmith -d <command>`) or through the config file, where the subcommand's own flag default used to overwrite it.

### Changed

- The minimum supported `click` version is now 8.2.

## [1.23.0] - 2026-08-14

### Added

- The packaged binary now bundles `keyrings.cryptfile` and `keyrings.alt`, encrypted/file-based `keyring` backends, so a host with no OS keyring (e.g. a headless Linux container) can still persist SSO/OIDC tokens via `PYTHON_KEYRING_BACKEND`.

## [1.22.0] - 2026-08-11

### Added

- `cloudsmith push deb` now derives a Debian source package's members from its `.dsc`, so `cloudsmith push deb <owner>/<repo>/<distro>/<release> foo_1.0-1.dsc` is enough where `--sources-file` and `--changes-file` previously had to be worked out by hand (and their suffixes vary: `.orig.tar.gz`, `.orig.tar.bz2`, `.debian.tar.xz`, `.diff.gz`, ...). The `Checksums-Sha256:` or `Files:` field of the `.dsc` is read — plain or OpenPGP-clearsigned — and the upstream/native source archive becomes `--sources-file` while the Debian packaging archive becomes `--changes-file`, for the `1.0`, `2.0`, `3.0 (native)` and `3.0 (quilt)` source formats. `--dsc-file` names a `.dsc` other than `PACKAGE_FILE`, and an explicit `--sources-file` or `--changes-file` still wins for its own field. A detached upstream signature (`*.orig.tar.*.asc`) is skipped with a warning, since the deb package format has no field to carry it; a multi-component source package (`*.orig-<component>.tar.*`) is rejected outright, because leaving a component behind would upload incomplete source.
- `cloudsmith domains list` lists the hosts Cloudsmith can authenticate as a versioned JSON document: `{"version": 1, "domains": [{"host": ..., "format": ..., "type": ..., "domain_type": ..., "org": ..., "repository": ..., "primary": ..., "created_at": ...}]}`. The built-in list can be replaced by a `[domains]` section in a trusted `config.ini` — each entry maps a hostname to the format it serves, or to `download`/`upload` — for dedicated deployments. An organisation's own custom domains are listed ahead of the built-in hosts, and a custom domain that is disabled or not yet validated is left out entirely, since it serves nothing. `--format` and `--repo` narrow the list to the hosts usable for a package format or repository, most-preferred first, and `--domain-type` to those with one purpose: `download`, `upload`, `api` or `native_api`.
- The Cloudsmith organisation is now named by `--org`, with `--organization` and `--oidc-org` accepted as aliases for the same option, and `org`, `organization` or `oidc_org` accepted in `config.ini`. `--oidc-org` named the setting after the first feature that wanted it; it is read by custom-domain discovery as well as OIDC token exchange, so it is now named after what it is. The `CLOUDSMITH_ORG` environment variable is unchanged, and `credential-helper install` no longer has a separate `--org` of its own.

### Fixed

- Logging in via SSO no longer leaves a previously loaded API key attached to later requests. `initialise_api()` reset request headers on every call but never cleared the underlying API key, which `Configuration.set_default()` makes sticky across calls — so a session that had read an API key from `credentials.ini` could carry both an `Authorization: Bearer` header and a stale `X-Api-Key` after SSO login, with the API able to authenticate as the pre-login identity while the CLI reported a successful login.
- `cloudsmith credential-helper install docker --dry-run` no longer makes a live API call or overwrites the on-disk custom-domain cache. Custom-domain discovery ran before the dry-run short-circuit, so a dry run had the same side effects as a real install; discovery is now skipped under `--dry-run` and reported as such in the planned actions.

## [1.21.0] - 2026-08-03

### Added

- `cloudsmith credential-helper generic` resolves a credential through the full provider chain (API key, `credentials.ini`, system keyring, OIDC) and emits it as a versioned JSON document — `{"version": 1, "username": "token", "password": "<token>"}` — for tools that shell out to the CLI rather than importing it. It takes no arguments: a Cloudsmith token is organisation-wide, so the host it will be used against does not change which credential resolves. Errors exit non-zero with a message on stderr and never emit a partial document.

## [1.20.2] - 2026-07-31

### Fixed

- Files larger than 100MB now upload correctly when authenticated via SSO or OIDC. The multi-part upload read its credentials from `opts.api_key`, which is only populated by `--api-key`, `CLOUDSMITH_API_KEY` or `credentials.ini` — so with an SSO session or OIDC auto-discovery it was empty, the auth header was dropped, and the part upload failed with a misleading `404 - Not Found` ("this usually means the user/org is wrong or not visible") even though every preceding API call had succeeded. Credentials are now taken from the resolved credential chain, with SSO access tokens sent as a bearer `Authorization` header and API keys/OIDC tokens as `X-Api-Key`.
- `cloudsmith download` now authenticates with OIDC credentials. It resolved its own auth from `opts.api_key` plus a direct keyring read, which between them cover neither OIDC auto-discovery nor any future credential source, so downloads from a private repository in an OIDC-authenticated pipeline were attempted anonymously. It now uses the same resolved credential as every other command.
- The hint shown on a `401 - Unauthorized` now reflects how the session actually authenticated. It branched on `opts.api_key`, so an OIDC-authenticated session was told "You don't have an API key or access token set" despite being authenticated, and an SSO session whose token had expired could be told to check its permissions instead of to re-run `cloudsmith auth`.

## [1.20.1] - 2026-07-30

### Fixed

- Standalone binaries again propagate CLI exit codes. In 1.20.0 the frozen entry point discarded the command's return value, so API failures exited 0 — for example `cloudsmith whoami` with an invalid API key reported success — breaking scripted authentication checks. Installs from PyPI (pip) were unaffected.

## [1.20.0] - 2026-07-30

### Added

- Standalone, self-contained CLI binaries built with PyInstaller for Linux (x86_64/aarch64, glibc and musl), macOS (arm64/x86_64) and Windows (x86_64). Each release attaches the per-platform archives and SHA256 checksums to the GitHub release and pushes them to Cloudsmith. The binaries bundle Python and all native dependencies, so no Python installation is required.
- Linux binary archives are GPG-signed. Each `cloudsmith-<version>-linux-*.tar.gz` ships a detached `.sig` alongside it, verifiable with `gpg --verify` against the published Cloudsmith CLI signing key.
- Released binaries are tagged on Cloudsmith by platform — `os`, `arch`, `libc` (Linux), the full target, and a type tag (`standalone-binary`/`signature`) — so CI/CD can select the right artifact via the package query API, for example `version:1.20.0 AND tag:standalone-binary AND tag:linux AND tag:x86_64 AND tag:musl`.
- Each release publishes a per-target install manifest (`cloudsmith-cli-manifest-<target>`) to Cloudsmith alongside the binaries, recording the archive name, download URL and SHA256 checksum, so install scripts can resolve and verify the correct binary via `.../raw/names/cloudsmith-cli-manifest-<target>/versions/{<version>|latest}/manifest.txt`.

### Changed

- **`cloudsmith whoami` now exits with code 1 when not authenticated** (and 0 when authenticated), across all output formats, so scripts and CI pipelines can check authentication status without parsing the output. The command's output itself is unchanged.
- The Homebrew tap (`cloudsmith-io/cloudsmith-cli`) now installs the standalone binary instead of the Python zipapp, so `python@3.10` is no longer a dependency — existing installs transition transparently via `brew upgrade cloudsmith-cli` (the orphaned `python@3.10` can be removed with `brew autoremove`), and `brew install cloudsmith-io/cloudsmith-cli/cloudsmith` now works as a shorter alias.
- The official Docker image now ships the standalone musl binary on a plain Alpine base instead of the Python zipapp — the image no longer contains a Python runtime.
- The Docker image now carries standard OCI labels (`org.opencontainers.image.*`: source, version, revision, licenses); the Docker Hub image additionally publishes the conventional floating tags (`latest`, major, and major.minor).
- Packaging migrated to `pyproject.toml` + `uv` (`setup.py`/`setup.cfg` retired); builds now use `uv build` with a committed `uv.lock`. This does not change how the CLI is installed from PyPI.

### Removed

- The multi-platform PEX zipapp (`cloudsmith.pyz`) is no longer built or published; the standalone per-platform binaries replace it. Anything that consumed `cloudsmith.pyz` from GitHub releases or the Cloudsmith raw repository (for example `cloudsmith-cli-action` with `executable: true`) must switch to the new binary archives.

### Security

- Stricter acceptance of API hosts and proxies. When `api_host` or `api_proxy` comes from a directory-relative `config.ini` (one found in the current working directory), the host must now match an allow-listed suffix — `api_host` allows `*.cloudsmith.io`/`*.cloudsmith.com` by default, `api_proxy` has no default and is rejected — preventing a checked-in config from redirecting credentials to an attacker-controlled endpoint. Values from CLI flags, environment variables, user-level config or an explicit `--config-file` are unaffected; additional trusted suffixes can be supplied via the `CLOUDSMITH_ALLOWED_API_HOST_SUFFIXES`/`CLOUDSMITH_ALLOWED_API_PROXY_SUFFIXES` environment variables.

## [1.19.0] - 2026-06-11

### Added

- Added a Docker credential helper for Cloudsmith registries. `cloudsmith credential-helper install docker` installs a `docker-credential-cloudsmith` launcher binary and registers it in `~/.docker/config.json`, so Docker authenticates to Cloudsmith registries automatically using your existing CLI credentials — no manual `docker login` required. Custom Cloudsmith registry domains are discovered via the API and cached locally; add extra hostnames with `--domain` (repeatable), disable discovery with `--no-discover`, or preview changes with `--dry-run`. Manage installed helpers with `cloudsmith credential-helper uninstall docker` and `cloudsmith credential-helper list`.
- Added Bitbucket Pipelines to OIDC credential auto-discovery. When a pipeline step sets `oidc: true`, the CLI reads the OIDC token from the `BITBUCKET_STEP_OIDC_TOKEN` environment variable and exchanges it for a Cloudsmith access token. Works out of the box with no extra dependencies.
- Added CircleCI to OIDC credential auto-discovery. When running in CircleCI, the CLI reads the OIDC token from the `CIRCLE_OIDC_TOKEN_V2` (preferred) or `CIRCLE_OIDC_TOKEN` environment variable and exchanges it for a Cloudsmith access token. Works out of the box with no extra dependencies.
- Added Azure DevOps to OIDC credential auto-discovery. When running in an Azure DevOps pipeline, the CLI fetches an OIDC token from the `SYSTEM_OIDCREQUESTURI` endpoint using the pipeline's `SYSTEM_ACCESSTOKEN` and exchanges it for a Cloudsmith access token. Works out of the box with no extra dependencies.
- Added GitHub Actions to OIDC credential auto-discovery. When running in GitHub Actions (with `id-token: write` permission), the CLI fetches an OIDC token from the Actions runtime endpoint and exchanges it for a Cloudsmith access token. Works out of the box with no extra dependencies.
- Added a generic fallback to OIDC credential auto-discovery. When no dedicated environment is detected, the CLI reads an OIDC token from the `CLOUDSMITH_OIDC_TOKEN` environment variable (useful for Jenkins or any custom CI/CD) and exchanges it for a Cloudsmith access token. Works out of the box with no extra dependencies.
- Added GitLab CI to OIDC credential auto-discovery. When running in GitLab CI/CD, the CLI reads the OIDC token from the `CLOUDSMITH_OIDC_TOKEN` environment variable (configured via `id_tokens` in `.gitlab-ci.yml`) and exchanges it for a Cloudsmith access token. Works out of the box with no extra dependencies.
- Added controls for OIDC detector selection. Set `CLOUDSMITH_OIDC_<DETECTOR>_DISABLED=true` to skip a specific detector (only the literal `true` disables), or use `--oidc-detector-order` (env var `CLOUDSMITH_OIDC_DETECTOR_ORDER`) with a comma-separated list of detector ids to override which detectors are considered and the order they are tried in. When both are set, disable flags take precedence over the order list. Both controls can also be set in `config.ini` via the `oidc_detector_order` and `oidc_disabled_detectors` keys (the latter additive with the `*_DISABLED` env vars). Unknown ids in the order, or controls that leave no detector enabled, are surfaced as a warning. Detector ids: `aws`, `azure_devops`, `bitbucket`, `circleci`, `generic`, `github`, `gitlab`.

### Fixed

- The official Docker image now runs as a dedicated non-root `cloudsmith` user (uid 1000) instead of root.
- The PyJWT dependency now declares the `crypto` extra (`PyJWT[crypto]`), fixing zipapp (`.pyz`) builds that previously shipped without cryptography wheels and failed at startup on macOS.

### Security

- Upgraded vulnerable dependencies — `mcp` 1.9.1 → 1.27.2 plus transitive upgrades (`urllib3`, `requests`, `starlette`, `python-multipart`, `python-dotenv`, `idna`, `pygments`, `pytest`) — resolving all open Dependabot alerts.


## [1.18.0] - 2026-06-09

### Added

- OIDC credential auto-discovery for CI/CD. When `CLOUDSMITH_ORG` and `CLOUDSMITH_SERVICE_SLUG` are set, the CLI auto-detects a supported cloud environment, obtains a vendor OIDC token, and exchanges it for a short-lived Cloudsmith API token — no static API key required. Initial support is for AWS (install the extra with `pip install cloudsmith-cli[aws]`). Tunable via `--oidc-org`, `--oidc-service-slug`, `--oidc-audience`, and `--oidc-discovery-disabled` (and matching `CLOUDSMITH_OIDC_*` env vars). The detector skips itself silently when its dependencies are not installed.
- `cloudsmith mcp configure` now supports Claude Code as a client (`--client claude-code`), registering the Cloudsmith MCP server in `~/.claude.json`.

### Changed

- Authentication now resolves credentials through an explicit, predictable provider chain: CLI flag → environment variable → credentials file → keyring → OIDC. This separates the previously combined credential sources and makes precedence deterministic.

### Fixed

- `metadata list` filters (`--source-kind`, `--classification`) now send the enum name the v2 API expects instead of an integer, fixing an HTTP 400 on every filtered list. Valid source kinds: `unknown, system, upstream, custom, third_party`; classifications: `unknown, intrinsic, security, provenance, sbom, generic`.

## [1.17.0] - 2026-05-18

### Added

- Added `metadata` command group for managing arbitrary JSON metadata (SBOM, BuildInfo, custom) attached to a package.
  - `metadata add`: Attach a new metadata entry to a package. Accepts inline `--content` or `--file` (with `-` for stdin), a required `--content-type`, and an optional `--source-identity`.
  - `metadata list`: List metadata entries for a package, or fetch a single entry by slug. Supports filtering by `--source-kind` and `--classification`, with pagination flags.
  - `metadata update`: Replace content or source identity on an existing entry. Content type is immutable after creation.
  - `metadata remove`: Remove a metadata entry from a package. Supports `-y` to skip the confirmation prompt.
  - Supports `--output-format json | pretty_json` for programmatic usage.
- Added push-time metadata flags to every `cloudsmith push <format>` subcommand. Metadata is validated locally and against the API before any file upload, then attached to the package immediately after creation.
  - `--metadata-content-file PATH`: Path to a JSON file containing the metadata content. Use `-` for stdin.
  - `--metadata-content JSON`: Inline JSON content. Mutually exclusive with `--metadata-content-file`.
  - `--metadata-content-type MIME`: MIME type of the metadata payload. Required when content is provided.
  - `--metadata-source-identity TEXT`: Identifier indicating where the metadata originated. Defaults to `cloudsmith-cli@<version>`.
  - `--on-metadata-failure [error|warn]`: Per-push override for how validation/attach failures are handled. `error` (default) aborts the push; `warn` downgrades to a warning and uploads the package anyway. Overrides `$CLOUDSMITH_METADATA_FAILURE_MODE` and the `metadata_failure_mode` config key for the current push.
  - Failures abort the push by default with the HTTP status as the exit code. Downgrade failures to a warning (and emit a copy-paste `cloudsmith metadata add` retry hint) via any of: the `--on-metadata-failure warn` CLI flag, `CLOUDSMITH_METADATA_FAILURE_MODE=warn` (or `0`) env var, or the new `metadata_failure_mode` key in `config.ini`. Precedence: CLI flag → env var → config key → `error` default.
  - Push JSON output now includes a `metadata_attachment` field on success and error envelopes.

## [1.16.0] - 2026-03-24

### Added

- Added Alpine Upstream support for managing upstream configurations.

## [1.15.0] - 2026-03-19

### Added

- Added `--tag` option to `download` command for filtering packages by tags
- Added download command documentation to README with comprehensive usage examples
- Added `--filename` option to `download` command for filtering by package filename, with support for glob patterns (e.g., `--filename '*.snupkg'`)
- Added `--download-all` flag to `download` command to download all matching packages instead of erroring on multiple matches
- Multiple packages table now includes a Filename column for easier disambiguation

## [1.14.0] - 2026-03-11

### Added

- Added `vulnerabilities` command to retrieve security scan results for a package
  - Summary View (Default): Displays a high-level count of vulnerabilities broken down by severity (Critical, High, Medium, Low, Unknown).
  - Assessment View `--show-assessment` (`-A`): Provides a detailed breakdown where vulnerabilities are:
    - Grouped by the specific affected upstream package / dependency.
    - Sorted by severity (Critical first).
    - Richly formatted tables.
  - Filtering Capabilities:
    - By Severity: `--severity` Show only specific levels (e.g., just Critical and High).
    - By Status: `--fixable | --non-fixable` Filter to show only "Fixable" vulnerabilities (where a patch exists) or "Non-Fixable" ones.
  - Supports `--output-format json | pretty_json` for programmatic usage

## [1.14.0] - 2026-03-13

### Added

- Added `vulnerabilities` command to retrieve security scan results for a package
  - Summary View (Default): Displays a high-level count of vulnerabilities broken down by severity (Critical, High, Medium, Low, Unknown).
  - Assessment View `--show-assessment` (`-A`): Provides a detailed breakdown where vulnerabilities are:
    - Grouped by the specific affected upstream package / dependency.
    - Sorted by severity (Critical first).
    - Richly formatted tables.
  - Filtering Capabilities:
    - By Severity: `--severity` Show only specific levels (e.g., just Critical and High).
    - By Status: `--fixable | --non-fixable` Filter to show only "Fixable" vulnerabilities (where a patch exists) or "Non-Fixable" ones.
  - Supports `--output-format json | pretty_json` for programmatic usage


## [1.13.0] - 2026-02-16

### Added

- Added `CLOUDSMITH_NO_KEYRING` environment variable to disable keyring usage globally. Set `CLOUDSMITH_NO_KEYRING=1` to skip system keyring operations.
- Added `--request-api-key` flag to `cloudsmith auth` command for fully automated, non-interactive API token retrieval. Auto-creates a token if none exists, or auto-rotates (with warning) if one already exists. Compatible with `--save-config` and `CLOUDSMITH_NO_KEYRING`.
- Added `--verbose` (`-v`) flag to `cloudsmith whoami` to show detailed authentication information including active method (API Key or SSO Token), credential source, token metadata, and SSO status. Supports `--output-format json`.
- Added `cloudsmith logout` command to clear stored authentication credentials and SSO tokens.
  - Clears credentials from `credentials.ini` and SSO tokens from the system keyring
  - `--keyring-only` to only clear SSO tokens from the system keyring
  - `--config-only` to only clear credentials from `credentials.ini`
  - `--dry-run` to preview what would be removed without making changes
  - Supports `--output-format json` for programmatic usage

### Deprecation Notices

- The `--token` flag on `cloudsmith auth` is deprecated. Use `--request-api-key` instead.
- The `--force` flag on `cloudsmith auth` is deprecated. Use `--request-api-key` instead (force behavior is implied).
- The `--json` flag on `cloudsmith auth` is deprecated. Use `--output-format json` instead.

## [1.12.1] - 2026-02-03

### Added

- Added Model Context Protocol (MCP) server support via `cloudsmith mcp` commands. Only STDIO transport is supported for now.
- Auto-configure supported clients (Claude Desktop, Cursor, VS Code, Gemini CLI) with `cloudsmith mcp configure`
- List available tools with `cloudsmith mcp list_tools` and tool groups with `cloudsmith mcp list_groups`
- Filter tools via `mcp_allowed_tools` and `mcp_allowed_tool_groups` configuration options to control which API operations are exposed

## [1.12.0] - 2026-02-02

### Added

- Added Generic Format support for pushing packages to repositories.
- Added Upstream support for managing upstream proxy configurations.

## [1.11.2] - 2026-01-22

## Added

- Migrate from CircleCI to GitHub Actions for testing and release workflows.
- Remove CircleCI workflows.
- Migrate from using `shiv` for zipapp generation to `pex` in order to support specific platform/arch and improve testing framework.
- Add zizmor for GitHub Actions code scans, part of workflow and pre-commit.
- Support output format for `--version` in order to allow JSON parsing.

## [1.10.3] - 2026-01-08

### Deprecation Notice

- The `--json` flag used in `cloudsmith auth` command will be removed in upcoming releases. Please migrate to `--output-format json` instead.

### Fixed

- Fixed JSON output for all commands
  - Informational messages, warnings, and interactive prompts are now routed to stderr when `--output-format json` is active.
  - Error messages are now formatted as structured JSON on stdout when JSON output is requested.

### Added

- Set `--show-all` to alias `--page-all`
- Add the ability to use a shortcut within `--page-size` to use pass `-1` or `*` to retrieve all pages i.e. `--page-size -1` or `--page-size *` (note the wildcard may require escaping in some shell environments)
- Added support for deny policy management commands (list, create, get, update, delete)

## [1.10.2] - 2026-01-07

### Fixed
- [Issue #250](https://github.com/cloudsmith-io/cloudsmith-cli/issues/250) - Updated `requests_toolbelt` dependency to `>=1.0.0` to ensure compatibility with `urllib3>=2.5` and avoid `urllib3.contrib.appengine` import errors.

## [1.10.1] - 2025-12-16

### Fixed

- Fixed quarantine block/add command

## [1.10.0] - 2025-12-16

### Fixed

- Upgraded `urllib3` from `v1.26.20` to `v2.5.0`.
- Added `mock_keyring` fixture to prevent SSO token refresh attempts during individual `test_rest.py` test which runs in pipelines (full suite passes). Caused by [HTTPretty issue 484](https://github.com/gabrielfalcao/HTTPretty/issues/484).
- Entitlement token list command now fixed
- Drop click dependency from `v8.2.0` to `v8.1.8` to fix dependency issue for Python 3.9

## [1.9.4] - 2025-11-07

> No code changes in this release. Version bump performed for release process consistency and to address packaging/metadata updates.

## [1.9.3] - 2025-11-07

- [[Issue-170]](https://github.com/cloudsmith-io/cloudsmith-cli/issues/170) - Add flag to get all pages

## [1.9.2] - 2025-11-06

### Fixed

- [Issue-235](https://github.com/cloudsmith-io/cloudsmith-cli/issues/235) - Fix for latest zipapp releases not working on < python@3.14

## [1.9.1] - 2025-11-05

### Fixed

- Click v8.3.0 was a breaking update which impacted conversion of Sentinel.UNSET values which impacted the auth --token workflow. Locking to 8.2.x versions and restricted 8.3.0 explicitly.

## [1.9.0] - 2025-11-05

### Added

- New minor version release includes v1.8.8 changes.

## [1.8.8] - 2025-11-05

### Fixed

- `--json` flag for the auth command now outputs json only.

### Added

- Added Python 3.14 support
- Added `download` command to download package binaries directly from Cloudsmith repositories
  - Support for downloading packages with version, format, OS, and architecture filters
  - Progress bar with download speed and size information
  - Automatic checksum verification (MD5, SHA256, SHA1)
  - Dry-run mode to preview downloads without downloading
  - Auto-selection mode with `--yes` flag for scripting
  - `--all-files` option to download all associated files (POM, sources, javadoc, SBOM, etc.) for Maven, NuGet, and other multi-file packages
    - Downloads all files into a folder named `{package-name}-{version}`
    - Supports custom output directory with `--outfile` option
    - Shows file type tags (pkg, pom, sources, javadoc, cyclonedx, sbom)
    - Reports download progress and success/failure summary for each file
## [1.8.7] - 2025-10-27

### Added

- `Cloudsmith auth -o <org> --token` now creates a new token if none previously existed.
- Added support for json output for auth via `--json` param.
- Added new `create` command for tokens. If authenticated and no previous token exists, this allows for new token creation.

## [1.8.6] - 2025-10-16

### Added

- Added `--force` parameter to the Auth command to be used in conjunction with `--token` to refresh tokens without interactive prompts i.e automatic.
- Added `--force` parameter to the Tokens refresh command to automatically refresh without an interactive prompt.

## [1.8.5] - 2025-10-16

### Added

## [1.8.4] - 2025-10-06

### Added

- Support for Conda, Cargo, Go, and Hugging Face upstreams ([#214](https://github.com/cloudsmith-io/cloudsmith-cli/pull/214))

## [1.8.3] - 2025-06-02

- Added 'swift' and 'hex' as available upstream formats.

## [1.8.2] - 2025-06-02

- Make an sdist available as part of the release.

## [1.8.1] - 2025-05-07

- Fix bug that caused configuration to be dropped in the authenticate command.
- Fix bug in the default configuration schema.

## [1.8.0] - 2025-05-02

### Added

- Added support for managing User API Tokens ([#192](https://github.com/cloudsmith-io/cloudsmith-cli/pull/192))

## [1.7.2] - 2025-04-28

### Added

- Added a fix for certain login error messages being suppressed ([#196](https://github.com/cloudsmith-io/cloudsmith-cli/pull/196))

## [1.7.1] - 2025-04-25

### Added

- Added support for 2FA authentication when logging in ([#188](https://github.com/cloudsmith-io/cloudsmith-cli/pull/188))

## [1.7.0] - 2025-03-31

### Added

- Added `--extra-files` parameter for Maven upload command ([#190](https://github.com/cloudsmith-io/cloudsmith-cli/pull/190))

## [1.6.2] - 2025-03-27

- Added html templates for saml response endpoints
- Added json support for whoami
- Added support for additional headers to be passed to the saml authentication flow

## [1.5.0] - 2025-03-21

### Added

- Added `--sort` flag for package list command ([#185](https://github.com/cloudsmith-io/cloudsmith-cli/pull/185))

### Fixed

- Fixed `cloudsmith auth` command where it results in `403` ([#183](https://github.com/cloudsmith-io/cloudsmith-cli/pull/183))

## [1.4.1] - 2024-11-26

### Added

 - Update cloudsmith-api to v2.0.16 ([#181](https://github.com/cloudsmith-io/cloudsmith-cli/pull/181))


## [1.4.0] - 2024-11-04

### Added

- Dropped support for Python 3.8. ([#137](https://github.com/cloudsmith-io/cloudsmith-cli/pull/137))

## [1.3.1] - 2024-10-08

### Fixed

 - Missing dependency from `setup.py` file ([#177](https://github.com/cloudsmith-io/cloudsmith-cli/pull/177))

## [1.3.0] - 2024-10-08

### Added

- The `auth` command, enabling users to authenticate against the API with their organization's configured SAML provider ([#174](https://github.com/cloudsmith-io/cloudsmith-cli/pull/174))

## [1.2.5] - 2024-06-11

### Added

- Produce CLI zipapp artefact on release ([#164](https://github.com/cloudsmith-io/cloudsmith-cli/pull/164))

## [1.2.3] - 2024-04-10

### Fixed

- Show pagination info for `repos get` ([#163](https://github.com/cloudsmith-io/cloudsmith-cli/pull/163))

## [1.2.2] - 2024-04-05

### Added

- Support for Swift package uploads ([#161](https://github.com/cloudsmith-io/cloudsmith-cli/pull/161))

## [1.2.0] - 2024-03-13

### Added

- Support for CRAN upstreams ([#157](https://github.com/cloudsmith-io/cloudsmith-cli/pull/157))

## [1.1.1] - 2023-09-13

### Fixed

- Revert change to urllib3 Retry constructor `method_whitelist`/`allowed_methods` kwarg ([#148](https://github.com/cloudsmith-io/cloudsmith-cli/pull/148))

## [1.1.0] - 2023-09-08

### Added

- Added support for large file uploads ([#143](https://github.com/cloudsmith-io/cloudsmith-cli/pull/143))

### Fixed

- Removed more unused dependencies relating to python 2.7 compatibility ([#142](https://github.com/cloudsmith-io/cloudsmith-cli/pull/142))

## [1.0.0] - 2023-08-10

### Breaking change

- Dropped support for EOL versions of Python (<3.8). ([#134](https://github.com/cloudsmith-io/cloudsmith-cli/pull/134))

## [0.44.0] - 2023-08-07

### Added

- Added `upstream` commands ([#131](https://github.com/cloudsmith-io/cloudsmith-cli/pull/131))

## [0.43.0] - 2023-06-03

### Added

- Added `--sbt-version` and `--scala-version` support for maven upload ([#128](https://github.com/cloudsmith-io/cloudsmith-cli/pull/128))

## [0.42.0] - 2023-05-25

### Added

- Added `--ivy-file` support for maven upload ([#125](https://github.com/cloudsmith-io/cloudsmith-cli/pull/125))

## [0.41.1] - 2023-05-18

### Fixed

- Removed type annotations from `maybe_truncate_list` and `maybe_truncate_string` to fix python 2.7 support ([#120](https://github.com/cloudsmith-io/cloudsmith-cli/pull/120))

## [0.41.0] - 2023-05-18

### Added

- Added support for `package_query_string` to license and vulnerability policy management ([#118](https://github.com/cloudsmith-io/cloudsmith-cli/pull/118))

## [0.40.1] - 2023-05-11

### Fixed

- `cloudsmith whoami` no longer errors for Services ([#116](https://github.com/cloudsmith-io/cloudsmith-cli/pull/116))

## [0.40.0] - 2023-05-11

### Added

- Added support for license policy management ([#113](https://github.com/cloudsmith-io/cloudsmith-cli/pull/113))

## [0.39.0] - 2023-05-09

### Added

- Added support for vulnerability policy management ([#111](https://github.com/cloudsmith-io/cloudsmith-cli/pull/111))

## [0.38.1] - 2023-05-08

### Fixed

- Write Python 2 deprecation message to stderr. ([#109](https://github.com/cloudsmith-io/cloudsmith-cli/pull/109))

## [0.38.0] - 2023-05-08

### Added

- Added deprecation warning to output for Python 2. ([#106](https://github.com/cloudsmith-io/cloudsmith-cli/pull/106))

## [0.37.2] - 2023-05-01

### Fixed

- Updated incorrect push format parameter descriptions.

## [0.37.1] - 2023-04-30

### Fixed

- Pinned urllib3 due to it dropping support for py2.

## [0.37.0] - 2023-03-29

### Fixed

- Try harder to find a user's `~/.cloudsmith` across operating systems, so config files are found.

## [0.36.1] - 2023-02-21

### Fixed

- Revert minimum allowed version of `click` to `7.0.0`.

## [0.36.0] - 2023-02-21

### Fixed

- Bump minimum allowed version of `click` to `8.0.3`.

## [0.35.2] - 2022-12-15

### Fixed

- Temporarily disable client-side validation within the cloudsmith-api.

## [0.35.1] - 2022-12-14

### Fixed

- Fixed an issue where datetime objects couldn't be serialised when outputting as JSON.

## [0.35.0] - 2022-12-14

### Fixed

- Updated to support cloudsmith-api v.2.0.0

## [0.34.0] - 2022-09-30

### Fixed

- Fixed a typo in permission exceptions.
- Removed linting noqas from help docs.

## [0.33.0] - 2022-05-20

### Fixed

- add '.' to config search paths ([#78](https://github.com/cloudsmith-io/cloudsmith-cli/pull/78))

### Preview

- add quarantine add/rm command ([#80](https://github.com/cloudsmith-io/cloudsmith-cli/pull/80))

## [0.32.0] - 2022-03-03

### Fixed

- Update API client initialization to support newer versions of `cloudsmith-api`.

## [0.31.1] - 2021-12-22

### Fixed

- Fixed issue with JSON-based output for the `dependencies` command.

## [0.31.0] - 2021-12-21

### Added

- Added the `cloudsmith dependencies` sub-command, to list package dependencies.

## [0.30.2] - 2021-12-20

### Fixed

- The ordering of the columns in the quota command has been fixed.

## [0.30.1] - 2021-11-32

### Fixed

- `cloudsmith push` will now pause/sleep the process when calling the status endpoint during pushes (thanks to bagoston).

## [0.30.0] - 2021-10-18

### Fixed

- Documentation generation for PyPi was broken; converted to markdown and fixed.

## [0.29.0] - 2021-10-11

Documentation release.

## [0.28.2] - 2021-10-09

Documentation release.

## [0.28.1] - 2021-10-09

### Fixed

- Automatic releasing of CLI via CircleCI fixed.

## [0.28.0] - 2021-05-18

### Fixed

- Support for Python 2 with the new package and token metrics changes

## [0.27.0] - 2021-05-17

Note: This release requires `cloudsmith-api` >= `0.57.1`.

### Breaking change

- Rework package and token metrics

## [0.26.0] - 2020-11-18

Note: This release requires `cloudsmith-api` >= `0.54.15`.

### Added

- Support for Organization Usage Metrics API
- Fix for rendering Entitlement Token restrictions via the CLI

## [0.25.5] - 2020-11-05

- Fixed formatting JSON results for the `metrics` and `quota` commands; `-F json` should work now.

## [0.25.4] - 2020-10-20

Note: This release requires `cloudsmith-api` >= `0.53.79`.

### Changed

- Resolves breaking changes in Bandwidth Usage Metrics.

## [0.25.3] - 2020-09-25

### Changed

- Implements Bandwidth controls for Entitlment Tokens.

## [0.25.2] - 2020-09-23

### Changed

- The builtin rate-limiting will no longer throttle at exit (prevents hanging on shutdown).
- The builtin rate-limiting will display a message when throttled by 429 responses.

## [0.25.1] - 2020-09-21

### Added

- The push command will now display how long it took to sync/fail a package upload.

### Changed

- The synch wait interval is now a minimum bound, and increases over time.

### Fixed

- The synch progress bar will now display immediately, instead of being delayed.

## [0.25.0] - 2020-09-16

Note: This release requires `cloudsmith-api` >= `0.53.3`.

### Added

- Support for Quota API limits & history

## [0.24.2] - 2020-09-08

### Fixed

- Fixed Python3 compatibility (removed f-string)

## [0.24.1] - 2020-09-04

Note: This release requires `cloudsmith-api` >= `0.52.92`.

### Added

- Support for Package Usage Metrics API

## [0.24.0] - 2020-09-01

Note: This release requires `cloudsmith-api` >= `0.52.79`.

### Added

- Support for Usage Metrics API

## [0.23.0] - 2020-07-07

Note: This release requires `cloudsmith-api` >= `0.52.0`.

### Added

- Support for package tagging: `list`, `add`, `clear`, `remove` and `replace` tags.
- Support for debian DSC (source file) uploading.

### Fixed

- Publishing a duplicate package without specifying `--publish` or `--no-republish` will now default to the repository republish settings.

## [0.22.2] - 2020-06-11

### Added

- Support for Terraform modules.
- Update for (C/C++) Conan push command to allow an optional name and version to be provided.

## [0.22.1] - 2020-06-10

### Added

- Update for (C/C++) Conan packages.

## [0.22.0] - 2020-06-05

### Added

- Support for (C/C++) Conan packages.

## [0.21.0] - 2020-04-16

### Added

- Support for repositories API and subcommands (`list`, `create`, `retrieve`, `update` and `delete`).

## [0.20.1] - 2020-03-27

### Fixed

- Version specifier set by `0.20.0` wasn't compatible with older versions of Python.

## [0.20.0] - 2020-03-27

**Note:** This release pins the Cloudsmith API library to version 0.x due to
changes in the versioning of the library. If you're having issues with an older
version of the CLI that installs the latest API, please upgrade your CLI
version, or install `cloudsmith-api==0.49.94`.

### Changed

- Pinned the Cloudsmith API library version to 0.x+ (excl. 1.x+ series).

## [0.19.2] - 2020-03-27

### Fixed

- Credentials config file not being populated with API key by `cloudsmith login`.

## [0.19.1] - 2020-02-07

### Fixed

- Missing README information on PyPi.

## [0.19.0] - 2020-02-06

### Added

- Support for (Objective-C and Swift) CocoaPod packages.

## [0.18.0] - 2019-12-20

### Added

- Support for (Google) Dart packages.

## [0.17.3] - 2019-10-18

### Fixed

- Fixed issue with displaying entitlements.

## [0.17.2] - 2019-10-17

### Fixed

- Regression with the `cloudsmith login` and `cloudsmith token` commands where they didn't execute correctly.

## [0.17.1] - 2019-10-04

### Fixed

- `cloudsmith login` command (so that it is properly recognised) (thanks to @robmadole for reporting).

## [0.17.0] - 2019-09-20

### Changed

- Upgraded suggested version of python-click to >=7.0.
- Renamed the `cloudsmith token` command to `cloudsmith login` (token still works).

### Fixed

- Parsing of booleans from config files.
- Tolerance of booleans without values in config files (thanks to @Mno-hime for reporting).

## [0.16.0] - 2019-09-18

### Added

- Support for --content-type when uploading Raw packages.

## [0.15.0] - 2019-09-03

### Added

- Support for NuGet packages (via API update).

## [0.14.0] - 2019-08-29

### Added

- Support for --without-api-ssl-verify to turn off SSL verification.

## [0.13.0] - 2019-08-20

### Added

- Support for Go modules.

## [0.12.0] - 2019-08-14

### Added

- Support for R/CRAN packages.

### Fixed

- Ordering of parameter decorators.

## [0.11.0] - 2019-08-07

### Added

- Support for LuaRocks modules.

### Fixed

- Removed duplicated --dry-run parameter in push command (thanks to @SeanTAllen of @ponylang).


## [0.10.0] - 2019-04-25

### Added

- Support for Cargo registry crates.


## [0.9.0] - 2019-04-16

### Added

- Support for Docker registry image containers.


## [0.8.2] - 2019-04-03

### Fixed

- Issue with executing in py2/py3 using entrypoint.


## [0.8.0] - 2019-04-03

### Added

- Support for Helm repository charts/packages (https://github.com/helm/charts).
- Support for republishing packages (overwrite existing versions).


## [0.7.2] - 2019-02-19

### Fixed

- Python 3.x compatibility due to not decoding request responses properly.


## [0.7.1] - 2019-02-13

### Added

- 501, 502, 503 and 504 errors received from the API will now be retried, with exponential backoff.

### Fixed

- Entitlement command output will now respect pretty format properly and not send non-output to sysout.


## [0.7.0] - 2018-10-13

### Added

- Support for Alpine Linux and NPM/npm packages.
- Updated and pinned cloudsmith-api dependency to 0.32.11.


## [0.6.3] - 2018-08-17

### Added

- Compatibility with upcoming API changes for listing repositories.

### Fixed

- Regression in listing packages caused by typo.


## [0.6.2] - 2018-08-16

### Changed

- When calling `ls repos`, the CLI will now list all repositories that the user can see.

### Fixed

- Compatibility with API changes for listing repositories.


## [0.6.1] - 2018-08-01

### Fixed

- Pinned cloudsmith-cli to 0.30.7 to fix issues with entitlements actions.


## [0.6.0] - 2018-07-31

### Added

- Updated and pinned cloudsmith-api dependency to 0.30.3.
- Added support for latest API (0.30.x+) which changed how packages are referenced (slug -> identifier).
- Added support for latest API (0.30.x+) which changed how entitlements are referenced (slug_perm -> identifier).


## [0.5.7] - 2018-05-07

### Added

- Always print rate limit information at exit (if throttled).

### Fixed

- #5: Credentials file not loading when explicitly specified via command-line parameter.
- #6: Ensure that a non-zero status is always returned on errors/failures.
- Exit with an error after running out of sync attempts.


## [0.5.6] - 2018-03-25

### Fixed

- Issue with entitlements create command crashing because `--name` was left off.


## [0.5.5] - 2018-03-25

### Fixed

- Issue with the move subcommand due to typo in string formatting.


## [0.5.4] - 2018-03-25

### Fixed

- Issue with entitlements due to issue in API library.


## [0.5.3] - 2018-03-25

### Fixed

- Issue with status subcommand failing due to API mismatch.


## [0.5.2] - 2018-03-25

### Fixed

- Issue with package synchronisation stalling due to typo in status check.


## [0.5.1] - 2018-03-25

### Added

- Display status reason text when a package fails, and give up attempting if it was fatal.


## [0.5.0] - 2018-03-25

### Added

- Support for aliased subcommands, starting with `delete` = `rm`, `list` = `ls` and `push` = `upload`.
- Support for retrieving rate limits from the API via `check limits`.
- Support for searching packages via `-q|--query` search query parameter.
- Support for `copy` (`cp`), move (`mv`) and `resync` package subcommands.
- Support for automatic resyncing when the sync fails (attempts can be controlled using `--sync-attempts`).
- Support for formatting the output of `list` subcommands (`distros`, `packages` and `json`) as JSON using `-F` or `--output-format`).
- Support for entitlements API and subcommands (`list`, `create`, `update`, `delete`, `refresh` and `sync`).
- Automatic rate limiting based on usage across all API calls (it can be turned off using `-R`).
- Utility for printing tables (internal only, but expect consistent tables for list-based results).


## Changed

- Minimum API version required is now 0.26.0+.
- The check command is now a list of sub-commands, and `check service` is now for checking the service status.


## [0.4.1] - 2018-03-12

### Added

- Support for pagination (page and page size) for lists, such as listing packages and repositories.


## [0.3.4] - 2018-03-05

### Fixed

- Made documentation for cloudsmith push clearer for formats that support distro/release.
- Serialization for API headers (especially Authorization) - No impact for most users.


## [0.3.2] - 2018-01-05

### Security

- When writing a default `credentials.ini` file, use `ug+rw` for permissions instead of world-readable.

### Fixed

- Issue #2: Not able to upload in Python3-based environments due to code incompatibility.


## [0.3.1] - 2017-12-06

### Added

- Silly (but nice) ASCII art banner for help command.
- Default creds/non-creds config files are now created/initialised on `cloudsmith token`.
- Support for `CLOUDSMITH_CONFIG_FILE` and `CLOUDSMITH_CREDENTIALS_FILE` environment variables.
- Support for adding arbitrary headers to the API via `--api-headers` and `CLOUDSMITH_API_HEADERS`.


## [0.2.2] - 2017-12-03

### Fixed

- Pin for `cloudsmith-api` is now correctly set to `0.21.3`.


## [0.2.1] - 2017-12-03

Phase 2 release.

### Added

- Configuration profiles, to support multiple environments.
- Options for `api_host`, `api_proxy` and `api_user_agent` in config file.
- The `help` command for those who need more than `-h` and `--help`.
- Support for uploading multiple package files at once.
- Tox-based testing for Python2.x and Python3.x.
- Pre-flight checks to push/upload command.
- The `list` command with support for listing distros, packages and repos.

### Changed

- Environment variables to use a `CLOUDSMITH_` prefix (not backwards compatible).

### Fixed

- Validation for `push` commands that require a distribution.
- Token endpoint failing because API key overrides login/password.
- Python3 compatibility so that it now runs with Py3. :-)


## [0.1.0] - 2017-11-23

Phase 1 release (initial release).
