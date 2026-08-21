# Copyright 2026 Cloudsmith Ltd
"""
Cargo credential helper command.

Implements the Cargo credential helper protocol for Cloudsmith registries.

See: https://doc.rust-lang.org/cargo/reference/credential-provider-protocol.html
"""


import click


@click.command()
@click.option(
    "--cargo-plugin",
    is_flag=True,
    default=False,
    help="Run in Cargo credential provider plugin mode (JSON-line protocol).",
)
@click.argument("index_url", required=False, default=None)
def cargo(cargo_plugin, index_url):
    click.echo("cargo")
    pass
