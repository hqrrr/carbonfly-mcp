"""Carbonfly MCP error types."""


class CarbonflyMCPError(Exception):
    """Base exception for Carbonfly MCP operations."""


class WorkshopError(CarbonflyMCPError):
    """Workshop (workspace) related errors."""


class GeometryError(CarbonflyMCPError):
    """Geometry generation / STL errors."""


class SimulationError(CarbonflyMCPError):
    """Simulation / case generation / solver errors."""


class WslError(CarbonflyMCPError):
    """WSL / OpenFOAM runtime errors."""


class PostProcError(CarbonflyMCPError):
    """Post-processing errors."""
