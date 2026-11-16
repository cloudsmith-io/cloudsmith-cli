from dataclasses import dataclass
from typing import Any


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
    def is_read_only(self) -> bool:
        return self.method == "GET"

    @property
    def is_destructive(self) -> bool:
        return not self.is_read_only
