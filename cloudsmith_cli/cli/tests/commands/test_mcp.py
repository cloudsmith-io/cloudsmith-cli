import json
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import cloudsmith_api
import pytest

from ....cli.commands.mcp import (
    _atomic_write_json,
    _configure_claude_code,
    _get_server_config,
    _safe_update_json,
    configure_client,
    detect_available_clients,
    list_groups,
    list_tools,
)
from ....core.mcp.data import OpenAPITool
from ....core.mcp.server import DynamicMCPServer


class TestMCPListToolsCommand:
    def test_list_tools_command_basic(self, runner):
        """Test that list_tools command returns available tools."""
        # Mock tools data
        mock_tools = {
            "repos_list": OpenAPITool(
                name="repos_list",
                description="List repositories",
                method="GET",
                path="/repos/",
                parameters={"type": "object", "properties": {}, "required": []},
                base_url="https://api.cloudsmith.io",
                query_filter=None,
                is_destructive=False,
                is_read_only=True,
            ),
            "packages_list": OpenAPITool(
                name="packages_list",
                description="List packages",
                method="GET",
                path="/packages/",
                parameters={"type": "object", "properties": {}, "required": []},
                base_url="https://api.cloudsmith.io",
                query_filter=None,
                is_destructive=False,
                is_read_only=True,
            ),
        }

        with patch(
            "cloudsmith_cli.core.mcp.server.DynamicMCPServer.list_tools"
        ) as list_tools_mock:
            list_tools_mock.return_value = mock_tools
            result = runner.invoke(list_tools, catch_exceptions=False)

        assert result.exit_code == 0
        assert "repos_list" in result.output
        assert "packages_list" in result.output
        assert "List repositories" in result.output
        assert "List packages" in result.output
        list_tools_mock.assert_called_once()

    def test_list_tools_command_with_filtering(self, runner):
        """Test that list_tools command respects filtering configuration."""
        # Mock tools data - simulating filtered results
        mock_tools = {
            "repos_list": OpenAPITool(
                name="repos_list",
                description="List repositories",
                method="GET",
                path="/repos/",
                parameters={"type": "object", "properties": {}, "required": []},
                base_url="https://api.cloudsmith.io",
                query_filter=None,
                is_destructive=False,
                is_read_only=True,
            ),
        }

        with patch(
            "cloudsmith_cli.core.mcp.server.DynamicMCPServer.list_tools"
        ) as list_tools_mock:
            list_tools_mock.return_value = mock_tools
            result = runner.invoke(list_tools, catch_exceptions=False)

        assert result.exit_code == 0
        assert "repos_list" in result.output
        # Verify that filtered tools are not in the output
        assert "packages_list" not in result.output
        list_tools_mock.assert_called_once()

    def test_list_tools_command_json_output(self, runner):
        """Test that list_tools command can output JSON format."""
        mock_tools = {
            "repos_list": OpenAPITool(
                name="repos_list",
                description="List repositories",
                method="GET",
                path="/repos/",
                parameters={"type": "object", "properties": {}, "required": []},
                base_url="https://api.cloudsmith.io",
                query_filter=None,
                is_destructive=False,
                is_read_only=True,
            ),
        }

        with patch(
            "cloudsmith_cli.core.mcp.server.DynamicMCPServer.list_tools"
        ) as list_tools_mock:
            list_tools_mock.return_value = mock_tools
            result = runner.invoke(
                list_tools, ["--output-format", "json"], catch_exceptions=False
            )

        assert result.exit_code == 0
        # JSON output should contain structured data
        assert '"name":' in result.output or '"name": "repos_list"' in result.output
        list_tools_mock.assert_called_once()

    def test_list_tools_command_empty(self, runner):
        """Test that list_tools command handles empty tool list."""
        mock_tools = {}

        with patch(
            "cloudsmith_cli.core.mcp.server.DynamicMCPServer.list_tools"
        ) as list_tools_mock:
            list_tools_mock.return_value = mock_tools
            result = runner.invoke(list_tools, catch_exceptions=False)

        assert result.exit_code == 0
        assert "0 tools visible" in result.output
        list_tools_mock.assert_called_once()


