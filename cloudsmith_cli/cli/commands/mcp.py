"""Main command/entrypoint."""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import click
import json5

from ...core.mcp import server
from ...core.mcp.data import OpenAPITool
from .. import command, decorators, utils
from .main import main

SUPPORTED_MCP_CLIENTS = {
    "claude": "Claude Desktop",
    "claude-code": "Claude Code",
    "cursor": "Cursor IDE",
    "vscode": "VS Code",
    "gemini-cli": "Gemini CLI",
}


@main.group(cls=command.AliasGroup, name="mcp")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
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
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@decorators.initialise_mcp
@click.pass_context
def list_tools(ctx, opts, mcp_server: server.DynamicMCPServer):
    """
    List available tools that will be exposed to the MCP Client
    """
    use_stderr = utils.should_use_stderr(opts)

    if not use_stderr:
        click.echo("Getting list of tools ... ", nl=False, err=use_stderr)

    with utils.maybe_spinner(opts):
        tools = mcp_server.list_tools()

    if not use_stderr:
        click.secho("OK", fg="green", err=use_stderr)

    tools_data = [
        {"name": name, "description": spec.description} for name, spec in tools.items()
    ]

    if utils.maybe_print_as_json(opts, tools_data):
        return

    print_tools(tools)


@mcp_.command(name="list_groups")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@decorators.initialise_api
@decorators.initialise_mcp
@click.pass_context
def list_groups(ctx, opts, mcp_server: server.DynamicMCPServer):
    """
    List available tool groups and the tools they contain
    """
    use_stderr = utils.should_use_stderr(opts)

    if not use_stderr:
        click.echo("Getting list of tool groups ... ", nl=False, err=use_stderr)

    with utils.maybe_spinner(opts):
        groups = mcp_server.list_groups()

    if not use_stderr:
        click.secho("OK", fg="green", err=use_stderr)

    groups_data = [{"name": name, "tools": tools} for name, tools in groups.items()]

    if utils.maybe_print_as_json(opts, groups_data):
        return

    print_groups(groups)


def print_tools(tool_list: dict[str, OpenAPITool]):
    """Print tools as a table or output in another format."""

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


def print_groups(group_list: dict[str, list[str]]):
    """Print tool groups as a table or output in another format."""

    headers = [
        "Group Name",
        "Tool Count",
        "Sample Tools",
    ]

    rows = []
    for group_name, tools in group_list.items():
        # Show first 3 tools as samples
        sample_tools = ", ".join(tools[:3])
        if len(tools) > 3:
            sample_tools += f", ... (+{len(tools) - 3} more)"

        rows.append(
            [
                click.style(group_name, fg="cyan"),
                click.style(str(len(tools)), fg="yellow"),
                click.style(sample_tools, fg="white"),
            ]
        )

    if group_list:
        click.echo()
        utils.pretty_print_table(headers, rows)

    click.echo()

    num_results = len(group_list)
    list_suffix = "group%s visible" % ("s" if num_results != 1 else "")
    utils.pretty_print_list_info(num_results=num_results, suffix=list_suffix)


