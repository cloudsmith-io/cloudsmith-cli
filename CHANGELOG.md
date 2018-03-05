# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

**Note:** Until 1.0 any MAJOR or MINOR release may have backwards-incompatible changes.

## [Unreleased]

Phase 3 release.

### Fixed

- Made documentation for cloudsmith push clearer for formats that support distro/release.
- Serialization for API headers (especially Authorization) - No impact for most users.


## [0.3.2]

Bugfix release.

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
