"""City adapter interface.

A city plugs in by subclassing CityAdapter, implementing register_tools(),
and adding itself to src/adapters/registry.py. See docs/ADDING_A_CITY.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


class CityAdapter(ABC):
    """Binds a city's data sources to MCP tools."""

    name: str = "base"

    @abstractmethod
    def register_tools(self, mcp: FastMCP) -> None:
        """Register this city's MCP tools on the FastMCP server."""

    async def health_check(self) -> dict[str, str]:
        """Report upstream dependency status, e.g. {"socrata": "ok"}."""
        return {}
