from dataclasses import dataclass
from typing import Any, Dict

import httpx


@dataclass
class OpenAPITool:
    """Represents a tool generated from OpenAPI spec"""

    name: str
    description: str
    method: str
    path: str
    parameters: Dict[str, Any]
    base_url: str


@dataclass
class AppContext:
    """Application context for storing OpenAPI tools and HTTP client"""

    http_client: httpx.AsyncClient
