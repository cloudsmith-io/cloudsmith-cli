from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class OpenAPITool:
    """Represents a tool generated from OpenAPI spec"""

    name: str
    description: str
    method: str
    path: str
    parameters: Dict[str, Any]
    base_url: str
    query_filter: Optional[str]
    is_destructive: bool = False
    is_read_only: bool = False
