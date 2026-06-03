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
    is_destructive: bool = False
    is_read_only: bool = False
