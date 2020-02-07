# Cloudsmith Command Line Interface (CLI)

[![Latest Version @ Cloudsmith](https://api-prd.cloudsmith.io/badges/version/cloudsmith/cli/python/cloudsmith-cli/latest/xf=bdist_wheel;xn=cloudsmith-cli;xv=py2.py3/?render=true)](https://cloudsmith.io/~cloudsmith/repos/cli/packages/detail/python/cloudsmith-cli/latest/xf=bdist_wheel;xn=cloudsmith-cli;xv=py2.py3/)
[![Python Versions](https://img.shields.io/pypi/pyversions/cloudsmith-cli.svg)](https://pypi.python.org/pypi/cloudsmith-cli)
[![PyPI Version](https://img.shields.io/pypi/v/cloudsmith-cli.svg)](https://pypi.python.org/pypi/cloudsmith-cli)
[![CircleCI](https://circleci.com/gh/cloudsmith-io/cloudsmith-cli.svg?style=svg)](https://circleci.com/gh/cloudsmith-io/cloudsmith-cli)
[![Maintainability](https://api.codeclimate.com/v1/badges/c4ce2988b461d7b31cd5/maintainability)](https://codeclimate.com/github/cloudsmith-io/cloudsmith-cli/maintainability)
[![Test Coverage](https://api.codeclimate.com/v1/badges/c4ce2988b461d7b31cd5/test_coverage)](https://codeclimate.com/github/cloudsmith-io/cloudsmith-cli/test_coverage)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/ambv/black)


The [Cloudsmith](https://cloudsmith.io) Command Line Interface (CLI) is a Py2/Py3 text-based interface to the [API](https://api.cloudsmith.io). This allows users, machines and other services to access and integrate smoothly with Cloudsmith without requiring explicit plugins or tools. Be awesome. [Automate Everything](https://corp.cloudsmith.io/tao/).

The following (very out of date) GIF demonstrates a small slice of the CLI - [View the full video on YouTube](https://youtu.be/8nlstYU9J5M):

[![CLI Demonstration](https://user-images.githubusercontent.com/2248287/33522274-c88416be-d7e0-11e7-86ab-518c53d6bf61.gif)](https://youtu.be/8nlstYU9J5M)

You can also read our [blog article](https://blog.cloudsmith.io/2017/11/25/automation-as-simple-as-a-b-cli/) that introduced the first version of the CLI and the Cloudsmith RESTful API.


## Changelog

Please see the [changelog](https://github.com/cloudsmith-io/cloudsmith-cli/blob/master/CHANGELOG.md) for the list of changes by version. The current version is displayed in the PyPi badge at the top.


## Features

The CLI currently supports the following commands (and sub-commands):

- `check`:               Check rate limits and service status.
- `copy`|`cp`:           Copy a package to another repository.
- `delete`|`rm`:         Delete a package from a repository.
- `docs`:                Launch the help website in your browser.
- `entitlements`|`ents`: Manage the entitlements for a repository.
  - `create`|`new`:        Create a new entitlement in a repository.
  - `delete`|`rm`:         Delete an entitlement from a repository.
  - `list`|`ls`:           List entitlements for a repository.
  - `refresh`:             Refresh an entitlement in a repository.
  - `sync`:                Sync entitlements from another repository.
  - `update`|`set`:        Update (patch) a entitlement in a repository.
- `help`:                Display the delightful help message and exit.
- `list`|`ls`:           List distros, packages, repos and entitlements.
  - `distros`:             List available distributions.
  - `entitlements`:        List entitlements for a repository.
  - `packages`:            List packages for a repository.
  - `repos`:               List repositories for a namespace (owner).
- `login`|`token`:       Retrieve your API authentication token/key via login.
- `move`|`mv`:           Move (promote) a package to another repo.
- `push`|`upload`:       Push (upload) a new package to a repository.
  - `alpine`:              Push (upload) a new Alpine package upstream.
  - `cargo`:               Push (upload) a new Cargo package upstream.
  - `composer`:            Push (upload) a new Composer package upstream.
  - `cran`:                Push (upload) a new R/CRAN package upstream.
  - `deb`:                 Push (upload) a new Debian package upstream.
  - `docker`:              Push (upload) a new Docker image upstream.
  - `go`:                  Push (upload) a new Go module upstream.
  - `helm`:                Push (upload) a new Helm package upstream.
  - `luarocks`:            Push (upload) a new Lua module upstream.
  - `maven`:               Push (upload) a new Maven package upstream.
  - `npm`:                 Push (upload) a new Npm package upstream.
  - `nuget`:               Push (upload) a new NuGet package upstream.
  - `python`:              Push (upload) a new Python package upstream.
  - `raw`:                 Push (upload) a new Raw package upstream.
  - `rpm`:                 Push (upload) a new RedHat package upstream.
  - `ruby`:                Push (upload) a new Ruby package upstream.
  - `vagrant`:             Push (upload) a new Vagrant package upstream.
- `resync`:              Resynchronise a package in a repository.
- `status`:              Get the synchronisation status for a package.
- `whoami`:              Retrieve your current authentication status.


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


## Examples

**Note:** All of the examples in this section are uploading to the **your-account** user and the **test** repository. Please replace these with your own user/org and repository names.

### Upload an Alpine Package

Assuming you have a package filename **libjq-1.0.3.apk**, representing **libjq 1.0.3**, for the **Alpine v3.8** distribution (which has a cloudsmith identifier of **alpine/v3.8**):

```
cloudsmith push alpine your-account/your-repo/alpine/v3.8 libjq-1.0.3.apk
```

### Upload a Cargo Package

Assuming you have a package filename **your-package.crate**, representing **your-package**, for **Cargo**:

```
cloudsmith push cargo your-account/your-repo your-package.crate
```

### Upload a (Objective-C or Swift) CocoaPods package

Assuming you have a package filename **your-package.tar.gz**, representing **your-package**, for **(Objective-C or Swift) CocoaPods**:

```
cloudsmith push cocoapods your-account/your-repo your-package.tar.gz
```

### Upload a Composer Package

Assuming you have a package filename **your-package.phar**, representing **your-package**, for **Composer**:

```
cloudsmith push composer your-account/your-repo your-package.phar
```

### Upload an R/CRAN Package

Assuming you have a package filename **your-package_0.1.0.tar.gz**, representing **your-package 0.1.0**, for **R/CRAN**:

```
cloudsmith push cran your-account/your-repo your-package_0.1.0.tar.gz
```

### Upload a (Google) Dart Package

Assuming you have a package filename **your-package-1.0.0.tgz**, representing **your-package 1.0.0**, for **(Google) Dart**:

```
cloudsmith push dart your-account/your-repo your-package-1.0.0.tgz
```

### Upload a Debian Package

Assuming you have a package filename **libxml2-2.9.4-2.x86_64.deb**, representing **libxml 2.9.4**, for the **Ubuntu 16.04** distribution (which has a cloudsmith identifier of **ubuntu/xenial**):

```
cloudsmith push deb your-account/your-repo/ubuntu/xenial libxml2-2.9.4-2.x86_64.deb
```

### Upload a Docker Image

Assuming you have a package filename **your-image.docker**, representing **your-image**, for **Docker**:

```
cloudsmith push docker your-account/your-repo your-image.docker
```

### Upload a Go Module

Assuming you have a package filename **v1.0.0.zip**, representing **your-package** **1.0.0**, for **Go**:

```
cloudsmith push go your-account/your-repo v1.0.0.zip
```

### Upload a Helm Package

Assuming you have a package filename **your-package-1.0.0.tgz**, representing **your-package** **1.0.0**, for **Helm**:

```
cloudsmith push helm your-account/your-repo your-package-1.0.0.tgz
```

### Upload a LuaRocks Module

Assuming you have a package filename **your-module-1.0.0-1.src.rock**, representing **your-module**, for **LuaRocks**:

```
cloudsmith push luarocks your-account/your-repo your-module-1.0.0-1.src.rock
```

### Upload a Maven Package

Assuming you have a package filename **validation-api-1.0.0.GA.jar**, representing **validation-api 1.0.0**, for **Maven/Java**:

```
cloudsmith push maven your-account/your-repo validation-api-1.0.0.GA.jar --pom-file=validation-api-1.0.0.GA.pom
```

### Upload a Npm Package

Assuming you have a package filename **cloudsmithjs-1.0.0.tgz**, representing **cloudsmith-js 1.0.0*, for **Npm**:

```
cloudsmith push npm your-account/your-repo cloudsmithjs-1.0.0.tgz
```

### Upload a Npm Package

Assuming you have a package filename **your-package-1.0.0.nupkg**, representing **your-package 1.0.0*, for **NuGet**:

```
cloudsmith push nuget your-account/your-repo your-package-1.0.0.nupkg
```

### Upload a Python Package

Assuming you have a package filename **boto3-1.4.4.py2.p3-none-any.whl**, representing **boto3 1.4.4**, for **Python 2/3**:

```
cloudsmith push python your-account/your-repo boto3-1.4.4.py2.p3-none-any.whl
```

### Upload a Raw Package

Assuming you have a package filename **assets.zip**, representing **packaged assets**:

```
cloudsmith push raw your-account/your-repo assets.zip
```

### Upload a RedHat Package

Assuming you have a package filename **libxml2-2.9.4-2.el5.x86_64.rpm**, representing **libxml 2.9.4**, for the **RedHat Enterprise 5.0** distribution (which has a cloudsmith identifier of **el/5**):

```
cloudsmith push rpm your-account/your-repo/el/5 libxml2-2.9.4-2.el5.x86_64.rpm
```

### Upload a Ruby Package

Assuming you have a package filename **safe_yaml-1.0.4.gem**, representing **safe_yaml 1.0.4**, for **Ruby 2.3+**:

```
cloudsmith push ruby your-account/your-repo safe_yaml-1.0.4.gem
```

### Upload a Vagrant Package

Assuming you have a package filename **awesome.box**, representing a Vagrant image for the **Awesome OS** (fictional, probably):

```
cloudsmith push vagrant your-account/your-repo awesome.box --provider virtualbox
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
