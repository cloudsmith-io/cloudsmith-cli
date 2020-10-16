# Cloudsmith Command Line Interface (CLI)

[![Latest Version @ Cloudsmith](https://api-prd.cloudsmith.io/badges/version/cloudsmith/cli/python/cloudsmith-cli/latest/xf=bdist_wheel;xn=cloudsmith-cli;xv=py2.py3/?render=true)](https://cloudsmith.io/~cloudsmith/repos/cli/packages/detail/python/cloudsmith-cli/latest/xf=bdist_wheel;xn=cloudsmith-cli;xv=py2.py3/)
[![Python Versions](https://img.shields.io/pypi/pyversions/cloudsmith-cli.svg)](https://pypi.python.org/pypi/cloudsmith-cli)
[![PyPI Version](https://img.shields.io/pypi/v/cloudsmith-cli.svg)](https://pypi.python.org/pypi/cloudsmith-cli)
[![CircleCI](https://circleci.com/gh/cloudsmith-io/cloudsmith-cli.svg?style=svg)](https://circleci.com/gh/cloudsmith-io/cloudsmith-cli)
[![Maintainability](https://api.codeclimate.com/v1/badges/c4ce2988b461d7b31cd5/maintainability)](https://codeclimate.com/github/cloudsmith-io/cloudsmith-cli/maintainability)
[![Test Coverage](https://api.codeclimate.com/v1/badges/c4ce2988b461d7b31cd5/test_coverage)](https://codeclimate.com/github/cloudsmith-io/cloudsmith-cli/test_coverage)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/ambv/black)


The [Cloudsmith](https://cloudsmith.io) Command Line Interface (CLI) is a Py2/Py3 text-based interface to the [API](https://api.cloudsmith.io). This allows users, machines and other services to access and integrate smoothly with Cloudsmith without requiring explicit plugins or tools. [Be awesome. Automate Everything](https://cloudsmith.com/company/the-tao-of-cloudsmith/).

The following asciinema video demonstrates some of the CLI commands:
[![asciicast](https://asciinema.org/a/DkNXQWQGBjWkfGPAkDAPNz7xe.svg)](https://asciinema.org/a/DkNXQWQGBjWkfGPAkDAPNz7xe)

We also have a [demo video on YouTube](https://youtu.be/R-g8ZhDwTKk):

You can also read our [blog article](https://blog.cloudsmith.io/2017/11/25/automation-as-simple-as-a-b-cli/) that introduced the first version of the CLI and the Cloudsmith RESTful API.


## Changelog

Please see the [changelog](https://github.com/cloudsmith-io/cloudsmith-cli/blob/master/CHANGELOG.md) for the list of changes by version. The current version is displayed in the PyPi badge at the top.


## Features

The CLI currently supports the following commands (and sub-commands):

- `check`:                Check rate limits and service status.
- `copy`|`cp`:            Copy a package to another repository.
- `delete`|`rm`:          Delete a package from a repository.
- `docs`:                 Launch the help website in your browser.
- `entitlements`|`ents`:  Manage the entitlements for a repository.
  - `create`|`new`:         Create a new entitlement in a repository.
  - `delete`|`rm`:          Delete an entitlement from a repository.
  - `list`|`ls`:            List entitlements for a repository.
  - `refresh`:              Refresh an entitlement in a repository.
  - `sync`:                 Sync entitlements from another repository.
  - `update`|`set`:         Update (patch) a entitlement in a repository.
- `help`:                 Display the delightful help message and exit.
- `list`|`ls`:            List distros, packages, repos and entitlements.
  - `distros`:              List available distributions.
  - `entitlements`:         List entitlements for a repository.
  - `packages`:             List packages for a repository. (Aliases `repos list`)
  - `repos`:                List repositories for a namespace (owner).
- `login`|`token`:        Retrieve your API authentication token/key via login.
- `metrics`:              Metrics and statistics for a repository.
  - `tokens`:               Retrieve bandwidth usage for entitlement tokens.
  - `packages`:             Retrieve package usage for repository.
- `move`|`mv`:            Move (promote) a package to another repo.
- `push`|`upload`:        Push (upload) a new package to a repository.
  - `alpine`:               Push (upload) a new Alpine package upstream.
  - `cargo`:                Push (upload) a new Cargo package upstream.
  - `composer`:             Push (upload) a new Composer package upstream.
  - `cocoapods`:            Push (upload) a new CocoaPods package upstream.
  - `conan`:                Push (upload) a new Conan (C++) package upstream.
  - `cran`:                 Push (upload) a new R/CRAN package upstream.
  - `deb`:                  Push (upload) a new Debian package upstream.
  - `docker`:               Push (upload) a new Docker image upstream.
  - `go`:                   Push (upload) a new Go module upstream.
  - `helm`:                 Push (upload) a new Helm package upstream.
  - `luarocks`:             Push (upload) a new Lua module upstream.
  - `maven`:                Push (upload) a new Maven package upstream.
  - `npm`:                  Push (upload) a new Npm package upstream.
  - `nuget`:                Push (upload) a new NuGet package upstream.
  - `python`:               Push (upload) a new Python package upstream.
  - `raw`:                  Push (upload) a new Raw package upstream.
  - `rpm`:                  Push (upload) a new RedHat package upstream.
  - `ruby`:                 Push (upload) a new Ruby package upstream.
  - `terraform`:            Push (upload) a new Terraform package upstream.
  - `vagrant`:              Push (upload) a new Vagrant package upstream.
- `quota`:                Quota limits and history for a organisation.
  - `limits`:               Display the Quota (bandwidth & storage usage/limits) for a specific organisation.
  - `history`:              Display the Quota History (upload, download, and storage usage/limits) for a specific organisation.
- `repositories`|`repos`: Manage repositories.
  - `create`|`new`:         Create a new repository in a namespace.
  - `get`|`list`|`ls`:      List repositories for a user, in a namespace or get details for a specific repository.
  - `update`:               Update a repository in a namespace.
  - `delete`|`rm`:          Delete a repository from a namespace.
- `resync`:               Resynchronise a package in a repository.
- `status`:               Get the synchronisation status for a package.
- `tags`:                 Manage the tags for a package in a repository.
  - `add`:                  Add tags to a package in a repository.
  - `clear`:                Clear all existing (non-immutable) tags from a package in a repository.
  - `list`|`ls`:            List tags for a package in a repository.
  - `remove`|`rm`:          Remove tags from a package in a repository.
  - `replace`:              Replace all existing (non-immutable) tags on a package in a repository.
- `whoami`:               Retrieve your current authentication status.


## Installation

You can install the latest CLI application from:

- [Official CLI Repository @ PyPi](https://pypi.python.org/pypi/cloudsmith-cli)
- [Official CLI Repository @ Cloudsmith](https://cloudsmith.io/~cloudsmith/repos/cli/packages/)

The simplest way is to use `pip`, such as:

```
pip install --upgrade cloudsmith-cli
```

Or you can get the latest pre-release version from Cloudsmith:

```
pip install --upgrade cloudsmith-cli --extra-index-url=https://dl.cloudsmith.io/public/cloudsmith/cli/python/index/
```

## Configuration

There are two configuration files used by the CLI:

- `config.ini`: For non-credentials configuration.
- `credentials.ini`: For credentials (authentication) configuration.

By default, the CLI will look for these in the following locations:

- The current working directory.
- A directory called `cloudsmith` in the OS-defined application directory. For example:
  - Linux:
    - `$HOME/.config/cloudsmith`
    - `$HOME/.cloudsmith`
  - Mac OS:
    - `$HOME/Library/Application Support/cloudsmith`
    - `$HOME/.cloudsmith`
  - Windows:
    - `C:\Users\<user>\AppData\Local\cloudsmith` (Win7+, not roaming)
    - `C:\Users\<user>\AppData\Roaming\cloudsmith` (Win7+, roaming)
    - `C:\Documents and Settings\<user>\Application Data\cloudsmith` (WinXP, not roaming)
    - `C:\Documents and Settings\<user>\Local Settings\Application Data\cloudsmith` (WinXP, roaming)

Both configuration files use the simple INI format, such as:

```
[default]
api_key=1234567890abcdef1234567890abcdef
```

### Non-Credentials (config.ini)

See the [default config](https://raw.githubusercontent.com/cloudsmith-io/cloudsmith-cli/master/cloudsmith_cli/data/config.ini) in GitHub:

You can specify the following configuration options:

- `api_host`: The API host to connect to.
- `api_proxy`: The API proxy to connect through.
- `api_ssl_verify`: Whether or not to use SSL verification for requests.
- `api_user_agent`: The user agent to use for requests.

### Credentials (credentials.ini)

See the [default config](https://raw.githubusercontent.com/cloudsmith-io/cloudsmith-cli/master/cloudsmith_cli/data/credentials.ini) in GitHub:

You can specify the following configuration options:

- `api_key`: The API key for authenticating with the API.


### Getting Your API Key

You'll need to provide authentication to Cloudsmith for any CLI actions that result in accessing private data or making changes to resources (such as pushing a new package to a repository)..

With the CLI this is simple to do. You can retrieve your API key using the `cloudsmith login` command:

```
cloudsmith login
Login: you@example.com
Password:
Repeat for confirmation:
```

*Note:* Please ensure you use your email for the 'Login' prompt and not your user slug/identifier.

The resulting output looks something like:

```
Retrieving API token for 'you@example.com' ... OK
Your API token is: 1234567890abcdef1234567890abcdef
```

Once you have your API key you can then put this into your `credentials.ini`, use it as an environment variable `export CLOUDSMITH_API_KEY=your_key_here` or pass it to the CLI using the `-k your_key_here` flag.

For convenience the CLI will ask you if you want to install the default configuration files, complete with your API key, if they don't already exist. Say 'y' or 'yes' to create the configuration files.

If the configuration files already exist, you'll have to manually put the API key into the configuration files, but the CLI will print out their locations.


## Uploading Packages

Although native uploads, i.e. those supported by the native ecosystem of a package format, are often preferred; it's easy to publish with the Cloudsmith CLI too!

For example, if you wanted to upload a Debian package, you can do it in one-step. Assuming you have a package filename **libxml2-2.9.4-2.x86_64.deb**, representing **libxml 2.9.4**, for the **Ubuntu 16.04** distribution (which has a cloudsmith identifier of **ubuntu/xenial**):

```
cloudsmith push deb your-account/your-repo/ubuntu/xenial libxml2-2.9.4-2.x86_64.deb
```

Want to know how to do it with another packaging format? Easy, just ask for help:

```
cloudsmith push rpm --help
```


## Contributing

Yes! Please do contribute, this is why we love open source.  Please see [CONTRIBUTING](https://github.com/cloudsmith-io/cloudsmith-cli/blob/master/CONTRIBUTING.md) for contribution guidelines when making code changes or raising issues for bug reports, ideas, discussions and/or questions (i.e. help required).


## License

Copyright 2018 Cloudsmith Ltd

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.

     http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.


## EOF

This quality product was brought to you by [Cloudsmith](https://cloudsmith.io) and the [fine folks who have contributed](https://github.com/cloudsmith-io/cloudsmith-cli/blob/master/CONTRIBUTORS.md).
