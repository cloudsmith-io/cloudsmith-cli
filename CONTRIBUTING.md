# Contributing

Thanks for helping improve the Cloudsmith CLI. This guide covers the development setup, tests, and release process for this repository. For general guidance on raising issues and pull requests, see the Cloudsmith [open-source contributing guide](https://docs.cloudsmith.com/resources/contributing).

For CLI usage, see the [CLI documentation](https://docs.cloudsmith.com/developer-tools/cli).

## Contributor License Agreement

By contributing to Cloudsmith Ltd projects, you agree to the Cloudsmith Ltd [Contributor License Agreement](https://docs.cloudsmith.com/resources/contributor-license-agreement).

## Set up a development environment

Prerequisites:

- Python 3.11 or later.
- [uv](https://docs.astral.sh/uv/).

Steps:

1. Create a virtual environment with the CLI (editable) and the development dependencies:

   ```sh
   uv sync --locked --group dev
   ```

2. Install the pre-commit hooks:

   ```sh
   uv run pre-commit install
   ```

3. Confirm the CLI runs from your checkout:

   ```sh
   uv run cloudsmith --version
   ```

The [direnv config](./.envrc) automates these steps if you use [direnv](https://direnv.net/).

Dependencies are declared in [pyproject.toml](./pyproject.toml) and locked in [uv.lock](./uv.lock). After you change a dependency, run `uv lock` and commit the updated lock file.

## Run tests

Run the unit tests:

```sh
uv run pytest -m "not integration"
```

Tests marked `integration` call the live Cloudsmith service and need the `PYTEST_CLOUDSMITH_*` environment variables. See [.env.example](./.env.example).

## Lint and format

The pre-commit hooks run [Ruff](https://docs.astral.sh/ruff/) for formatting and linting, plus pyupgrade, typos, and secret scanning. Run them on all files before you open a pull request:

```sh
uv run pre-commit run --all-files
```

## Submit a pull request

1. Add or update tests for your change.
2. Add an entry under `[Unreleased]` in [CHANGELOG.md](./CHANGELOG.md) for user-facing changes.
3. Open a pull request and complete the template.

## Release a new version

Maintainers release new versions. The `master` branch is protected, so the version bump goes through a pull request:

1. On a new branch, bump the version without a commit or a tag:

   ```sh
   uv run bumpversion <major|minor|revision> --no-commit --no-tag
   ```

2. Move the `[Unreleased]` entries in [CHANGELOG.md](./CHANGELOG.md) under the new version.
3. Open a pull request with these changes and merge it.
4. Tag the merged commit on `master` and push the tag:

   ```sh
   git tag v<version>
   git push origin v<version>
   ```

The tag push starts the release workflow. The workflow fails if the tag does not match the `VERSION` file on `master`.

## Get help

To ask a question, see the [open-source contributing guide](https://docs.cloudsmith.com/resources/contributing) or open a [GitHub issue](https://github.com/cloudsmith-io/cloudsmith-cli/issues/new/choose).