class TestMCPListGroupsCommand:
    def test_list_groups_command_basic(self, runner):
        """Test that list_groups command returns available tool groups."""
        # Mock groups data
        mock_groups = {
            "repos": ["repos_list", "repos_create", "repos_delete"],
            "packages": ["packages_list", "packages_read", "packages_delete"],
            "orgs": ["orgs_list", "orgs_read"],
        }

        with patch(
            "cloudsmith_cli.core.mcp.server.DynamicMCPServer.list_groups"
        ) as list_groups_mock:
            list_groups_mock.return_value = mock_groups
            result = runner.invoke(list_groups, catch_exceptions=False)

        assert result.exit_code == 0
        assert "repos" in result.output
        assert "packages" in result.output
        assert "orgs" in result.output
        # Check tool counts are displayed
        assert "3" in result.output  # repos has 3 tools
        assert "2" in result.output  # orgs has 2 tools
        list_groups_mock.assert_called_once()

    def test_list_groups_command_with_filtering(self, runner):
        """Test that list_groups command respects filtering configuration."""
        # Mock groups data - simulating filtered results with only repos group
        mock_groups = {
            "repos": ["repos_list", "repos_create"],
        }

        with patch(
            "cloudsmith_cli.core.mcp.server.DynamicMCPServer.list_groups"
        ) as list_groups_mock:
            list_groups_mock.return_value = mock_groups
            result = runner.invoke(list_groups, catch_exceptions=False)

        assert result.exit_code == 0
        assert "repos" in result.output
        # Verify that filtered groups are not in the output
        assert "packages" not in result.output
        assert "orgs" not in result.output
        list_groups_mock.assert_called_once()

    def test_list_groups_command_json_output(self, runner):
        """Test that list_groups command can output JSON format."""
        mock_groups = {
            "repos": ["repos_list", "repos_create"],
            "packages": ["packages_list"],
        }

        with patch(
            "cloudsmith_cli.core.mcp.server.DynamicMCPServer.list_groups"
        ) as list_groups_mock:
            list_groups_mock.return_value = mock_groups
            result = runner.invoke(
                list_groups, ["--output-format", "json"], catch_exceptions=False
            )

        assert result.exit_code == 0
        # JSON output should contain structured data
        assert '"name":' in result.output or '"name": "repos"' in result.output
        assert '"tools":' in result.output
        list_groups_mock.assert_called_once()

    def test_list_groups_command_empty(self, runner):
        """Test that list_groups command handles empty group list."""
        mock_groups = {}

        with patch(
            "cloudsmith_cli.core.mcp.server.DynamicMCPServer.list_groups"
        ) as list_groups_mock:
            list_groups_mock.return_value = mock_groups
            result = runner.invoke(list_groups, catch_exceptions=False)

        assert result.exit_code == 0
        assert "0 groups visible" in result.output
        list_groups_mock.assert_called_once()

    def test_list_groups_command_with_many_tools(self, runner):
        """Test that list_groups command shows sample tools for groups with many tools."""
        # Mock a group with more than 3 tools to test the "... (+N more)" feature
        mock_groups = {
            "repos": [
                "repos_list",
                "repos_create",
                "repos_read",
                "repos_update",
                "repos_delete",
            ],
        }

        with patch(
            "cloudsmith_cli.core.mcp.server.DynamicMCPServer.list_groups"
        ) as list_groups_mock:
            list_groups_mock.return_value = mock_groups
            result = runner.invoke(list_groups, catch_exceptions=False)

        assert result.exit_code == 0
        assert "repos" in result.output
        assert "5" in result.output  # Total count of tools
        # Should show "... (+2 more)" since it only displays first 3
        assert "+2 more" in result.output
        list_groups_mock.assert_called_once()


