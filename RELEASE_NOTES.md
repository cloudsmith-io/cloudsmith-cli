# Release Notes

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## [Unreleased]

- **Added** configuration profiles, to support multiple environments.
- **Added** `api_host`, `api_proxy` and `api_user_agent` to config file.
- **Added** `help` command for those who need more than `-h` and `--help`.
- **Changed** environment variables to use a `CLOUDSMITH_` prefix.
- **Fixed** validation for `push` commands that require a distribution.
- **Fixed** token endpoint failing because API key overrides login/password.

## [0.1.0] - 2017-11-23

- Initial release.
