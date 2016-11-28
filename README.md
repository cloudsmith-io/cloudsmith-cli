# Cloudsmith Command Line Interface (CLI)

The [Cloudsmith](https://cloudsmith.io) Command Line Interface (CLI) is a Py2/Py3 text-based interface to the [API](https://api.cloudsmith.io). This allows users, machines and other services to access and integrate smoothly with Cloudsmith without requiring explicit plugins or tools.

## Features

The CLI currently supports the following commands:

- `check`:  Check the status/version of the service.
- `delete`: Delete a package from a repository.
- `docs`:   Launch the help website in your browser.
- `push`:   Push/upload a new package to a repository.
- `status`: Get the synchronisation status for a package.
- `token`:  Retrieve your API authentication token/key.
- `whoami`: Retrieve your current authentication status.

## Configuration

There are two configuration files used by the CLI:

- `config.ini`: For non-credentials configuration.
- `credentials.ini`: For credentials (authentication) configuration.

By default, the CLI will look for these in the following locations:

- The current working directory.
- A directory called `.cloudsmith` in the OS-defined application directory ($HOME for Linux, AppData for Windows, etc.)

Both configuration files use the simple INI format, such as:

```
# Default configuration
[default]
api_key='1234567890abcdef1234567890abcdef'

# Profile-based configuration (not working yet)
[profile:cloudsmith]
api_key='fedcba0987654321fedcba0987654321'
```

### Non-Credentials (config.ini)

TODO

### Credentials (credentials.ini)

You can specify the following configuration options:

- `api_key`: To specify the authentication key/token for API access.

## Examples

TODO: Provide a list of examples for the CLI tool.

## Contributing

Yes! Please do contribute, this is why we love open source.  Please see `CONTRIBUTING.md` for contribution guidelines when making code changes or raising issues for bug reports, ideas, discussions and/or questions (i.e. help required).

## Releasing

To make a new release for `cloudsmith-cli` follow the procedure for virtualenv setup then:

```
$ bumpversion <major|minor|revision>
```

A tag will automatically created along with the version bump commit.

## EOF

This quality product was brought to you by [Cloudsmith](https://cloudsmith.io) and the fine folks mentioned in `CONTRIBUTORS.md`.
