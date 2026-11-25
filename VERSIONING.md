# Versioning policy

This policy helps you upgrade the Cloudsmith CLI with confidence. It explains what each type of release can change and which behaviors you can depend on in scripts.

This policy states our intent. It doesn't change the [Apache License 2.0](LICENSE), which provides the CLI "as is", without warranties or conditions of any kind.

## Overview

- Release versions use the `MAJOR.MINOR.PATCH` format from [Semantic Versioning 2.0.0](https://semver.org/), with the exceptions listed in the [breaking change reference](#breaking-change-reference).
- A command or option in [early access](#early-access) can change in a minor release. Early access lasts a maximum of 6 months.
- Cloudsmith deprecates features before it removes them. Only a major version removes a [deprecated](#deprecation) feature, except for [API-driven changes](#api-driven-changes) and [security fixes](#security-fixes).
- When the Cloudsmith API changes, the CLI follows it in a minor release.
- The `data` and `meta` structure of JSON output on `stdout` stays the same within a major version. Human-readable output on `stdout` stays familiar.
- Output on `stderr`, such as warnings and notices, can change in any release.
- For automation, use JSON output and exit codes. Don't parse human-readable output.

## What each version number means

### Major

Includes changes to the public contract that can break your scripts or pipelines. Read the breaking changes in `CHANGELOG.md` before you upgrade.

### Minor

Adds new features, and can include the minor changes listed in the [breaking change reference](#breaking-change-reference). Scripts that use stable features keep working, but can show new deprecation warnings. These minor changes can break a script:

- A change to a command or option in [early access](#early-access)
- A [bug fix that changes the contract](#bug-fixes-that-change-the-contract)
- A change that a [Cloudsmith API change](#api-driven-changes) requires
- A change to the order of the sources in [credential resolution](#credential-resolution)

### Patch

Includes bug fixes, security fixes, dependency updates, and changes to help text and `stderr` output. The public contract doesn't change, except for an emergency [security fix](#security-fixes).

## Breaking change reference

The following lists show the release type that each change requires.

### Major

- Remove or rename a command, subcommand, alias, or option
- Make an optional argument or option required
- Change an option's default in a way that changes results
- Change the order of positional arguments
- Remove a value that an option accepts
- Remove, rename, or change the type or nesting of the `data` or `meta` field in JSON output, or of a field in `meta.pagination`
- Move the result of a command off `stdout`
- Change the meaning of a listed exit code
- Remove or rename an environment variable or configuration key
- Change the meaning of an environment variable
- Stop reading a configuration directory
- Remove a source from [credential resolution](#credential-resolution)
- Change the precedence of options, environment variables, and configuration files
- Remove a deprecated feature

### Minor

- Add a command, subcommand, option, option value, alias, or environment variable
- Add a field to JSON output
- Add an exit code for a failure that used a generic non-zero code
- Add a configuration file location, while still reading the existing locations
- Move output that isn't a command result from `stdout` to `stderr`
- Add a source to [credential resolution](#credential-resolution), or change the order of the sources
- Change or remove a command, subcommand, or option in [early access](#early-access), including the JSON output of an early access command
- Move a command, subcommand, or option out of [early access](#early-access)
- Mark a feature as deprecated
- Fix a [bug in the contract](#bug-fixes-that-change-the-contract)
- Make a change that a [Cloudsmith API change](#api-driven-changes) requires
- Drop support for a Python version that is end of life upstream
- Change a [distribution channel](#distribution), with notice
- Add a new type or destination of [telemetry](#telemetry)
- Change human-readable output on `stdout`, such as table columns

### Patch

- Fix a bug that doesn't change the contract
- Update a dependency
- Make an emergency [security fix](#security-fixes)
- Change help text, error wording, or `stderr` content

## Use the CLI in scripts and pipelines

We recommend that you:

- Pin an exact CLI version for reproducible CI builds. To pin a version, see the instructions for the [install script](https://docs.cloudsmith.com/developer-tools/cli#installing-with-the-install-script), the [GitHub Actions integration](https://docs.cloudsmith.com/integrations/integrating-with-github-actions#configuration), or the [Homebrew tap](https://github.com/cloudsmith-io/homebrew-cloudsmith-cli#holding-or-rolling-back-a-version).
- If you take updates automatically, stay within one major version.
- If a script uses a command or option in [early access](#early-access), pin the CLI version.
- Use JSON output (`--output-format json`). Read only `stdout`.
- Check exit codes instead of parsing error messages.
- Before you upgrade to the next major version, run your commands without JSON output. Fix the deprecation warnings that they print to `stderr`.
- Read the **Deprecated** and **Removed** sections of [`CHANGELOG.md`](CHANGELOG.md) before you upgrade.

## Public contract

This policy covers the following items. An incompatible change to them requires a major version, except where the [breaking change reference](#breaking-change-reference) lists a minor release. A command or option in [early access](#early-access) joins the contract when Cloudsmith removes its early access label.

"Documented" means described in `--help` or in the [CLI documentation](https://docs.cloudsmith.com/developer-tools/cli). Commands, options, and environment variables that have never been documented aren't part of the contract. Previously documented features remain covered during [deprecation](#deprecation), even when hidden from `--help`.

### Commands and subcommands

The names of commands and subcommands, and their documented aliases. For example, `cloudsmith list packages` and its alias `cloudsmith ls pkgs` keep working, and keep their meaning, for the whole of a major version.

Only a major version can remove or rename a command, subcommand, or alias.

### Arguments and options

For each command, the contract covers:

- The names of its options, and their short forms. For example, `--output-format` and `-F`.
- The order of its positional arguments. For example, `cloudsmith push raw` takes `OWNER/REPO` first, then the file.
- Whether each argument and option is required
- The values that each option accepts. For example, `--output-format` accepts `json`.
- What the command does when you leave out an option. For example, without `--yes`, `cloudsmith delete` asks you to confirm.

Only a major version can:

- Remove or rename an option
- Change the order of arguments
- Make an argument or option required
- Remove a value that an option accepts
- Change what a command does when you leave out an option

A minor release can add options, and new values for an option.

### Environment variables

The names and meanings of documented `CLOUDSMITH_*` environment variables. For example, `CLOUDSMITH_API_KEY` always sets the API key, and `CLOUDSMITH_WORKSPACE` always sets the workspace.

Only a major version can remove or rename one of these variables, or change its meaning.

The CLI also reads standard environment variables that other tools use, such as `NO_COLOR`, `CI`, and `HTTPS_PROXY`. The contract doesn't cover these variables. The CLI follows the common conventions for them.

### Configuration files

The documented keys in `config.ini` and `credentials.ini`, and the directories that the CLI searches for these files. For example, the `api_key` key in `credentials.ini`, the `workspace` key in `config.ini`, `[profile:NAME]` sections, and the `~/.cloudsmith` directory.

For the full list of keys and directories, see [Configuration / setup](https://docs.cloudsmith.com/developer-tools/cli#configuration--setup).

Only a major version can remove or rename a key, or stop reading a directory. A minor release can add a directory, but the CLI continues to read the existing directories.

### Precedence

When you give the same setting in more than one place, the CLI uses the value from the first place in this order:

1. A command-line option, such as `--workspace`
2. An environment variable, such as `CLOUDSMITH_WORKSPACE`
3. A key in `config.ini`, such as `workspace`

For example, if you set `CLOUDSMITH_WORKSPACE=acme` and pass `--workspace demo`, the CLI uses `demo`.

Only a major version can change this order.

Credentials follow the order of sources in [Credential resolution](#credential-resolution).

### Machine-readable output

The structure of JSON output. The `data` field holds the result of the command, and the `meta.pagination` field holds the page details of a list. For example, a list of packages is always in `data`, and the number of results is always in `meta.pagination.results_total`.

Only a major version can remove or rename these fields, or change their type or nesting. A minor release can add fields.

Most fields inside `data` come from the Cloudsmith API, and they change when the API changes. See [API-driven changes](#api-driven-changes).

### Output streams

`stdout` contains the result of the command: the table, the JSON document, or the requested value. The CLI prints warnings, deprecation notices, update notices, retry messages, and debug output to `stderr`. With the default output format, status messages, progress bars, and error messages also go to `stdout`. Output on `stderr` is for people, not scripts, and its content can change in any release.

Only a major version can move the result of a command off `stdout`.

When you select a machine-readable output format, `stdout` contains only valid output in that format. The CLI doesn't show update notices, deprecation warnings, or early access warnings.

Any other output on `stdout` is a [bug in the contract](#bug-fixes-that-change-the-contract), and Cloudsmith fixes it in a minor release.

### Exit codes

`0` means success and non-zero means failure. The following codes keep their meaning. Only a major version can change the meaning of these codes.

| Code | Meaning |
|---|---|
| `0` | The command succeeded. |
| `1` | General failure. For `whoami`, `1` also means that the CLI sent no credentials. Rejected credentials give a different non-zero code. |
| `2` | Usage error, such as an unknown option, or a missing or invalid argument. For `download`, `2` also means that no package matches. |

Other non-zero codes, including the codes that the CLI uses when an API request fails, aren't part of the contract yet. A minor release can replace them with more specific codes. In scripts, check only that the code is non-zero, unless this section lists the code.

A command that exits `0` after a failure, or when it reports a failure state, has a [bug in the contract](#bug-fixes-that-change-the-contract). Cloudsmith fixes it in a minor release.

### Credential resolution

The CLI checks these sources in order, and uses the first credential that it finds:

1. The `--api-key` option
2. The `CLOUDSMITH_API_KEY` environment variable
3. `credentials.ini`
4. A SAML session stored in the system keyring
5. [OpenID Connect (OIDC) auto-discovery](https://docs.cloudsmith.com/developer-tools/cli#automatically-discover-oidc-credentials)

Only a major version can remove a source. A minor release can add a source, or change the order of the sources. `CHANGELOG.md` lists the change under **Changed**, with the old and new order.

### What the contract doesn't cover

The following aren't part of the public contract. They can change in any release, including a patch, unless a release type is specified below or in the linked section:

- The content of `stderr`, such as warnings, notices, log lines, and `--debug` output
- Help text and the wording of error messages
- Interactive prompts, except the behavior that [Arguments and options](#arguments-and-options) lists. The CLI shows a new prompt only when it runs in a terminal, so scripts keep working. In scripts, pass values as options instead.
- Abbreviated command names. The CLI accepts a unique prefix of a command name, such as `vuln` for `vulnerabilities`, but a new command can make a prefix ambiguous.
- The order of results, unless an option sets it
- The structure of JSON error output
- Exit codes other than those listed in [Exit codes](#exit-codes)
- The tools that `cloudsmith mcp` provides. The CLI generates them from the Cloudsmith API's OpenAPI specification.
- The Python modules in the `cloudsmith_cli` package. The package is an application, not a library, and Cloudsmith doesn't support importing it.
- The Python version and dependency versions in standalone binaries and container images
- Fields inside `data` that come from the Cloudsmith API, as described in [API-driven changes](#api-driven-changes)

Human-readable output on `stdout`, such as tables and columns, isn't part of the contract either. Cloudsmith keeps it familiar, and changes it only in a minor release.

## Early access

Cloudsmith can release a new command, subcommand, or option in early access. Early access lets Cloudsmith improve a new feature with your feedback, before the feature joins the public contract.

A feature is in early access only when it has the early access label. A new feature without the label is part of the public contract from its first release.

A feature in early access:

- Shows in `--help` with the `[EARLY ACCESS]` label
- Prints a warning to `stderr` when you use it. The CLI doesn't print this warning with JSON output. Credential helper commands that package managers run don't print it.
- Has an entry under **Added** in `CHANGELOG.md` that says it's in early access

A minor release can change or remove a feature in early access. For a command, this includes its arguments, its options, and its output, including the fields in its JSON output. `CHANGELOG.md` lists each change under **Changed** or **Removed**.

Early access lasts a maximum of 6 months. The 6 months start on the date of the release that adds the feature. Before the 6 months end, Cloudsmith decides to continue or to stop the feature:

- **Continue:** A minor release removes the early access label and the warning. The feature is then part of the public contract, and the usual rules apply.
- **Stop:** A minor release removes the feature. `CHANGELOG.md` lists the removal under **Removed**.

## Deprecation

A minor release can mark a feature as deprecated. A deprecated feature stays part of the public contract until a release removes it, and it:

- Prints a warning to `stderr` that names its replacement, if there is one, and the version that removes it. The CLI doesn't print this warning with JSON output, or when `CLOUDSMITH_SUPPRESS_DEPRECATIONS` is `1`, `true`, or `yes`. Credential helper commands that package managers run don't print it.
- Doesn't show in `--help`, or shows with the `[DEPRECATED]` label
- Has an entry under **Deprecated** in `CHANGELOG.md`
- Keeps working for at least 6 months and 2 minor releases

Only a major version removes a deprecated feature, and only after the deprecation period. The exceptions are API-driven changes and security fixes. `CHANGELOG.md` lists the removal under **Removed**, with its replacement.

Where possible, a removed command or option fails with an error that names its replacement, instead of a generic "no such option" error.

[API-driven changes](#api-driven-changes) and [security fixes](#security-fixes) can remove a feature in a minor release, without a deprecation period. A security fix can also do this in a patch release.

## API-driven changes

The CLI is a client of the Cloudsmith API. When the API deprecates, removes, or changes an endpoint, field, parameter, or authentication method, the CLI follows it in a **minor** release. This can include removing an option or command that only existed for a feature the API no longer provides.

For these changes, Cloudsmith:

- Keeps each command's name, arguments, and options wherever the API still supports them
- Prints a deprecation warning to `stderr` before the change, if the API gives advance notice
- Makes a command that can no longer do its job fail with a non-zero exit code. Its error message explains the API change and suggests an alternative.
- Names the API change in `CHANGELOG.md`

When a command moves to a new API version, the CLI can keep fields that match the earlier API response. Your scripts then keep working. A later minor release can remove these fields.

## Bug fixes that change the contract

Some bugs are in the contract itself. Examples are an exit code that reports success after a failure, a JSON field with the wrong type, and an option that has no effect. Cloudsmith fixes these bugs in a **minor** release, instead of waiting for the next major version. `CHANGELOG.md` lists the fix under **Fixed** as a behavior change, and explains what to do if your script relies on the old behavior.

## Security fixes

If a security fix must break the public contract, Cloudsmith releases it in a minor release. An emergency security fix can also break the public contract in a patch release.

## Distribution

Cloudsmith publishes the CLI through the channels in [Installation](https://docs.cloudsmith.com/developer-tools/cli#installation). These channels are PyPI, the Cloudsmith `cloudsmith/cli` repository, the install scripts, standalone binaries on GitHub releases, the Homebrew tap, and the `cloudsmith/cloudsmith-cli` container image.

The following change only in a minor release, with notice:

- The `cloudsmith` executable name
- Package, formula, and image names
- Standalone binary target names and archive names
- The channels and binary targets that Cloudsmith publishes to
- The container image's entrypoint, default command, and user

Notice means that `CHANGELOG.md` lists the change at least one minor release before it takes effect.

The bundled Python version, base images, image contents other than the CLI, and artifact sizes can change in any release.

## Telemetry

The CLI sends two types of telemetry to Cloudsmith:

- Usage telemetry: after each command, the CLI sends one event. The event contains the command name and the names of the options and environment variables that you set, but never their values. Usage telemetry is on by default, also in CI.
- Error reports: when the CLI fails with an unexpected error, it sends an error report.

To turn off both types, set `CLOUDSMITH_TELEMETRY=disable`. To learn what each type contains and how to turn off each one, see [CLI telemetry](https://docs.cloudsmith.com/developer-tools/cli-telemetry).

If Cloudsmith adds a new type of data or a new destination, `CHANGELOG.md` lists it in that release, with instructions to opt out.

## Supported versions

Only the latest minor release of the current major version receives fixes. To get a fix, upgrade to the latest minor release.

After Cloudsmith releases a new major version, the previous major version receives bug fixes, security fixes, and [API-driven changes](#api-driven-changes) for [N] months.

## How Cloudsmith announces changes

Cloudsmith publishes two changelogs:

- [`CHANGELOG.md`](CHANGELOG.md) is the complete record of every release. It groups the changes in each release under **Added**, **Changed**, **Deprecated**, **Removed**, **Fixed**, and **Security**. For a major version, it lists the breaking changes first, with the steps to migrate.
- The [Cloudsmith changelog](https://cloudsmith.com/changelog) summarizes the notable changes in a release, and links to `CHANGELOG.md` for the full list.

The commitments in this policy refer to `CHANGELOG.md`.
