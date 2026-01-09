import asyncio
import copy
import inspect
import json
from typing import Any, Dict, List, Optional
from urllib import parse

import cloudsmith_api
import httpx
import toon_python as toon
from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.shared._httpx_utils import create_mcp_http_client

from .data import OpenAPITool

ALLOWED_METHODS = ["get", "post", "put", "delete", "patch"]

API_VERSIONS_TO_DISCOVER = {
    "v1": "swagger/?format=openapi",
    "v2": "openapi/?format=json",
}
TOOL_DELETE_SUFFIXES = ["delete", "destroy", "remove"]

TOOL_READ_ONLY_SUFFIXES = ["read", "list", "retrieve"]

# Common action suffixes in OpenAPI operation IDs
# These should not be considered as part of the resource group hierarchy
TOOL_ACTION_SUFFIXES = [
    "create",
    "read",
    "list",
    "update",
    "partial_update",
    "delete",
    "destroy",
    "retrieve",
    "remove",
]

DEFAULT_DISABLED_CATEGORIES = [
    "broadcasts",
    "rates",
    "packages_upload",
    "packages_validate",
    "user_token",
    "user_tokens",
    "webhooks",
    "status",
    "repos_ecdsa",
    "repos_geoip",
    "repos_gpg",
    "repos_rsa",
    "repos_x509",
    "repos_upstream",
    "orgs_openid",
    "orgs_saml",
    "orgs_invites",
    "files",
    "badges",
    "quota",
    "users_profile",
    "workspaces_policies",
    "storage_regions",
    "entitlements",
    "metrics_entitlements",
    "metrics_packages",
    "orgs_teams",
    "repo_retention",
]

SERVER_NAME = "Cloudsmith MCP Server"