@mcp_.command(name="configure")
@decorators.common_cli_config_options
@decorators.common_cli_output_options
@decorators.common_api_auth_options
@click.option(
    "--client",
    type=click.Choice(list(SUPPORTED_MCP_CLIENTS.keys()), case_sensitive=False),
    help=f"MCP client to configure ({', '.join(SUPPORTED_MCP_CLIENTS.keys())}). If not specified, will attempt to detect and configure all.",
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
    - Claude Code
    - Cursor IDE
    - VS Code (GitHub Copilot)
    - Gemini CLI

    For Claude Code, --global edits ~/.claude.json (user scope) and
    --local writes ./.mcp.json (project scope, intended to be committed).

    Examples:\n
        cloudsmith mcp configure --client claude\n
        cloudsmith mcp configure --client claude-code\n
        cloudsmith mcp configure --client cursor --local\n
        cloudsmith mcp configure --client gemini-cli\n
        cloudsmith mcp configure  # Auto-detect and configure all
    """

    use_stderr = utils.should_use_stderr(opts)

    # Get the profile from context
    profile = ctx.meta.get("profile")

    # Determine the best command to run the MCP server
    server_config = _get_server_config(profile)

    clients_to_configure = []
    if client:
        clients_to_configure = [client.lower()]
    else:
        # Auto-detect available clients
        clients_to_configure = detect_available_clients()

    if not clients_to_configure:
        if not use_stderr:
            click.echo(click.style("No supported MCP clients detected.", fg="yellow"))
            click.echo("\nSupported clients:")
            for display_name in SUPPORTED_MCP_CLIENTS.values():
                click.echo(f"  - {display_name}")

        utils.maybe_print_as_json(opts, [])
        return

    results = []
    success_count = 0
    for client_name in clients_to_configure:
        try:
            if configure_client(client_name, server_config, is_global, profile):
                if not use_stderr:
                    click.echo(
                        click.style(f"✓ Configured {client_name.title()}", fg="green")
                    )
                success_count += 1
                results.append({"client": client_name, "success": True})
            else:
                if not use_stderr:
                    click.echo(
                        click.style(
                            f"✗ Failed to configure {client_name.title()}", fg="red"
                        )
                    )
                results.append(
                    {
                        "client": client_name,
                        "success": False,
                        "error": "Configuration failed",
                    }
                )
        except (OSError, ValueError) as e:
            if not use_stderr:
                click.echo(
                    click.style(
                        f"✗ Error configuring {client_name.title()}: {str(e)}", fg="red"
                    )
                )
            results.append({"client": client_name, "success": False, "error": str(e)})

    if utils.maybe_print_as_json(opts, results):
        return

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


def _get_server_config(profile=None):
    """Determine the first available command configuration to run the MCP server."""
    # Check if running in a virtual environment
    in_venv = hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )

    # Build the base args
    base_args = []
    if profile:
        base_args.extend(["-P", profile])

    # In a venv, always use python -m to ensure we use the venv's packages
    if in_venv:
        return {
            "command": sys.executable,
            "args": ["-m", "cloudsmith_cli"] + base_args + ["mcp", "start"],
        }

    # Otherwise, try to find cloudsmith in PATH, fall back to python -m
    cloudsmith_cmd = shutil.which("cloudsmith")
    if cloudsmith_cmd:
        return {"command": cloudsmith_cmd, "args": base_args + ["mcp", "start"]}

    return {
        "command": sys.executable,
        "args": ["-m", "cloudsmith_cli"] + base_args + ["mcp", "start"],
    }


def detect_available_clients():
    """Detect which MCP clients are available on the system."""
    available = []
    home = Path.home()

    for client in SUPPORTED_MCP_CLIENTS:
        config = get_config_path(client, is_global=True)
        if not config:
            continue
        # Parent-dir existence is the usual "app installed" marker, but a
        # parent of $HOME (Claude Code) tells us nothing; require the file
        # itself in that case.
        if config.exists() or (config.parent.exists() and config.parent != home):
            available.append(client)

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
            "win32": (
                Path(appdata) / "Claude" / "claude_desktop_config.json"
                if appdata
                else None
            ),
            "linux": home / ".config" / "Claude" / "claude_desktop_config.json",
        },
        "claude-code": {
            "global": home / ".claude.json",
            "local": Path.cwd() / ".mcp.json",
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
            "win32": (
                Path(appdata) / "Code" / "User" / "settings.json" if appdata else None
            ),
            "linux": home / ".config" / "Code" / "User" / "settings.json",
            "local": Path.cwd() / ".vscode" / "settings.json",
        },
        "gemini-cli": {
            "global": home / ".gemini" / "settings.json",
            "local": Path.cwd() / ".gemini" / "settings.json",
        },
    }

    client_config = config_paths.get(client_name, {})

    # For scope-keyed (not platform-keyed) clients, look up by global/local.
    if client_name in ("claude-code", "cursor", "gemini-cli"):
        scope = "global" if is_global else "local"
        return client_config.get(scope)

    # For VS Code local config
    if client_name == "vscode" and not is_global:
        return client_config.get("local")

    # For platform-specific configs (Claude and VS Code global)
    platform = sys.platform if sys.platform in ("darwin", "win32") else "linux"
    return client_config.get(platform)


def configure_client(client_name, server_config, is_global=True, profile=None):
    """Configure a specific MCP client with the Cloudsmith server."""
    server_name = f"cloudsmith-{profile}" if profile else "cloudsmith"

    if client_name == "claude-code":
        return _configure_claude_code(server_name, server_config, is_global)

    config_path = get_config_path(client_name, is_global)
    if not config_path:
        return False

    key = "chat.mcp.servers" if client_name == "vscode" else "mcpServers"

    def mutate(config):
        config.setdefault(key, {})[server_name] = server_config

    _safe_update_json(config_path, mutate)
    return True


def _configure_claude_code(server_name, server_config, is_global):
    """Register the Cloudsmith MCP server with Claude Code.

    Why direct edit (not `claude mcp add-json`): avoids requiring the Claude
    Code CLI on PATH. _safe_update_json handles the race with a running
    Claude Code session writing to ~/.claude.json.
    """
    path = get_config_path("claude-code", is_global=is_global)
    if is_global and not path.exists():
        raise ValueError(
            f"{path} not found. Launch Claude Code at least once, "
            "then re-run this command."
        )

    def mutate(config):
        config.setdefault("mcpServers", {})[server_name] = server_config

    _safe_update_json(path, mutate)
    return True


def _atomic_write_json(path: Path, data) -> None:
    """Write JSON to ``path`` atomically via a tempfile + os.replace.

    Preserves the destination's existing file mode when present.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = path.stat().st_mode & 0o777 if path.exists() else None

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    tmp_path = Path(tmp.name)
    try:
        with tmp as f:
            # json5 is used for reading; we write standard JSON, which drops
            # any user comments (currently only relevant for VS Code's JSONC).
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        if existing_mode is not None:
            os.chmod(tmp_path, existing_mode)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _safe_update_json(path: Path, mutate, *, max_retries: int = 3) -> None:
    """Read JSON at ``path``, apply ``mutate(dict)``, atomic-write back.

    Retries on mtime change between read and replace -- guards against a
    concurrent writer (e.g. a running Claude Code session updating
    ~/.claude.json, or VS Code editing settings.json) clobbering deltas.
    """
    for _ in range(max_retries):
        if path.exists():
            mtime_before = path.stat().st_mtime_ns
            with open(path) as f:
                content = f.read()
            try:
                config = json5.loads(content)
            except (json.JSONDecodeError, ValueError) as e:
                raise ValueError(
                    f"Cannot parse config file '{path}': {e}. "
                    "Please fix the JSON syntax or remove the file to "
                    "create a new one."
                ) from e
        else:
            mtime_before = None
            config = {}

        mutate(config)

        if mtime_before is not None and path.stat().st_mtime_ns != mtime_before:
            continue

        _atomic_write_json(path, config)
        return

    raise ValueError(
        f"Could not safely update {path}: another process keeps modifying "
        "it. Close the consuming app and retry."
    )
