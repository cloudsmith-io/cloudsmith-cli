# Threat model

## What this project does and where untrusted input enters
The Cloudsmith CLI (`cloudsmith`) is a Python client for the Cloudsmith package-management API. Users run it on laptops and in CI. It holds API keys, SSO tokens and OIDC-exchanged tokens. It also writes credential helpers and config for package managers (Docker, Cargo, pnpm, Terraform) and for MCP clients.

Untrusted:
- API responses from the Cloudsmith API host and from custom domains (`core/api/*`, `core/rest.py`, `core/pagination.py`, `core/download.py`). This includes package names, filenames, download URLs and checksums.
- Requests to the SSO callback server. `cloudsmith auth` listens on `localhost` ports 12400-12404 (`cli/commands/auth.py`, `cli/webserver.py`, `cli/saml.py`, `core/sso.py`). Any local process or browser page can send a request to it.
- CI identity tokens and the metadata endpoints that supply them (`core/credentials/oidc/detectors/*`), and the OIDC exchange response (`core/credentials/oidc/exchange.py`).
- Requests from package managers to the credential helper runtimes (`credential_helpers/*/runtime.py`). The host name in the request decides which credential the helper returns.
- Existing package-manager config files that the installers parse and rewrite: `~/.docker/config.json`, Cargo config, `.npmrc`, `.terraformrc` (`credential_helpers/*/installer.py`, `credential_helpers/pnpm/rc.py`, `credential_helpers/terraform/terraformrc.py`).
- Files that the user uploads or attaches with `push`, including Debian `.dsc` files (`cli/dsc_parser.py`) and SBOM or BuildInfo metadata (`cli/metadata_common.py`).
- The OpenAPI specs that the MCP server loads at runtime to build its tools (`core/mcp/server.py`). The MCP client talks to the server over stdio and is an LLM agent.
- The release manifest and bundle for self-update (`core/update_check.py`, `core/self_update.py`).

Trusted: command-line flags, environment variables, `config.ini` and `credentials.ini` that the user owns, and the OS keyring.

## Components that matter most / least
- Credential scoping. A credential must only go to the host that it belongs to. This covers `core/credentials/chain.py`, the providers in `core/credentials/providers/`, the credential helper runtimes, and the custom-domain lookup (`credential_helpers/domains.py`, `credential_helpers/common.py`). Host-name parsing and matching bugs are in scope.
- Token storage: `core/keyring.py`, `core/macos_keychain.py`, and the OIDC token cache (`core/credentials/oidc/cache.py`). File permissions and cross-profile leaks are in scope.
- The SSO callback server: CSRF, token injection, and open redirects.
- File writes from untrusted data: download paths from API filenames, tar extraction in `core/self_update.py`, and edits to package-manager and MCP client config files (`cli/commands/mcp.py`).
- Self-update integrity: the SHA-256 check and the bundle replace and rollback logic.
- Out of scope: the generated `cloudsmith-api` SDK, tests under `*/tests/`, and the `bin/` and `packaging/` directories.

## How to exercise it
- `cloudsmith` and `pytest` are in `/usr/local/bin`. The unit tests are in `cloudsmith_cli/cli/tests/` and `cloudsmith_cli/core/tests/`. Run `pytest cloudsmith_cli -m "not integration"`.
- The tests stub HTTP with `httpretty`. Use the same method, or a local HTTP server, to act as a malicious API host or custom domain.
- Set `CLOUDSMITH_API_HOST` to point the CLI at a local server.

## How you rate severity
- Critical: code execution on the user's machine caused by an API response, a custom domain, a CI metadata endpoint or a request to the SSO callback server.
- High: an API key, SSO token or OIDC token sent to a host that does not own it; token theft through the SSO callback; arbitrary file write or path traversal from API data or an archive; a self-update bypass of the SHA-256 check.
- Medium: tokens stored with weak file permissions; credential leaks between profiles; a crash or hang caused by a malicious server; injection into config files that the CLI writes.
- Low: terminal escape injection in output; information leaks that do not expose credentials.

## Anything to leave alone
- The user's own flags, environment variables and config files behaving as documented, including `CLOUDSMITH_API_HOST` set to any host.
- Tokens visible to other processes that run as the same OS user.
- Vulnerabilities in third-party dependencies with no reachable path in the CLI.
