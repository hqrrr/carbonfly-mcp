"""Geometry tools – pure-Python multi-region STL generation for OpenFOAM.

All geometry is created as named ``solid`` blocks inside a single ``scene.stl``
file. snappyHexMesh recognises each ``solid`` block as a separate patch, so
there is no need for separate STL files per boundary.

Supported primitives: box, cylinder, sphere. External STL import also supported.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Optional

import numpy as np

from ..errors import GeometryError
from ..workshop.manager import _read_config

SCENE_STL = "scene"


# ---- Low-level STL helpers ----

def _normalize(v):
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v)
    if n < 1e-15:
        return np.array([0.0, 0.0, 1.0])
    return v / n


def _stl_facet(normal, v1, v2, v3):
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


# ---- Scene file management ----

def _get_scene_path(workshop_root):
    ws_dir = Path(workshop_root)
    _read_config(ws_dir)
    return ws_dir / "stl" / f"{SCENE_STL}.stl"


def _parse_scene_solids(scene_path):
    if not scene_path.exists():
        return {}
    raw = scene_path.read_text(encoding="utf-8", errors="ignore")
    solids = {}
    current = None
    buf = []
    for line in raw.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("solid ") and not stripped.startswith("solid from "):
            current = stripped[6:].strip()
            buf = []
        elif stripped.startswith("endsolid"):
            if current:
                solids[current] = buf
            current = None
        elif current is not None:
            buf.append(line)
    return solids


def _rebuild_scene(scene_path, solids):
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    with open(scene_path, "w", encoding="utf-8") as f:
        for name in sorted(solids):
            f.write(f"solid {name}\n")
            f.write("".join(solids[name]))
            f.write(f"endsolid {name}\n")


# ---- 2D polygon triangulation (ear-clipping with holes) ----


def _cross_2d(a, b, c):
    """Signed cross product (b-a) × (c-b) in 2D. Positive = left turn (CCW)."""
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])


def _polygon_area_2d(poly):
    """Signed area of a 2D polygon (positive = CCW)."""
    n = len(poly)
    area = 0.0
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _is_ccw(poly):
    return _polygon_area_2d(poly) > 0


def _point_in_triangle_2d(pt, a, b, c):
    """Check whether *pt* lies strictly inside triangle (a, b, c)."""
    d1 = _cross_2d(a, b, pt)
    d2 = _cross_2d(b, c, pt)
    d3 = _cross_2d(c, a, pt)
    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (has_neg and has_pos)


def _triangulate_polygon_with_holes(outer_2d, holes_2d):
    """Triangulate a 2D polygon with holes via ear-clipping.

    Args:
        outer_2d: Outer boundary vertices as [(x,y), …] (CCW).
        holes_2d: List of hole boundaries, each [(x,y), …] (CW).

    Returns:
        (vertices, triangles) where *vertices* is the merged vertex list
        and *triangles* is a list of (i, j, k) index triples.
    """
    # Ensure outer is CCW, holes are CW
    if not _is_ccw(outer_2d):
        outer_2d = list(reversed(outer_2d))
    holes_cw = []
    for hole in holes_2d:
        if _is_ccw(hole):
            holes_cw.append(list(reversed(hole)))
        else:
            holes_cw.append(list(hole))

    # Build combined vertex list
    vertices = list(outer_2d)
    hole_ranges = []  # (start_inclusive, end_exclusive)
    for hole in holes_cw:
        start = len(vertices)
        vertices.extend(hole)
        hole_ranges.append((start, len(vertices)))
    n_outer = len(outer_2d)

    # Find a bridge (closest pair) for every hole and build a single
    # non-self-intersecting polygon index list.
    indices = list(range(n_outer))
    for h_idx, (h_start, h_end) in enumerate(hole_ranges):
        best_oi = 0
        best_hi = h_start
        best_d2 = float("inf")
        for oi in range(n_outer):
            ox, oy = vertices[oi]
            for hi in range(h_start, h_end):
                hx, hy = vertices[hi]
                d2 = (ox - hx) ** 2 + (oy - hy) ** 2
                if d2 < best_d2:
                    best_d2 = d2
                    best_oi = oi
                    best_hi = hi
        # Insert hole into indices at the bridge position
        bridge_pos = indices.index(best_oi)
        hole_loop = list(range(best_hi, h_end)) + list(range(h_start, best_hi + 1))
        indices = (
            indices[: bridge_pos + 1] + hole_loop + indices[bridge_pos:]
        )

    # Deduplicate consecutive identical entries
    deduped = [indices[0]]
    for idx in indices[1:]:
        if idx != deduped[-1]:
            deduped.append(idx)
    indices = deduped

    # Ear-clipping
    remaining = indices[:]
    triangles = []

    # Safety limit to guard against infinite loops
    max_iters = len(remaining) * 10
    for _ in range(max_iters):
        n = len(remaining)
        if n < 3:
            break
        found = False
        for i in range(n):
            a_idx = remaining[(i - 1) % n]
            b_idx = remaining[i]
            c_idx = remaining[(i + 1) % n]
            a = vertices[a_idx]
            b = vertices[b_idx]
            c = vertices[c_idx]
            # Must be a convex vertex (left turn for CCW polygon)
            if _cross_2d(a, b, c) <= 0:
                continue
            # No other vertex inside the candidate ear
            ear_ok = True
            for j in range(n):
                v_idx = remaining[j]
                if v_idx in (a_idx, b_idx, c_idx):
                    continue
                if _point_in_triangle_2d(vertices[v_idx], a, b, c):
                    ear_ok = False
                    break
            if ear_ok:
                triangles.append((a_idx, b_idx, c_idx))
                remaining.pop(i)
                found = True
                break
        if not found:
            break

    if len(remaining) >= 3:
        # Final triangle — should be exactly 3 vertices left
        triangles.append(tuple(remaining[:3]))

    return vertices, triangles


# ---- Facet generators (pure – no side effects) ----


def _triangulate_face_with_cutouts(corners, normal, cutouts_2d, resolution=40):
    """Triangulate an axis-aligned rectangular face with circular cutouts.

    Generates explicit circular hole boundaries (polygon approximation)
    and triangulates the annular region between the face rectangle and the
    hole(s) using ear-clipping.

    Args:
        corners: 4 corner points [c0, c1, c2, c3] in CCW order (outside).
        normal: outward normal of the face (used only for orientation).
        cutouts_2d: [(cx, cy, r), ...] in face-local 2D.
        resolution: number of circle segments per hole (minimum 32).

    Returns:
        List of 3D triangle vertex triples.
    """
    c0, c1, c2, c3 = corners

    # Establish face-local 2D ↔ 3D mapping -------------------------------------------------
    if abs(normal[2]) > 0.5:
        # z-normal face → local coords are (x, y)
        to_3d = lambda x, y: np.array([x, y, c0[2]])
        xmin, xmax = sorted([c0[0], c2[0]])
        ymin, ymax = sorted([c0[1], c2[1]])
    elif abs(normal[1]) > 0.5:
        # y-normal face → local coords are (x, z)
        to_3d = lambda x, y: np.array([x, c0[1], y])
        xmin, xmax = sorted([c0[0], c2[0]])
        ymin, ymax = sorted([c0[2], c2[2]])
    else:
        # x-normal face → local coords are (y, z)
        to_3d = lambda x, y: np.array([c0[0], x, y])
        xmin, xmax = sorted([c0[1], c2[1]])
        ymin, ymax = sorted([c0[2], c2[2]])

    # Build outer polygon (CCW) ------------------------------------------------------------
    outer_2d = [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]

    # Build hole polygons (CW) – approximate circles with N segments -----------------------
    n_seg = max(32, resolution)
    holes_2d = []
    for cx, cy, r in cutouts_2d:
        # snappyHexMesh extrudes the hole boundary a small amount; shrink slightly
        # so the effective opening matches the requested radius.
        r_eff = max(0.0, r - 1e-6)
        angles = np.linspace(0.0, 2.0 * math.pi, n_seg, endpoint=False)
        circle_pts = [(cx + r_eff * math.cos(a), cy + r_eff * math.sin(a)) for a in angles]
        # CW order for holes (so the combined polygon is still simple)
        holes_2d.append(list(reversed(circle_pts)))

    # Triangulate -------------------------------------------------------------------------
    vertices_2d, tris_idx = _triangulate_polygon_with_holes(outer_2d, holes_2d)

    # Map to 3D ---------------------------------------------------------------------------
    triangles_3d = []
    for i, j, k in tris_idx:
        p0 = to_3d(*vertices_2d[i])
        p1 = to_3d(*vertices_2d[j])
        p2 = to_3d(*vertices_2d[k])
        triangles_3d.append((p0, p1, p2))

    return triangles_3d


def _make_box_facets(
    origin: tuple[float, float, float],
    dimensions: tuple[float, float, float],
    cutouts: dict | None = None,
    face_resolution: int = 40,
) -> list[str]:
    ox, oy, oz = origin
    dx, dy, dz = dimensions

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

    face_defs = {
        "-z": (v[0], v[1], v[2], v[3], (0, 0, -1)),
        "+z": (v[4], v[7], v[6], v[5], (0, 0, 1)),
        "-y": (v[4], v[5], v[1], v[0], (0, -1, 0)),
        "+y": (v[7], v[3], v[2], v[6], (0, 1, 0)),
        "-x": (v[4], v[0], v[3], v[7], (-1, 0, 0)),
        "+x": (v[5], v[6], v[2], v[1], (1, 0, 0)),
    }

    cutouts = cutouts or {}
    facets = []

    for face_name, (c0, c1, c2, c3, normal) in face_defs.items():
        face_cutouts = cutouts.get(face_name, [])
        if not face_cutouts:
            facets.append(_stl_facet(normal, c0, c1, c2))
            facets.append(_stl_facet(normal, c0, c2, c3))
        else:
            tris = _triangulate_face_with_cutouts(
                [c0, c1, c2, c3], normal, face_cutouts, face_resolution
            )
            for p0, p1, p2 in tris:
                facets.append(_stl_facet(normal, p0, p1, p2))

    return facets


def _make_cylinder_facets(
    origin: tuple[float, float, float],
    radius: float,
    height: float,
    axis: str,
    segments: int,
    capped: bool,
) -> list[str]:
    ox, oy, oz = origin
    segments = max(3, segments)
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

    for i in range(segments):
        j = (i + 1) % segments
        a, b = btm[i], btm[j]
        c, d = top[j], top[i]
        n = _normalize(np.cross(b - a, c - a))
        facets.append(_stl_facet(n, a, b, c))
        facets.append(_stl_facet(n, a, c, d))

    if capped:
        if axis == "z":
            n_btm, n_top = (0, 0, -1), (0, 0, 1)
        elif axis == "y":
            n_btm, n_top = (0, -1, 0), (0, 1, 0)
        else:
            n_btm, n_top = (-1, 0, 0), (1, 0, 0)
        for i in range(segments):
            j = (i + 1) % segments
            facets.append(_stl_facet(n_btm, btm_center, btm[j], btm[i]))
        for i in range(segments):
            j = (i + 1) % segments
            facets.append(_stl_facet(n_top, top_center, top[i], top[j]))

    return facets


def _make_sphere_facets(
    origin: tuple[float, float, float],
    radius: float,
    segments: int,
) -> list[str]:
    ox, oy, oz = origin
    lats = segments // 2
    lons = segments

    vertices = []
    vertices.append((ox, oy, oz + radius))
    vertices.append((ox, oy, oz - radius))

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

    for j in range(lons):
        jn = (j + 1) % lons
        idx_a = 2 + j
        idx_b = 2 + jn
        n = _normalize(v[idx_a] + v[idx_b] + v[0] - np.array([ox, oy, oz]) * 3)
        facets.append(_stl_facet(n, v[0], v[idx_b], v[idx_a]))

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

    for j in range(lons):
        jn = (j + 1) % lons
        idx_a = 2 + (lats - 2) * lons + j
        idx_b = 2 + (lats - 2) * lons + jn
        n = _normalize(v[idx_a] + v[idx_b] + v[1] - np.array([ox, oy, oz]) * 3)
        facets.append(_stl_facet(n, v[1], v[idx_a], v[idx_b]))

    return facets


def _make_disc_facets(
    origin: tuple[float, float, float],
    radius: float,
    normal: str,
    segments: int,
) -> list[str]:
    """Generate facets for a flat filled circular disc.

    The disc is a single-sided planar face — ideal for inlet / outlet patches
    that sit flush against a wall or ceiling surface.
    """
    ox, oy, oz = origin
    segments = max(3, segments)
    angles = np.linspace(0, 2 * math.pi, segments, endpoint=False)

    norm_map = {
        "+z": ((0, 0, 1), lambda a: np.array([ox + radius * math.cos(a), oy + radius * math.sin(a), oz])),
        "-z": ((0, 0, -1), lambda a: np.array([ox + radius * math.cos(a), oy + radius * math.sin(a), oz])),
        "+y": ((0, 1, 0), lambda a: np.array([ox + radius * math.cos(a), oy, oz + radius * math.sin(a)])),
        "-y": ((0, -1, 0), lambda a: np.array([ox + radius * math.cos(a), oy, oz + radius * math.sin(a)])),
        "+x": ((1, 0, 0), lambda a: np.array([ox, oy + radius * math.cos(a), oz + radius * math.sin(a)])),
        "-x": ((-1, 0, 0), lambda a: np.array([ox, oy + radius * math.cos(a), oz + radius * math.sin(a)])),
    }

    if normal not in norm_map:
        raise GeometryError(f"normal must be one of {list(norm_map.keys())}, got: {normal}")

    n_out, point_fn = norm_map[normal]
    center = np.array([ox, oy, oz])
    flip = normal.startswith("-")
    facets = []

    for i in range(segments):
        j = (i + 1) % segments
        if flip:
            facets.append(_stl_facet(n_out, center, point_fn(angles[j]), point_fn(angles[i])))
        else:
            facets.append(_stl_facet(n_out, center, point_fn(angles[i]), point_fn(angles[j])))

    return facets


# ---- Public geometry tools ----

def create_box_stl(
    workshop_root,
    stl_name,
    origin=(0, 0, 0),
    dimensions=(1, 1, 1),
    cutouts=None,
    face_resolution=40,
):
    """Create an axis-aligned box with optional face cutouts.

    ``cutouts`` maps face names (``"+z"``, ``"-z"``, …) to a list of
    ``(cx, cy, r)`` tuples in **face-local 2-D coordinates**.  This allows
    circular openings (e.g. for inlets) without overlapping geometry.

    Example — 5×4×3 m room with a 0.15 m radius hole in the ceiling at (1, 2):
        create_box_stl(ws, "room", dimensions=(5,4,3),
                       cutouts={"+z": [(1, 2, 0.15)]})
    """
    scene_path = _get_scene_path(workshop_root)
    solids = _parse_scene_solids(scene_path)

    facets = _make_box_facets(origin, dimensions, cutouts, face_resolution)
    solids[stl_name] = facets
    _rebuild_scene(scene_path, solids)

    result = {
        "scene_path": str(scene_path.resolve()),
        "stl_name": stl_name,
        "geometry_type": "box",
        "origin": list(origin),
        "dimensions": list(dimensions),
        "num_facets": len(facets),
    }
    if cutouts:
        result["cutouts"] = cutouts
    return result


def create_cylinder_stl(
    workshop_root,
    stl_name,
    origin=(0, 0, 0),
    radius=0.1,
    height=0.3,
    axis="z",
    segments=32,
    capped=True,
):
    scene_path = _get_scene_path(workshop_root)
    solids = _parse_scene_solids(scene_path)

    facets = _make_cylinder_facets(origin, radius, height, axis, segments, capped)
    solids[stl_name] = facets
    _rebuild_scene(scene_path, solids)

    return {
        "scene_path": str(scene_path.resolve()),
        "stl_name": stl_name,
        "geometry_type": "cylinder",
        "origin": list(origin),
        "radius": radius,
        "height": height,
        "axis": axis,
        "num_facets": len(facets),
    }


def create_sphere_stl(
    workshop_root,
    stl_name,
    origin=(0, 0, 0),
    radius=0.3,
    segments=24,
):
    scene_path = _get_scene_path(workshop_root)
    solids = _parse_scene_solids(scene_path)

    facets = _make_sphere_facets(origin, radius, segments)
    solids[stl_name] = facets
    _rebuild_scene(scene_path, solids)

    return {
        "scene_path": str(scene_path.resolve()),
        "stl_name": stl_name,
        "geometry_type": "sphere",
        "origin": list(origin),
        "radius": radius,
        "num_facets": len(facets),
    }


def create_disc_stl(
    workshop_root,
    stl_name,
    origin=(0, 0, 0),
    radius=0.15,
    normal="+z",
    segments=32,
):
    """Create a flat circular disc (filled face) as a boundary patch.

    Ideal for inlet / outlet patches that sit flush on a wall or ceiling.
    Pair with ``create_box_stl(cutouts={"+z": [(cx, cy, r)]})`` so the disc
    occupies the hole without overlapping the box face.

    Args:
        workshop_root: Workshop directory path.
        stl_name: Solid name for the disc.
        origin: Center of the disc in 3-D (meters).
        radius: Disc radius (meters).
        normal: Face normal direction (``"+z"``, ``"-z"``, ``"+y"``, ``"-y"``, ``"+x"``, ``"-x"``).
        segments: Circumference segment count.
    """
    scene_path = _get_scene_path(workshop_root)
    solids = _parse_scene_solids(scene_path)

    facets = _make_disc_facets(origin, radius, normal, segments)
    solids[stl_name] = facets
    _rebuild_scene(scene_path, solids)

    return {
        "scene_path": str(scene_path.resolve()),
        "stl_name": stl_name,
        "geometry_type": "disc",
        "origin": list(origin),
        "radius": radius,
        "normal": normal,
        "num_facets": len(facets),
    }


def import_stl(
    workshop_root,
    source_path,
    stl_name=None,
):
    source = Path(source_path)
    if not source.exists():
        raise GeometryError(f"Source STL file not found: {source}")
    if source.suffix.lower() not in (".stl",):
        raise GeometryError(f"Source must be an STL file, got: {source.suffix}")

    scene_path = _get_scene_path(workshop_root)
    solids = _parse_scene_solids(scene_path)

    imported_solids = _parse_scene_solids(source)
    if not imported_solids:
        raise GeometryError(f"No solid blocks found in: {source}")

    imported_names = []
    total_facets = 0

    for solid_name, facets in imported_solids.items():
        target_name = stl_name if stl_name and len(imported_solids) == 1 else solid_name
        solids[target_name] = facets
        imported_names.append(target_name)
        total_facets += _count_facets(facets)

    _rebuild_scene(scene_path, solids)

    return {
        "scene_path": str(scene_path.resolve()),
        "imported_solids": imported_names,
        "geometry_type": "imported",
        "source_path": str(source.resolve()),
        "num_facets": total_facets,
    }


def _count_facets(facet_data):
    if not facet_data:
        return 0
    return sum(1 for item in facet_data if "endfacet" in item)


def list_geometry(workshop_root):
    scene_path = _get_scene_path(workshop_root)
    solids = _parse_scene_solids(scene_path)

    geo = []
    for name, facets in sorted(solids.items()):
        geo.append({
            "name": name,
            "num_facets": _count_facets(facets),
        })

    return {
        "workshop_root": str(Path(workshop_root).resolve()),
        "scene_path": str(scene_path.resolve()),
        "solids": geo,
    }


def clear_geometry(workshop_root):
    scene_path = _get_scene_path(workshop_root)
    _rebuild_scene(scene_path, {})
    return {
        "workshop_root": str(Path(workshop_root).resolve()),
        "scene_path": str(scene_path.resolve()),
        "cleared": True,
    }
