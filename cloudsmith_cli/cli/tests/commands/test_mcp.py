from unittest.mock import patch

import cloudsmith_api

from ....cli.commands.mcp import list_groups, list_tools
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
