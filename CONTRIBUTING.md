# Contributing

Please refer to Cloudsmith's standard guide on [Open-Source Contributing](https://help.cloudsmith.io/docs/contributing).


## Contributor License Agreement

By making any contributions to Cloudsmith Ltd projects you agree to be bound by the terms of the Cloudsmith Ltd [Contributor License Agreement](https://help.cloudsmith.io/docs/contributor-license-agreement).


## Requirements

The standard requirements are python 3.7 and the ability to install PyPi packages (either system-wide or via virtualenv, of which the latter is preferred).

You can refer to the following requirements files to see what is required:

- Common/Runtime: [setup.py](./setup.py)
- Development: [requirements.txt](./requirements.txt)


## Coding Conventions

Please ensure code conforms to [PEP-8](https://www.python.org/dev/peps/pep-0008/) and [PEP-257](https://www.python.org/dev/peps/pep-0257/).


## Releasing

To make a new release for `cloudsmith-cli` follow the procedure for virtualenv setup then:

```
$ bumpversion <major|minor|revision>
```

A tag will automatically created along with the version bump commit.


## Need Help?

See the section for raising a question in the [Contributing Guide](https://help.cloudsmith.io/docs/contributing).