class TestMCPServerDynamicToolGeneration:
    def test_server_generates_tools_from_openapi_spec(self):
        """Test that MCP server dynamically creates tools from OpenAPI spec."""
        # Create a minimal OpenAPI spec
        mock_openapi_spec = {
            "paths": {
                "/repos/": {
                    "get": {
                        "operationId": "repos_list",
                        "summary": "List all repositories",
                        "parameters": [
                            {
                                "name": "page",
                                "in": "query",
                                "type": "integer",
                                "description": "Page number",
                            }
                        ],
                    }
                },
                "/repos/{owner}/{identifier}/": {
                    "parameters": [
                        {
                            "name": "owner",
                            "in": "path",
                            "required": True,
                            "type": "string",
                        },
                        {
                            "name": "identifier",
                            "in": "path",
                            "required": True,
                            "type": "string",
                        },
                    ],
                    "get": {
                        "operationId": "repos_read",
                        "summary": "Get a specific repository",
                    },
                    "delete": {
                        "operationId": "repos_delete",
                        "summary": "Delete a repository",
                    },
                },
            }
        }

        # Create API config
        api_config = cloudsmith_api.Configuration()
        api_config.host = "https://api.cloudsmith.io"
        api_config.api_key = {"X-Api-Key": "test-key"}

        # Create MCP server instance
        server = DynamicMCPServer(api_config=api_config, force_all_tools=True)

        # Mock the spec loading directly
        server.spec = mock_openapi_spec

        # Call the synchronous tool generation method
        import asyncio

        asyncio.run(
            server._generate_tools_from_spec()  # pylint: disable=protected-access
        )

        # Verify tools were created
        assert len(server.tools) == 3
        assert "repos_list" in server.tools
        assert "repos_read" in server.tools
        assert "repos_delete" in server.tools

        # Verify tool details
        repos_list_tool = server.tools["repos_list"]
        assert repos_list_tool.name == "repos_list"
        assert repos_list_tool.description == "List all repositories"
        assert repos_list_tool.method == "GET"
        assert repos_list_tool.path == "/repos/"
        assert repos_list_tool.is_read_only is True
        assert repos_list_tool.is_destructive is False

        # Verify delete tool is marked as destructive
        repos_delete_tool = server.tools["repos_delete"]
        assert repos_delete_tool.is_destructive is True
        assert repos_delete_tool.is_read_only is False

    def test_server_respects_tool_filtering(self):
        """Test that MCP server filters tools based on configuration."""
        # Create a simple OpenAPI spec
        mock_openapi_spec = {
            "paths": {
                "/repos/": {
                    "get": {
                        "operationId": "repos_list",
                        "summary": "List repositories",
                    }
                },
                "/packages/": {
                    "get": {
                        "operationId": "packages_list",
                        "summary": "List packages",
                    }
                },
            }
        }

        api_config = cloudsmith_api.Configuration()
        api_config.host = "https://api.cloudsmith.io"
        api_config.api_key = {"X-Api-Key": "test-key"}

        # Create server with filtering - only allow repos group
        server = DynamicMCPServer(api_config=api_config, allowed_tool_groups=["repos"])

        # Mock the spec loading directly
        server.spec = mock_openapi_spec

        # Call the tool generation method
        import asyncio

        asyncio.run(
            server._generate_tools_from_spec()  # pylint: disable=protected-access
        )

        # Verify only repos tools were created
        assert len(server.tools) == 1
        assert "repos_list" in server.tools
        assert "packages_list" not in server.tools


SERVER_CONFIG = {"command": "cloudsmith", "args": ["mcp", "start"]}


class TestMCPServerConfig:
    def test_frozen_executable_runs_mcp_directly(self):
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "executable", "/opt/cloudsmith/cloudsmith"),
        ):
            assert _get_server_config("staging") == {
                "command": "/opt/cloudsmith/cloudsmith",
                "args": ["-P", "staging", "mcp", "start"],
            }


