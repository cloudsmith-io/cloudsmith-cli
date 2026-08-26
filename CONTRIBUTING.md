# Contributing

Please refer to Cloudsmith's standard guide on [Open-Source Contributing](https://docs.cloudsmith.com/resources/contributing).


## Contributor License Agreement

By making any contributions to Cloudsmith Ltd projects you agree to be bound by the terms of the Cloudsmith Ltd [Contributor License Agreement](https://docs.cloudsmith.com/resources/contributor-license-agreement).


## Development Environment

The basic requirements are:
- Any [current version](https://endoflife.date/python) of Python.
- The ability to install PyPI packages (preferably in a virtual environment).

All dependencies are declared in [pyproject.toml](./pyproject.toml): production deps under `[project.dependencies]`, with development, binary-build, and release tooling in dependency groups. Exact versions are locked in [uv.lock](./uv.lock).

For most purposes you just want [uv](https://docs.astral.sh/uv/): `uv sync --locked --group dev` creates a virtual environment with the project (editable) and all dev dependencies installed.

Our [direnv config](./.envrc) file codifies the development environment setup which we use internally.

## Coding Conventions

Please ensure code conforms to [PEP-8](https://www.python.org/dev/peps/pep-0008/) and [PEP-257](https://www.python.org/dev/peps/pep-0257/).


## Releasing

To make a new release for `cloudsmith-cli`:

```
$ bumpversion <major|minor|revision>
```

A tag will automatically created along with the version bump commit. Push the tag with `git push origin {version}`

Please ensure that [CHANGELOG.md](./CHANGELOG.md) is updated appropriately with each release.


## Need Help?

See the section for raising a question in the [Contributing Guide](https://docs.cloudsmith.com/resources/contributing).
