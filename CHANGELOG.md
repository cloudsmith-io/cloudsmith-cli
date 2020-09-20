# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

**Note:** Until 1.0 any MAJOR or MINOR release may have backwards-incompatible changes.

## [Unreleased]

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
