# Cloudsmith CLI

[![Latest version on Cloudsmith](https://api-prd.cloudsmith.io/badges/version/cloudsmith/cli/python/cloudsmith-cli/latest/xf=bdist_wheel;xn=cloudsmith-cli;xv=py3/?render=true)](https://cloudsmith.io/~cloudsmith/repos/cli/packages/detail/python/cloudsmith-cli/latest/xf=bdist_wheel;xn=cloudsmith-cli;xv=py3/)
[![Python versions](https://img.shields.io/pypi/pyversions/cloudsmith-cli.svg)](https://pypi.python.org/pypi/cloudsmith-cli)
[![PyPI version](https://img.shields.io/pypi/v/cloudsmith-cli.svg)](https://pypi.python.org/pypi/cloudsmith-cli)
[![Test](https://github.com/cloudsmith-io/cloudsmith-cli/actions/workflows/test.yml/badge.svg)](https://github.com/cloudsmith-io/cloudsmith-cli/actions/workflows/test.yml)
[![Lint](https://github.com/cloudsmith-io/cloudsmith-cli/actions/workflows/lint.yml/badge.svg)](https://github.com/cloudsmith-io/cloudsmith-cli/actions/workflows/lint.yml)

The Cloudsmith CLI (`cloudsmith`) manages packages, repositories, and access in [Cloudsmith](https://cloudsmith.com) from a terminal or CI/CD pipeline. It wraps the [Cloudsmith API](https://api.cloudsmith.io) so scripts and pipelines can push, download, promote, and inspect packages without custom tooling.

## Get started

To install the CLI, authenticate, and configure it, see the [Cloudsmith CLI documentation](https://docs.cloudsmith.com/developer-tools/cli). It covers installation with pip, the install script, Homebrew, or Docker, and authentication with an API key, SAML, or OIDC.

To list the commands, run `cloudsmith --help`. For the options of one command, run `cloudsmith <command> --help`.

## Get help

- **Documentation:** [docs.cloudsmith.com/developer-tools/cli](https://docs.cloudsmith.com/developer-tools/cli)
- **Release notes:** [CHANGELOG.md](./CHANGELOG.md)
- **Bugs and feature requests:** [GitHub issues](https://github.com/cloudsmith-io/cloudsmith-cli/issues)
- **Security issues:** see [SECURITY.md](./SECURITY.md). Do not open a public issue.

> [!NOTE]
> The CLI sends anonymous error reports when a command fails unexpectedly. To turn this off, set `DO_NOT_TRACK=1`. See [CHANGELOG.md](./CHANGELOG.md) for details.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for development setup, tests, and the release process. [CONTRIBUTORS.md](./CONTRIBUTORS.md) lists maintainers and contributors.

## License

Copyright 2018 Cloudsmith Ltd. Licensed under the [Apache License, Version 2.0](./LICENSE).
