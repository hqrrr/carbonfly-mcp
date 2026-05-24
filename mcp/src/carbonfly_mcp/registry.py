"""Tool registration for Carbonfly MCP – registers all domain tools with FastMCP."""

from __future__ import annotations

from fastmcp import FastMCP

from .workshop.manager import (
    create_workshop,
    list_workshops,
    get_workshop_info,
    delete_workshop,
)

from .tools.geometry import (
    create_box_stl,
    create_cylinder_stl,
    create_sphere_stl,
    import_stl,
    list_geometry,
)

from .tools.boundary import (
    configure_inlet,
    configure_outlet,
    configure_wall,
    configure_dynamic_respiration,
    configure_recirculation,
    list_boundaries,
    clear_boundaries,
)

from .tools.simulation import (
    check_environment,
    generate_case,
    run_meshing,
    run_simulation,
    get_simulation_status,
)

from .tools.postproc import (
    list_results,
    probe_point,
    assess_iaq,
    read_co2_field,
    read_temperature_field,
)


def register_tools(mcp: FastMCP) -> None:
    """Register all Carbonfly MCP tools."""

    # ---- Workshop (workspace) tools ----
    mcp.add_tool(create_workshop)
    mcp.add_tool(list_workshops)
    mcp.add_tool(get_workshop_info)
    mcp.add_tool(delete_workshop)

    # ---- Geometry tools ----
    mcp.add_tool(create_box_stl)
    mcp.add_tool(create_cylinder_stl)
    mcp.add_tool(create_sphere_stl)
    mcp.add_tool(import_stl)
    mcp.add_tool(list_geometry)

    # ---- Boundary tools ----
    mcp.add_tool(configure_inlet)
    mcp.add_tool(configure_outlet)
    mcp.add_tool(configure_wall)
    mcp.add_tool(configure_dynamic_respiration)
    mcp.add_tool(configure_recirculation)
    mcp.add_tool(list_boundaries)
    mcp.add_tool(clear_boundaries)

    # ---- Simulation tools ----
    mcp.add_tool(check_environment)
    mcp.add_tool(generate_case)
    mcp.add_tool(run_meshing)
    mcp.add_tool(run_simulation)
    mcp.add_tool(get_simulation_status)

    # ---- Post-processing tools ----
    mcp.add_tool(list_results)
    mcp.add_tool(probe_point)
    mcp.add_tool(assess_iaq)
    mcp.add_tool(read_co2_field)
    mcp.add_tool(read_temperature_field)
