"""Geometry tools – pure-Python STL generation for OpenFOAM.

All geometry is created as ASCII STL files directly, without Rhino dependency.
Supported primitives: box, cylinder, sphere. External STL import also supported.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Optional

import numpy as np

from ..errors import GeometryError
from ..workshop.manager import get_stl_path, _read_config


def _normalize(v):
    """Normalize a 3D vector."""
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v)
    if n < 1e-15:
        return np.array([0.0, 0.0, 1.0])
    return v / n


def _stl_facet(normal, v1, v2, v3):
    """Generate one ASCII STL facet string."""
    n = _normalize(normal)
    return (
        f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}\n"
        f"    outer loop\n"
        f"      vertex {v1[0]:.6e} {v1[1]:.6e} {v1[2]:.6e}\n"
        f"      vertex {v2[0]:.6e} {v2[1]:.6e} {v2[2]:.6e}\n"
        f"      vertex {v3[0]:.6e} {v3[1]:.6e} {v3[2]:.6e}\n"
        f"    endloop\n"
        f"  endfacet\n"
    )


def _write_ascii_stl(filepath: Path, solid_name: str, facets: list[str]):
    """Write facets to an ASCII STL file."""
    content = f"solid {solid_name}\n"
    content += "".join(facets)
    content += f"endsolid {solid_name}\n"
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")


def create_box_stl(
    workshop_root: str | Path,
    stl_name: str,
    origin: tuple[float, float, float] = (0, 0, 0),
    dimensions: tuple[float, float, float] = (1, 1, 1),
) -> dict:
    """Create an axis-aligned box as STL.

    Args:
        workshop_root: Workshop directory path.
        stl_name: Name for the STL file (without .stl extension).
        origin: (x, y, z) of the box min corner in meters.
        dimensions: (dx, dy, dz) in meters.

    Returns:
        dict with stl_path and statistics.
    """
    stl_path = get_stl_path(workshop_root, stl_name)
    ox, oy, oz = origin
    dx, dy, dz = dimensions

    # 8 vertices of the box
    v = [
        np.array([ox, oy, oz]),
        np.array([ox + dx, oy, oz]),
        np.array([ox + dx, oy + dy, oz]),
        np.array([ox, oy + dy, oz]),
        np.array([ox, oy, oz + dz]),
        np.array([ox + dx, oy, oz + dz]),
        np.array([ox + dx, oy + dy, oz + dz]),
        np.array([ox, oy + dy, oz + dz]),
    ]

    # 6 faces, each 2 triangles
    faces = [
        (v[0], v[1], v[2], v[3]),   # -z (bottom)
        (v[4], v[7], v[6], v[5]),   # +z (top)
        (v[4], v[5], v[1], v[0]),   # -y
        (v[7], v[3], v[2], v[6]),   # +y
        (v[4], v[0], v[3], v[7]),   # -x
        (v[5], v[6], v[2], v[1]),   # +x
    ]
    normals = [
        (0, 0, -1), (0, 0, 1),
        (0, -1, 0), (0, 1, 0),
        (-1, 0, 0), (1, 0, 0),
    ]

    facets = []
    for quad, norm in zip(faces, normals):
        p0, p1, p2, p3 = quad
        facets.append(_stl_facet(norm, p0, p1, p2))
        facets.append(_stl_facet(norm, p0, p2, p3))

    _write_ascii_stl(stl_path, stl_name, facets)

    return {
        "stl_path": str(stl_path.resolve()),
        "stl_name": stl_name,
        "geometry_type": "box",
        "origin": list(origin),
        "dimensions": list(dimensions),
        "num_facets": len(facets),
    }


def create_cylinder_stl(
    workshop_root: str | Path,
    stl_name: str,
    origin: tuple[float, float, float] = (0, 0, 0),
    radius: float = 0.1,
    height: float = 0.3,
    axis: str = "z",
    segments: int = 32,
    capped: bool = True,
) -> dict:
    """Create a cylinder as STL.

    Args:
        workshop_root: Workshop directory path.
        stl_name: Name for the STL file.
        origin: Center of the cylinder bottom face in meters.
        radius: Cylinder radius in meters.
        height: Cylinder height in meters.
        axis: Cylinder axis direction ('x', 'y', or 'z').
        segments: Number of segments around the circumference.
        capped: If True, add end caps.

    Returns:
        dict with stl_path and statistics.
    """
    stl_path = get_stl_path(workshop_root, stl_name)
    ox, oy, oz = origin
    segments = max(3, segments)

    # Generate circle points
    angles = np.linspace(0, 2 * math.pi, segments, endpoint=False)
    cx = np.cos(angles) * radius
    cy = np.sin(angles) * radius

    if axis == "z":
        btm = np.column_stack([cx + ox, cy + oy, np.full(segments, oz)])
        top = np.column_stack([cx + ox, cy + oy, np.full(segments, oz + height)])
        btm_center = np.array([ox, oy, oz])
        top_center = np.array([ox, oy, oz + height])
    elif axis == "y":
        btm = np.column_stack([cx + ox, np.full(segments, oy), cy + oz])
        top = np.column_stack([cx + ox, np.full(segments, oy + height), cy + oz])
        btm_center = np.array([ox, oy, oz])
        top_center = np.array([ox, oy + height, oz])
    elif axis == "x":
        btm = np.column_stack([np.full(segments, ox), cx + oy, cy + oz])
        top = np.column_stack([np.full(segments, ox + height), cx + oy, cy + oz])
        btm_center = np.array([ox, oy, oz])
        top_center = np.array([ox + height, oy, oz])
    else:
        raise GeometryError("axis must be 'x', 'y', or 'z'")

    facets = []

    # Side faces (quads -> 2 triangles each)
    for i in range(segments):
        j = (i + 1) % segments
        a, b = btm[i], btm[j]
        c, d = top[j], top[i]
        # normal points outward
        n = _normalize(np.cross(b - a, c - a))
        facets.append(_stl_facet(n, a, b, c))
        facets.append(_stl_facet(n, a, c, d))

    if capped:
        # Bottom cap
        for i in range(segments):
            j = (i + 1) % segments
            if axis == "z":
                n = (0, 0, -1)
            elif axis == "y":
                n = (0, -1, 0)
            else:
                n = (-1, 0, 0)
            facets.append(_stl_facet(n, btm_center, btm[j], btm[i]))
        # Top cap
        for i in range(segments):
            j = (i + 1) % segments
            if axis == "z":
                n = (0, 0, 1)
            elif axis == "y":
                n = (0, 1, 0)
            else:
                n = (1, 0, 0)
            facets.append(_stl_facet(n, top_center, top[i], top[j]))

    _write_ascii_stl(stl_path, stl_name, facets)

    return {
        "stl_path": str(stl_path.resolve()),
        "stl_name": stl_name,
        "geometry_type": "cylinder",
        "origin": list(origin),
        "radius": radius,
        "height": height,
        "axis": axis,
        "num_facets": len(facets),
    }


def create_sphere_stl(
    workshop_root: str | Path,
    stl_name: str,
    origin: tuple[float, float, float] = (0, 0, 0),
    radius: float = 0.3,
    segments: int = 24,
) -> dict:
    """Create a triangulated sphere as STL using icosphere approximation.

    Args:
        workshop_root: Workshop directory path.
        stl_name: Name for the STL file.
        origin: Sphere center in meters.
        radius: Sphere radius in meters.
        segments: Number of lat/lon divisions.

    Returns:
        dict with stl_path and statistics.
    """
    stl_path = get_stl_path(workshop_root, stl_name)
    ox, oy, oz = origin

    # Lat/lon sphere
    lats = segments // 2
    lons = segments

    vertices = []
    # Poles
    vertices.append((ox, oy, oz + radius))       # north pole
    vertices.append((ox, oy, oz - radius))       # south pole

    for i in range(1, lats):
        theta = math.pi * i / lats
        st = math.sin(theta)
        ct = math.cos(theta)
        for j in range(lons):
            phi = 2 * math.pi * j / lons
            x = ox + radius * st * math.cos(phi)
            y = oy + radius * st * math.sin(phi)
            z = oz + radius * ct
            vertices.append((x, y, z))

    v = [np.array(p) for p in vertices]

    facets = []

    # North cap
    for j in range(lons):
        jn = (j + 1) % lons
        idx_a = 2 + j
        idx_b = 2 + jn
        n_out = _normalize(v[idx_a] + v[idx_b] + v[0] - np.array([ox, oy, oz]) * 3)
        facets.append(_stl_facet(n_out, v[0], v[idx_b], v[idx_a]))

    # Body
    for i in range(lats - 2):
        for j in range(lons):
            jn = (j + 1) % lons
            a = 2 + i * lons + j
            b = 2 + i * lons + jn
            c = 2 + (i + 1) * lons + jn
            d = 2 + (i + 1) * lons + j
            n1 = _normalize(v[a] + v[b] + v[c] - np.array([ox, oy, oz]) * 3)
            n2 = _normalize(v[a] + v[c] + v[d] - np.array([ox, oy, oz]) * 3)
            facets.append(_stl_facet(n1, v[a], v[b], v[c]))
            facets.append(_stl_facet(n2, v[a], v[c], v[d]))

    # South cap
    for j in range(lons):
        jn = (j + 1) % lons
        idx_a = 2 + (lats - 2) * lons + j
        idx_b = 2 + (lats - 2) * lons + jn
        n_out = _normalize(v[idx_a] + v[idx_b] + v[1] - np.array([ox, oy, oz]) * 3)
        facets.append(_stl_facet(n_out, v[1], v[idx_a], v[idx_b]))

    _write_ascii_stl(stl_path, stl_name, facets)

    return {
        "stl_path": str(stl_path.resolve()),
        "stl_name": stl_name,
        "geometry_type": "sphere",
        "origin": list(origin),
        "radius": radius,
        "num_facets": len(facets),
    }


def import_stl(
    workshop_root: str | Path,
    source_path: str | Path,
    stl_name: Optional[str] = None,
) -> dict:
    """Import an existing STL file into the workshop.

    Args:
        workshop_root: Workshop directory path.
        source_path: Path to external STL file.
        stl_name: Name in workshop (defaults to source filename stem).

    Returns:
        dict with stl_path and original source.
    """
    source = Path(source_path)
    if not source.exists():
        raise GeometryError(f"Source STL file not found: {source}")
    if source.suffix.lower() not in (".stl",):
        raise GeometryError(f"Source must be an STL file, got: {source.suffix}")

    if stl_name is None:
        stl_name = source.stem

    stl_path = get_stl_path(workshop_root, stl_name)
    shutil.copy2(source, stl_path)

    # Parse facet count
    content = stl_path.read_text(encoding="utf-8", errors="ignore")
    num_facets = content.count("endfacet")

    return {
        "stl_path": str(stl_path.resolve()),
        "stl_name": stl_name,
        "geometry_type": "imported",
        "source_path": str(source.resolve()),
        "num_facets": num_facets,
    }


def list_geometry(workshop_root: str | Path) -> dict:
    """List all STL files in the workshop.

    Args:
        workshop_root: Workshop directory path.

    Returns:
        dict with list of geometry files and their info.
    """
    ws_dir = Path(workshop_root)
    _read_config(ws_dir)
    stl_dir = ws_dir / "stl"

    files = []
    if stl_dir.is_dir():
        for f in sorted(stl_dir.glob("*.stl")):
            size_bytes = f.stat().st_size
            files.append({
                "name": f.name,
                "path": str(f.resolve()),
                "size_bytes": size_bytes,
            })

    return {"workshop_root": str(ws_dir.resolve()), "geometry_files": files}