class TestMCPConfigureClaudeCode:
    def test_user_scope_merges_into_existing_claude_json(self, tmp_path):
        claude_json = tmp_path / ".claude.json"
        existing = {
            "numStartups": 42,
            "mcpServers": {"other": {"command": "other-mcp"}},
            "projects": {"/some/path": {"lastSessionId": "abc"}},
        }
        claude_json.write_text(json.dumps(existing, indent=2))

        with patch("cloudsmith_cli.cli.commands.mcp.Path.home", return_value=tmp_path):
            assert _configure_claude_code("cloudsmith", SERVER_CONFIG, is_global=True)

        result = json.loads(claude_json.read_text())
        assert result["mcpServers"]["other"] == {"command": "other-mcp"}
        assert result["mcpServers"]["cloudsmith"] == SERVER_CONFIG
        assert result["numStartups"] == 42
        assert result["projects"] == existing["projects"]

    def test_user_scope_errors_when_claude_json_missing(self, tmp_path):
        with patch("cloudsmith_cli.cli.commands.mcp.Path.home", return_value=tmp_path):
            with pytest.raises(ValueError, match="Launch Claude Code at least once"):
                _configure_claude_code("cloudsmith", SERVER_CONFIG, is_global=True)

    def test_project_scope_writes_local_mcp_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert _configure_claude_code("cloudsmith", SERVER_CONFIG, is_global=False)

        local = tmp_path / ".mcp.json"
        assert local.exists()
        assert json.loads(local.read_text()) == {
            "mcpServers": {"cloudsmith": SERVER_CONFIG}
        }

    def test_project_scope_merges_into_existing_mcp_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        existing = {"mcpServers": {"other": {"command": "other-mcp"}}}
        (tmp_path / ".mcp.json").write_text(json.dumps(existing))

        _configure_claude_code("cloudsmith", SERVER_CONFIG, is_global=False)

        result = json.loads((tmp_path / ".mcp.json").read_text())
        assert result["mcpServers"]["other"] == {"command": "other-mcp"}
        assert result["mcpServers"]["cloudsmith"] == SERVER_CONFIG

    def test_configure_client_routes_claude_code_with_profile(self, tmp_path):
        (tmp_path / ".claude.json").write_text("{}")
        with patch("cloudsmith_cli.cli.commands.mcp.Path.home", return_value=tmp_path):
            configure_client(
                "claude-code", SERVER_CONFIG, is_global=True, profile="staging"
            )

        result = json.loads((tmp_path / ".claude.json").read_text())
        assert "cloudsmith-staging" in result["mcpServers"]

    def test_detect_available_clients_respects_claude_json_presence(self, tmp_path):
        # Real get_config_path for claude-code (resolves under the patched
        # home); None for everything else so this host's real configs don't
        # leak into the result.
        import cloudsmith_cli.cli.commands.mcp as mcp_module

        real_get_config_path = mcp_module.get_config_path

        def selective(client, is_global=True):
            if client == "claude-code":
                return real_get_config_path(client, is_global=is_global)
            return None

        with (
            patch("cloudsmith_cli.cli.commands.mcp.Path.home", return_value=tmp_path),
            patch(
                "cloudsmith_cli.cli.commands.mcp.get_config_path", side_effect=selective
            ),
        ):
            assert "claude-code" not in detect_available_clients()

            (tmp_path / ".claude.json").write_text("{}")
            assert "claude-code" in detect_available_clients()


