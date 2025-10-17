"""Main command/entrypoint."""

import json
import os
import shutil
import sys
from pathlib import Path

import click

from ...core.mcp import server
from .. import command, decorators, utils
from .main import main


@main.group(cls=command.AliasGroup, name="mcp")
@decorators.common_cli_config_options
@decorators.common_api_auth_options
@decorators.initialise_api
@click.pass_context
def mcp_(ctx, opts):  # pylint: disable=unused-argument
    """
    Start the Cloudsmith MCP Server

    See the help for subcommands for more information on each.
    """


@mcp_.command(name="start")
@decorators.initialise_api
@decorators.initialise_mcp
@click.pass_context
def start(ctx, opts, mcp_server: server.DynamicMCPServer):
    """
    Start the MCP Server
    """
    mcp_server.run()


@mcp_.command(name="list_tools")
@decorators.initialise_api
@decorators.initialise_mcp
@click.pass_context
def list_tools(ctx, opts, mcp_server: server.DynamicMCPServer):
    """
    List available tools that will be exposed to the AI Client
    """
    click.echo("Getting list of tools ... ", nl=False, err=False)
    with utils.maybe_spinner(opts):
        tools = mcp_server.list_tools()

    print_tools(tools)


def print_tools(tool_list):
    """Print repositories as a table or output in another format."""

    headers = [
        "Name",
        "Description",
    ]

    rows = []
    for tool_name, tools_spec in tool_list.items():
        rows.append(
            [
                click.style(tool_name, fg="cyan"),
                click.style(tools_spec.description, fg="yellow"),
            ]
        )

    if tool_list:
        click.echo()
        utils.pretty_print_table(headers, rows)

    click.echo()

    num_results = len(tool_list)
    list_suffix = "tool%s visible" % ("s" if num_results != 1 else "")
    utils.pretty_print_list_info(num_results=num_results, suffix=list_suffix)


@mcp_.command(name="configure")
@click.option(
    "--client",
    type=click.Choice(["claude", "cursor", "vscode"], case_sensitive=False),
    help="MCP client to configure (claude, cursor, vscode). If not specified, will attempt to detect and configure all.",
)
@click.option(
    "--global/--local",
    "is_global",
    default=True,
    help="Configure globally (default) or in current project directory (local)",
)
@decorators.initialise_api
@click.pass_context
def configure(ctx, opts, client, is_global):  # pylint: disable=unused-argument
    """
    Configure the Cloudsmith MCP server for supported clients.

    This command automatically adds the Cloudsmith MCP server configuration
    to the specified client's configuration file. Supported clients are:
    - Claude Desktop
    - Cursor IDE
    - VS Code (GitHub Copilot)

    Examples:\n
        cloudsmith mcp configure --client claude\n
        cloudsmith mcp configure --client cursor --local\n
        cloudsmith mcp configure  # Auto-detect and configure all
    """
    # Determine the best command to run the MCP server
    server_config = _get_server_config()

    clients_to_configure = []
    if client:
        clients_to_configure = [client.lower()]
    else:
        # Auto-detect available clients
        clients_to_configure = detect_available_clients()

    if not clients_to_configure:
        click.echo(click.style("No supported MCP clients detected.", fg="yellow"))
        click.echo("\nSupported clients:")
        click.echo("  - Claude Desktop")
        click.echo("  - Cursor IDE")
        click.echo("  - VS Code")
        return

    success_count = 0
    for client_name in clients_to_configure:
        try:
            if configure_client(client_name, server_config, is_global):
                click.echo(
                    click.style(f"✓ Configured {client_name.title()}", fg="green")
                )
                success_count += 1
            else:
                click.echo(
                    click.style(
                        f"✗ Failed to configure {client_name.title()}", fg="red"
                    )
                )
        except Exception as e:
            click.echo(
                click.style(
                    f"✗ Error configuring {client_name.title()}: {str(e)}", fg="red"
                )
            )

    if success_count > 0:
        click.echo(
            click.style(
                f"\n✓ Successfully configured {success_count} client(s)", fg="green"
            )
        )
        click.echo(
            "\nNote: You may need to restart the client application for changes to take effect."
        )
    else:
        click.echo(click.style("\n✗ No clients were configured successfully", fg="red"))