class CustomFastMCP(FastMCP):
    """Custom FastMCP that overrides tool listing to clean up schemas to not overwhelm the LLM context"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def list_tools(self) -> list[types.Tool]:
        """Override to clean up tool schemas"""
        # Get the default tools from parent (returns list[MCPTool])
        default_tools = await super().list_tools()

        # Clean up each tool's schema
        cleaned_tools = []
        for tool in default_tools:
            # Create a new MCPTool with cleaned schema
            cleaned_tool = types.Tool(
                name=tool.name,
                description=tool.description,
                inputSchema=self._clean_schema(tool.inputSchema),
                annotations=tool.annotations,
            )
            cleaned_tools.append(cleaned_tool)

        return cleaned_tools

    def _clean_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Clean up schema by removing anyOf patterns and other complexities"""
        if not isinstance(schema, dict):
            return schema

        cleaned = copy.deepcopy(schema)

        # Clean properties recursively
        if "properties" in cleaned:
            cleaned_properties = {}
            for prop_name, prop_schema in cleaned["properties"].items():
                cleaned_properties[prop_name] = self._clean_property_schema(prop_schema)
            cleaned["properties"] = cleaned_properties

        return cleaned

    def _clean_property_schema(self, prop_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Clean individual property schema"""
        if not isinstance(prop_schema, dict):
            return prop_schema

        cleaned = copy.deepcopy(prop_schema)

        # Handle anyOf patterns - extract the non-null type
        if "anyOf" in cleaned:
            non_null_schemas = [
                item
                for item in cleaned["anyOf"]
                if not (isinstance(item, dict) and item.get("type") == "null")
            ]

            if len(non_null_schemas) == 1:
                # Replace anyOf with the single non-null type
                non_null_schema = non_null_schemas[0]

                # Merge the non-null schema properties
                for key, value in non_null_schema.items():
                    if key not in cleaned or key == "type":
                        cleaned[key] = value

                # Remove the anyOf
                del cleaned["anyOf"]

        # Handle oneOf with single option
        if "oneOf" in cleaned and len(cleaned["oneOf"]) == 1:
            single_schema = cleaned["oneOf"][0]
            for key, value in single_schema.items():
                if key not in cleaned or key == "type":
                    cleaned[key] = value
            del cleaned["oneOf"]

        # Remove nullable indicators
        if "nullable" in cleaned:
            del cleaned["nullable"]

        # Clean up title if it's auto-generated and not useful
        if "title" in cleaned and cleaned["title"].endswith("Arguments"):
            del cleaned["title"]

        # Recursively clean nested schemas
        if "properties" in cleaned:
            nested_properties = {}
            for nested_name, nested_schema in cleaned["properties"].items():
                nested_properties[nested_name] = self._clean_property_schema(
                    nested_schema
                )
            cleaned["properties"] = nested_properties

        if "items" in cleaned:
            cleaned["items"] = self._clean_property_schema(cleaned["items"])

        return cleaned


class DynamicMCPServer:
    """MCP Server that dynamically generates tools from Cloudsmith's OpenAPI specs"""

    def __init__(
        self,
        api_config: cloudsmith_api.Configuration = None,
        use_toon=True,
        allow_destructive_tools=False,
        debug_mode=False,
        allowed_tool_groups: Optional[List[str]] = None,
        allowed_tools: Optional[List[str]] = None,
        force_all_tools: bool = False,
    ):
        mcp_kwargs = {"log_level": "ERROR"}
        if debug_mode:
            mcp_kwargs["log_level"] = "DEBUG"
        self.mcp = CustomFastMCP(SERVER_NAME, **mcp_kwargs)
        self.api_config = api_config
        self.api_base_url = api_config.host
        self.use_toon = use_toon
        self.allow_destructive_tools = allow_destructive_tools
        self.allowed_tool_groups = set(allowed_tool_groups or [])
        self.allowed_tools = set(allowed_tools or [])
        self.force_all_tools = force_all_tools
        self.tools: Dict[str, OpenAPITool] = {}
        self.spec = {}

    async def load_openapi_spec(self):
        """Load OpenAPI spec and generate tools dynamically"""

        if not self.api_base_url:
            raise Exception("The Cloudsmith API has to be set")

        async with create_mcp_http_client(
            timeout=30.0, headers=self._get_additional_headers()
        ) as http_client:
            for version, endpoint in API_VERSIONS_TO_DISCOVER.items():
                spec_url = f"{self.api_base_url}/{version}/{endpoint}"
                response = await http_client.get(spec_url)
                response.raise_for_status()
                self.spec = response.json()
                await self._generate_tools_from_spec()

    def _get_tool_groups(self, tool_name: str) -> List[str]:
        """
        Extract all hierarchical group names from a tool name, excluding action suffixes.

        Examples:
            webhooks_create -> ['webhooks']
            repos_upstream_swift_list -> ['repos', 'repos_upstream', 'repos_upstream_swift']
            vulnerabilities_read -> ['vulnerabilities']
            workspaces_policies_actions_partial_update -> ['workspaces', 'workspaces_policies']
            repos_upstream_huggingface_partial_update -> ['repos', 'repos_upstream', 'repos_upstream_huggingface']
        """
        groups = []
        parts = tool_name.split("_")

        # Determine how many parts belong to the action suffix
        # Sort by length descending to match longest suffixes first
        sorted_suffixes = sorted(
            TOOL_ACTION_SUFFIXES, key=lambda x: len(x.split("_")), reverse=True
        )

        action_parts_count = 0
        for action_suffix in sorted_suffixes:
            action_suffix_parts = action_suffix.split("_")
            if len(parts) >= len(action_suffix_parts):
                # Check if the end of the tool name matches this action suffix
                if parts[-len(action_suffix_parts) :] == action_suffix_parts:
                    action_parts_count = len(action_suffix_parts)
                    break

        # If no action suffix found, treat the last part as the action
        if action_parts_count == 0:
            action_parts_count = 1

        # Build hierarchical groups by progressively adding parts, excluding action suffix
        resource_parts = (
            parts[:-action_parts_count] if action_parts_count > 0 else parts
        )
        for i in range(1, len(resource_parts) + 1):
            group = "_".join(resource_parts[:i])
            groups.append(group)

        return groups

    def _is_tool_destructive(self, tool_name: str) -> bool:
        return any(suffix in tool_name for suffix in TOOL_DELETE_SUFFIXES)

    def _is_tool_read_only(self, tool_name: str) -> bool:
        return any(suffix in tool_name for suffix in TOOL_READ_ONLY_SUFFIXES)

    def _is_tool_allowed(self, tool_name: str) -> bool:
        """Check if a tool is allowed based on user configuration"""

        if self.force_all_tools:
            return True

        # Check if tool is destructive and destructive tools are disabled
        if not self.allow_destructive_tools and self._is_tool_destructive(tool_name):
            return False

        tool_groups = self._get_tool_groups(tool_name)

        # If user provided their own list of allowed tools or tool groups
        if len(self.allowed_tools) > 0 or len(self.allowed_tool_groups) > 0:
            allowed_tool_group = bool(set(tool_groups) & set(self.allowed_tool_groups))
            allowed_tool = tool_name in self.allowed_tools
            return allowed_tool or allowed_tool_group

        # Otherwise disable all categories in the default list
        return not any(group in DEFAULT_DISABLED_CATEGORIES for group in tool_groups)

    async def _generate_tools_from_spec(self):
        """Generate MCP tools from OpenAPI specification"""

        if not self.spec:
            raise ValueError("OpenAPI spec not loaded")

        # Parse paths and generate tools
        for path, path_item in self.spec.get("paths", {}).items():
            for method, operation in path_item.items():
                path_parameters = path_item.get("parameters", [])

                if method.lower() in ALLOWED_METHODS:
                    tool = self._create_tool_from_operation(
                        method.upper(),
                        path,
                        operation,
                        path_parameters,
                        self.api_base_url,
                    )
                    if tool and self._is_tool_allowed(tool.name):
                        self.tools[tool.name] = tool
                        self._register_dynamic_tool(tool)

    def _register_dynamic_tool(self, api_tool: OpenAPITool):
        """Register a single tool dynamically with the MCP server"""

        # Create the tool function dynamically
        async def dynamic_tool_func(**kwargs) -> str:
            return await self._execute_api_call(api_tool, kwargs)

        # Set function metadata for MCP
        dynamic_tool_func.__name__ = api_tool.name

        docstring_parts = [api_tool.description]
        properties = api_tool.parameters.get("properties", {})
        if properties:
            docstring_parts.append("\nParameters:")
            for param_name, param_schema in properties.items():
                param_type = param_schema.get("type", "string")
                param_desc = param_schema.get("description", "")

                param_line = f"{param_name} ({param_type})"

                # Add enum information
                if "enum" in param_schema:
                    enum_values = map(str, param_schema["enum"])
                    param_line += f" - One of: {', '.join(enum_values)}"

                    # Add default if available
                    if "default" in param_schema:
                        param_line += f" (default: {param_schema['default']})"

                if param_desc:
                    param_line += f": {param_desc}"

                docstring_parts.append(param_line)

        dynamic_tool_func.__doc__ = "\n".join(docstring_parts)

        annotations = {"return": str}  # Set return type annotation

        # Create parameter annotations for better type checking
        sig_params = []
        for param_name, param_schema in properties.items():
            # For enum parameters, we could create a custom type, but for simplicity use str
            if "enum" in param_schema:
                param_type = str  # MCP will handle validation
            else:
                param_type = self._schema_type_to_python_type(
                    param_schema.get("type", "string")
                )

            annotation_type = inspect.Parameter.empty
            default = inspect.Parameter.empty

            if param_name not in api_tool.parameters.get("required", []):
                # Create parameter with default value
                default = param_schema.get("default", None)
                annotation_type = (
                    param_type if default is not None else Optional[param_type]
                )

            sig_params.append(
                inspect.Parameter(
                    param_name,
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=annotation_type,
                    default=default,
                )
            )
            annotations[param_name] = param_type

        # Create new signature
        dynamic_tool_func.__signature__ = inspect.Signature(sig_params)
        dynamic_tool_func.__annotations__ = annotations

        # Register with MCP server - this uses the decorator approach
        self.mcp.tool(
            annotations=types.ToolAnnotations(
                destructiveHint=api_tool.is_destructive,
                readOnlyHint=api_tool.is_read_only,
            )
        )(dynamic_tool_func)

    def _schema_type_to_python_type(self, schema_type: str):
        """Convert OpenAPI schema type to Python type"""
        type_mapping = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        return type_mapping.get(schema_type, str)

    def _get_additional_headers(self):
        headers = {}
        if "X-Api-Key" in self.api_config.api_key:
            headers["X-Api-Key"] = self.api_config.api_key["X-Api-Key"]

        if self.api_config.headers:
            headers.update(self.api_config.headers)

        return headers

    def _get_request_params(
        self, url: str, tool: OpenAPITool, arguments: Dict[str, Any]
    ):
        """Get params to use for HTTP request based on tool arguments"""

        query_params = {}
        body_params = {}

        # Separate parameters by type based on OpenAPI spec
        properties = tool.parameters.get("properties", {})
        validated_arguments = {}

        for key, value in arguments.items():
            if key in properties:
                param_schema = properties[key]

                # Skip None values for optional parameters
                if value is None:
                    if "default" in param_schema:
                        validated_arguments[key] = param_schema["default"]
                    continue

                # Validate enum values
                if "enum" in param_schema:
                    if value not in param_schema["enum"]:
                        allowed_values = ", ".join(param_schema["enum"])
                        return f"Invalid value '{value}' for parameter '{key}'. Allowed values: {allowed_values}"

                validated_arguments[key] = value
            else:
                validated_arguments[key] = value

        for key, value in validated_arguments.items():
            if key in properties:
                if "{" + key + "}" in url:
                    # This is a parameter as part of the URL, so replace it
                    url = url.replace("{" + key + "}", str(value))
                elif tool.method in ["GET", "DELETE"]:
                    # Query parameter for GET/DELETE
                    query_params[key] = value
                else:
                    # Body parameter for POST/PUT/PATCH
                    body_params[key] = value

        return url, query_params, body_params

    async def _execute_api_call(
        self, tool: OpenAPITool, arguments: Dict[str, Any]
    ) -> str:
        """Execute an API call based on tool definition"""

        headers = self._get_additional_headers()
        headers.update(
            {
                "Accept": "application/json",
            }
        )

        http_client = create_mcp_http_client(headers=headers)

        # Build URL with path parameters
        url = tool.base_url + tool.path

        url, query_params, body_params = self._get_request_params(url, tool, arguments)

        if tool.query_filter:
            parsed_simplified_filter = parse.parse_qs(tool.query_filter)
            query_params.update(parsed_simplified_filter)

        try:
            # Make the API call
            if tool.method == "GET":
                response = await http_client.get(url, params=query_params)
            elif tool.method == "POST":
                response = await http_client.post(
                    url, json=body_params, params=query_params
                )
            elif tool.method == "PUT":
                response = await http_client.put(
                    url, json=body_params, params=query_params
                )
            elif tool.method == "DELETE":
                response = await http_client.delete(url, params=query_params)
            elif tool.method == "PATCH":
                response = await http_client.patch(
                    url, json=body_params, params=query_params
                )
            else:
                # Unsupported method, shouldn't happen
                return f"Unsupported HTTP method: {tool.method}"

            response.raise_for_status()

            # Return formatted response
            result = response.json()
            if self.use_toon:
                return toon.encode(result)
            return json.dumps(result, indent=2)

        except (json.JSONDecodeError, toon.ToonEncodingError):
            return response.text
        except httpx.HTTPError as e:
            return f"HTTP error: {str(e)}"
        finally:
            await http_client.aclose()

    def _extract_parameters_from_schema(
        self, schema: Dict[str, Any], param_in: str = "body"
    ) -> Dict[str, Any]:
        """Extract individual parameters from a resolved schema object"""

        parameters = {}

        if schema.get("type") == "object" and "properties" in schema:
            for prop_name, prop_schema in schema["properties"].items():
                enhanced_schema = {
                    **prop_schema,
                    "in": param_in,
                    "description": prop_schema.get("description", ""),
                }

                # Handle enum descriptions
                if "enum" in prop_schema:
                    enhanced_schema["enum_description"] = self._format_enum_description(
                        prop_schema["enum"], prop_schema.get("description", "")
                    )

                parameters[prop_name] = enhanced_schema

        return parameters

    def _extract_request_body_parameters(
        self, request_body: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract parameters from OpenAPI 3.0 request body with $ref resolution"""

        parameters = {}
        content = request_body.get("content", {})

        # Handle JSON request body
        if "application/json" in content:
            json_schema = content["application/json"].get("schema", {})
            resolved_schema = self._resolve_schema(json_schema)
            parameters.update(
                self._extract_parameters_from_schema(resolved_schema, "body")
            )

        # Handle form data
        if "application/x-www-form-urlencoded" in content:
            form_schema = content["application/x-www-form-urlencoded"].get("schema", {})
            resolved_schema = self._resolve_schema(form_schema)
            parameters.update(
                self._extract_parameters_from_schema(resolved_schema, "form")
            )

        return parameters

    def _extract_body_parameter(self, body_param: Dict[str, Any]) -> Dict[str, str]:
        """Extract parameters from Swagger 2.0 body parameter with $ref resolution"""

        if "schema" not in body_param:
            return {}

        # Resolve the schema reference
        schema = self._resolve_schema(body_param["schema"])

        return self._extract_parameters_from_schema(schema, "body")

    def _create_tool_from_operation(
        self,
        method: str,
        path: str,
        operation: Dict[str, Any],
        path_parameters: list,
        base_url: str,
    ) -> Optional[OpenAPITool]:
        """Create a tool definition from an OpenAPI operation"""

        # Generate operation ID
        operation_id = operation.get("operationId")
        if not operation_id:
            operation_id = f"{method.lower()}{path.replace('/', '_').replace('{', '').replace('}', '')}"

        # Clean up operation ID to be a valid Python function name
        tool_name = operation_id.replace("-", "_").replace(".", "_").lower()

        description = (
            operation.get("summary")
            or operation.get("description")
            or f"{method} {path}"
        )

        # Extract parameters
        parameters = {}
        required_params = []

        operation_params = operation.get("parameters", [])
        all_parameters = operation_params + path_parameters

        # Path and query parameters for swagger 2.0
        for param in all_parameters:
            if param.get("in") == "path" or param.get("in") == "query":
                param_name = param["name"]

                param_type = param.get("type", "string")
                param_schema = param.get("schema", {"type": param_type})
                enhanced_schema = {
                    **param_schema,
                    "description": param.get("description", ""),
                    "in": param.get("in"),
                }

                if "enum" in param_schema:
                    enhanced_schema["enum"] = param_schema["enum"]
                    enhanced_schema["enum_description"] = self._format_enum_description(
                        param_schema.get("enum", []), param.get("description", "")
                    )

                parameters[param_name] = enhanced_schema

                if param.get("required", False):
                    required_params.append(param["name"])
            elif param.get("in") == "body":
                body_params = self._extract_body_parameter(param)
                parameters.update(body_params)
                if param.get("required", False):
                    required_params.extend(body_params.keys())

        # handle request body for openapi 3.0+
        if method in ["POST", "PUT", "PATCH"] and "requestBody" in operation:
            body_params = self._extract_request_body_parameters(
                operation["requestBody"]
            )
            parameters.update(body_params)

            if operation["requestBody"].get("required", True):
                required_params.extend(body_params.keys())

        simplified_query = operation.get("x-simplified")

        # Create parameter schema for MCP
        parameter_schema = {
            "type": "object",
            "properties": parameters,
            "required": required_params,
        }

        return OpenAPITool(
            name=tool_name,
            description=description,
            method=method,
            path=path,
            parameters=parameter_schema,
            base_url=base_url,
            query_filter=simplified_query,
            is_destructive=self._is_tool_destructive(tool_name),
            is_read_only=self._is_tool_read_only(tool_name),
        )

    def _format_enum_description(
        self, enum_values: List[str], original_description: str
    ) -> str:
        """Format enum values for better tool descriptions"""

        if not enum_values:
            return original_description

        enum_list = "\n".join([f"  - {value}" for value in enum_values])

        if original_description:
            return f"{original_description}\n\nAllowed values:\n{enum_list}"

        return f"Allowed values:\n{enum_list}"

    def _resolve_schema_ref(self, ref_string: str) -> Dict[str, Any]:
        """
        Resolve a $ref reference to its actual schema definition

        Args:
            ref_string: The $ref string like "#/definitions/PackageCopyRequest"
            spec: The full OpenAPI specification

        Returns:
            The resolved schema definition
        """
        if not ref_string.startswith("#/"):
            raise ValueError(f"Only local references supported: {ref_string}")

        if not self.spec:
            raise ValueError("OpenAPI spec not loaded")

        # Remove the '#/' prefix and split the path
        path_parts = ref_string[2:].split("/")

        # Navigate through the spec to find the definition
        current = self.spec
        for part in path_parts:
            if part in current:
                current = current[part]
            else:
                raise ValueError(f"Reference not found: {ref_string}")

        return current

    def _resolve_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively resolve a schema, handling $ref references
        """
        if "$ref" in schema:
            # Resolve the reference
            resolved = self._resolve_schema_ref(schema["$ref"])
            # Recursively resolve the resolved schema in case it has more refs
            return self._resolve_schema(resolved)

        # Handle nested schemas
        resolved_schema = schema.copy()

        # Resolve properties in object schemas
        if "properties" in schema:
            resolved_schema["properties"] = {}
            for prop_name, prop_schema in schema["properties"].items():
                resolved_schema["properties"][prop_name] = self._resolve_schema(
                    prop_schema
                )

        # Resolve items in array schemas
        if "items" in schema:
            resolved_schema["items"] = self._resolve_schema(schema["items"])

        # Resolve allOf, oneOf, anyOf
        for key in ["allOf", "oneOf", "anyOf"]:
            if key in schema:
                resolved_schema[key] = [
                    self._resolve_schema(sub_schema) for sub_schema in schema[key]
                ]

        return resolved_schema

    def run(self):
        """Initialize and run the server"""
        asyncio.run(self.load_openapi_spec())
        try:
            self.mcp.run(transport="stdio")
        except asyncio.CancelledError:
            print("Server shutdown requested")

    def list_tools(self) -> Dict[str, OpenAPITool]:
        """Initialize and return list of tools. Useful for debugging"""
        asyncio.run(self.load_openapi_spec())
        return self.tools

    def list_groups(self) -> Dict[str, List[str]]:
        """Initialize and return list of tool groups with their tools. Useful for debugging"""
        asyncio.run(self.load_openapi_spec())

        # Build a mapping of group -> list of tools
        groups: Dict[str, List[str]] = {}

        for tool_name in self.tools:
            tool_groups = self._get_tool_groups(tool_name)
            for group in tool_groups:
                if group not in groups:
                    groups[group] = []
                groups[group].append(tool_name)

        # Sort groups by name and tools within each group
        return {group: sorted(tools) for group, tools in sorted(groups.items())}
