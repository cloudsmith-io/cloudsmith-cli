from dataclasses import dataclass
from typing import Any

TOOL_DELETE_SUFFIXES = ["delete", "destroy", "remove"]


@dataclass
class OpenAPITool:
    """Represents a tool generated from OpenAPI spec"""

    name: str
    description: str
    method: str
    path: str
    parameters: dict[str, Any]
    base_url: str
    query_filter: str | None

    @property
    def is_destructive(self) -> bool:
        return self.method != "GET" or any(
            suffix in self.name for suffix in TOOL_DELETE_SUFFIXES
        )

    @property
    def is_read_only(self) -> bool:
        return not self.is_destructive