class TestSafeWriteHelpers:
    def test_atomic_write_preserves_existing_file_mode(self, tmp_path):
        target = tmp_path / "config.json"
        target.write_text("{}")
        os.chmod(target, 0o600)

        _atomic_write_json(target, {"k": "v"})

        assert json.loads(target.read_text()) == {"k": "v"}
        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    def test_atomic_write_creates_parent_directory(self, tmp_path):
        target = tmp_path / "nested" / "deeper" / "config.json"
        _atomic_write_json(target, {"k": "v"})
        assert json.loads(target.read_text()) == {"k": "v"}

    def test_atomic_write_cleans_up_tempfile_on_failure(self, tmp_path):
        target = tmp_path / "config.json"
        with patch(
            "cloudsmith_cli.cli.commands.mcp.os.replace",
            side_effect=OSError("boom"),
        ):
            with pytest.raises(OSError, match="boom"):
                _atomic_write_json(target, {"k": "v"})

        leftovers = [
            p for p in tmp_path.iterdir() if p.name.startswith(".config.json.")
        ]
        assert leftovers == []

    def test_safe_update_creates_file_when_missing(self, tmp_path):
        target = tmp_path / "config.json"
        _safe_update_json(target, lambda c: c.setdefault("a", []).append(1))
        assert json.loads(target.read_text()) == {"a": [1]}

    def test_atomic_write_follows_symlinks(self, tmp_path):
        real = tmp_path / "real" / "config.json"
        real.parent.mkdir()
        real.write_text(json.dumps({"existing": True}))
        link = tmp_path / "config.json"
        link.symlink_to(real)

        _atomic_write_json(link, {"k": "v"})

        assert link.is_symlink()
        assert link.readlink() == real
        assert json.loads(real.read_text()) == {"k": "v"}

    def test_safe_update_retries_on_concurrent_write(self, tmp_path):
        target = tmp_path / "config.json"
        target.write_text(json.dumps({"counter": 0}))

        calls = {"n": 0}

        def mutate(config):
            config["counter"] = config.get("counter", 0) + 1
            if calls["n"] == 0:
                # Simulate a concurrent writer landing between our read and
                # our pre-write mtime check. Bumping mtime explicitly so the
                # change is visible even on filesystems with coarse mtime.
                target.write_text(json.dumps({"counter": 99}))
                before = target.stat()
                os.utime(
                    target, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000)
                )
            calls["n"] += 1

        _safe_update_json(target, mutate)

        # First attempt reads 0, racing writer lands 99, retry reads 99 and
        # increments to 100.
        assert json.loads(target.read_text())["counter"] == 100

    def test_safe_update_raises_after_max_retries(self, tmp_path):
        target = tmp_path / "config.json"
        target.write_text("{}")

        original_stat = Path.stat

        def always_racing(self, *args, **kwargs):
            result = original_stat(self, *args, **kwargs)
            if str(self) == str(target):
                # Bump the file on disk every time we observe it, so the
                # mtime check always fails.
                os.utime(target, ns=(result.st_atime_ns, result.st_mtime_ns + 1000))
            return result

        with patch.object(Path, "stat", always_racing):
            with pytest.raises(ValueError, match="another process keeps modifying"):
                _safe_update_json(target, lambda c: c, max_retries=2)

    def test_safe_update_raises_on_malformed_json(self, tmp_path):
        target = tmp_path / "config.json"
        target.write_text("{not valid json}")

        with pytest.raises(ValueError, match="Cannot parse config file"):
            _safe_update_json(target, lambda c: c)


class TestConfigureClientSafeWrite:
    """Other clients should now use the atomic safe-update path."""

    def test_writes_atomically_for_claude_desktop(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        with patch(
            "cloudsmith_cli.cli.commands.mcp.get_config_path",
            return_value=config_path,
        ):
            configure_client("claude", SERVER_CONFIG, is_global=True)

        assert json.loads(config_path.read_text()) == {
            "mcpServers": {"cloudsmith": SERVER_CONFIG}
        }

    def test_writes_vscode_key_for_vscode_client(self, tmp_path):
        config_path = tmp_path / "settings.json"
        config_path.write_text(json.dumps({"editor.fontSize": 14}))

        with patch(
            "cloudsmith_cli.cli.commands.mcp.get_config_path",
            return_value=config_path,
        ):
            configure_client("vscode", SERVER_CONFIG, is_global=True)

        result = json.loads(config_path.read_text())
        assert result["editor.fontSize"] == 14
        assert result["chat.mcp.servers"]["cloudsmith"] == SERVER_CONFIG