def _get_server_config():
    """Determine the best command configuration to run the MCP server."""
    # Check if running in a virtual environment
    in_venv = hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )

    # In a venv, always use python -m to ensure we use the venv's packages
    if in_venv:
        return {
            "command": sys.executable,
            "args": ["-m", "cloudsmith_cli", "mcp", "start"],
        }

    # Otherwise, try to find cloudsmith in PATH, fall back to python -m
    cloudsmith_cmd = shutil.which("cloudsmith")
    if cloudsmith_cmd:
        return {"command": cloudsmith_cmd, "args": ["mcp", "start"]}

    return {"command": sys.executable, "args": ["-m", "cloudsmith_cli", "mcp", "start"]}


def detect_available_clients():
    """Detect which MCP clients are available on the system."""
    available = []

    # Check for Claude Desktop
    claude_config = get_config_path("claude", is_global=True)
    if claude_config and claude_config.parent.exists():
        available.append("claude")

    # Check for Cursor
    cursor_config = get_config_path("cursor", is_global=True)
    if cursor_config and cursor_config.parent.exists():
        available.append("cursor")

    # Check for VS Code
    vscode_config = get_config_path("vscode", is_global=True)
    if vscode_config and vscode_config.parent.exists():
        available.append("vscode")

    return available


def get_config_path(client_name, is_global=True):
    """Get the configuration file path for a given client."""
    home = Path.home()
    appdata = os.getenv("APPDATA", "")

    # Configuration paths by client, platform, and scope
    config_paths = {
        "claude": {
            "darwin": home
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json",
            "win32": Path(appdata) / "Claude" / "claude_desktop_config.json"
            if appdata
            else None,
            "linux": home / ".config" / "Claude" / "claude_desktop_config.json",
        },
        "cursor": {
            "global": home / ".cursor" / "mcp.json",
            "local": Path.cwd() / ".cursor" / "mcp.json",
        },
        "vscode": {
            "darwin": home
            / "Library"
            / "Application Support"
            / "Code"
            / "User"
            / "settings.json",
            "win32": Path(appdata) / "Code" / "User" / "settings.json"
            if appdata
            else None,
            "linux": home / ".config" / "Code" / "User" / "settings.json",
            "local": Path.cwd() / ".vscode" / "settings.json",
        },
    }

    client_config = config_paths.get(client_name, {})

    # For Cursor, use global/local scope instead of platform
    if client_name == "cursor":
        scope = "global" if is_global else "local"
        return client_config.get(scope)

    # For VS Code local config
    if client_name == "vscode" and not is_global:
        return client_config.get("local")

    # For platform-specific configs (Claude and VS Code global)
    platform = sys.platform if sys.platform in ("darwin", "win32") else "linux"
    return client_config.get(platform)


def configure_client(client_name, server_config, is_global=True):
    """Configure a specific MCP client with the Cloudsmith server."""
    config_path = get_config_path(client_name, is_global)

    if not config_path:
        return False

    # Ensure parent directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing config or create new one
    if config_path.exists():
        with open(config_path) as f:
            try:
                config = json.load(f)
            except json.JSONDecodeError:
                config = {}
    else:
        config = {}

    # Add Cloudsmith MCP server based on client format
    if client_name == "claude" or client_name == "cursor":
        if "mcpServers" not in config:
            config["mcpServers"] = {}
        config["mcpServers"]["cloudsmith"] = server_config

    elif client_name == "vscode":
        # VS Code uses a different format in settings.json
        if "chat.mcp.servers" not in config:
            config["chat.mcp.servers"] = {}
        config["chat.mcp.servers"]["cloudsmith"] = server_config

    # Write updated config
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    return True
