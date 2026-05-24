"""FastMCP server for Carbonfly MCP.

Provides headless indoor CO2 CFD simulation via OpenFOAM + WSL through MCP.
Uses Code Mode (sandboxed Python execution) for tool orchestration, following
the same pattern as ladybug-tools-mcp.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastmcp import FastMCP

from . import __version__
from .registry import register_tools

# Ensure the carbonfly library is importable (sibling directory)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # carbonfly-mcp/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def create_mcp() -> FastMCP:
    """Create and configure the Carbonfly MCP server."""

    mcp = FastMCP(
        "Carbonfly MCP",
        version=__version__,
        instructions=(
            "Carbonfly MCP – headless indoor CO2 CFD simulation with OpenFOAM via WSL. "
            "Create simulation workspaces, generate geometry (STL), configure boundary "
            "conditions, generate OpenFOAM cases, run meshing and solver, and process results. "
            "No Rhino or Grasshopper required."
        ),
        on_duplicate="error",
        strict_input_validation=True,
        mask_error_details=False,
    )

    register_tools(mcp)
    return mcp


# Module-level MCP instance for `python -m carbonfly_mcp.server`
mcp = create_mcp()


def main():
    """CLI entry point for carbonfly-mcp."""
    mcp.run()


if __name__ == "__main__":
    main()
