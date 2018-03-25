# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

**Note:** Until 1.0 any MAJOR or MINOR release may have backwards-incompatible changes.

## [Unreleased]

Nothing yet.


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
