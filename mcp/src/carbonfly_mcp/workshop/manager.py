"""Workshop manager – manages simulation workspaces for Carbonfly MCP.

A Workshop is a local directory that contains:
- workshop.json    – metadata and configuration
- stl/             – STL geometry files
- cases/           – OpenFOAM case directories
- results/         – post-processing results
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from ..errors import WorkshopError

WORKSHOP_CONFIG = "workshop.json"


def _ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_workshop(root: str | Path, name: str, description: str = "") -> dict[str, Any]:
    """Create a new workshop directory.

    Args:
        root: Parent directory for the workshop.
        name: Unique workshop name (slug).
        description: Optional description.

    Returns:
        dict with keys: workshop_root, name, created_at.
    """
    root = Path(root)
    ws_dir = root / name
    if ws_dir.exists():
        raise WorkshopError(f"Workshop already exists: {ws_dir}")

    stl_dir = _ensure_dir(ws_dir / "stl")
    cases_dir = _ensure_dir(ws_dir / "cases")
    results_dir = _ensure_dir(ws_dir / "results")

    config = {
        "name": name,
        "description": description,
        "created_at": datetime.now().isoformat(),
        "carbonfly_mcp_version": "0.1.0",
    }
    (ws_dir / WORKSHOP_CONFIG).write_text(json.dumps(config, indent=2), encoding="utf-8")

    return {
        "workshop_root": str(ws_dir.resolve()),
        "name": name,
        "stl_dir": str(stl_dir.resolve()),
        "cases_dir": str(cases_dir.resolve()),
        "results_dir": str(results_dir.resolve()),
        "created_at": config["created_at"],
    }


def _read_config(ws_dir: Path) -> dict[str, Any]:
    cfg_path = ws_dir / WORKSHOP_CONFIG
    if not cfg_path.exists():
        raise WorkshopError(f"Not a workshop directory (missing {WORKSHOP_CONFIG}): {ws_dir}")
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def _resolve_workshop(root: str | Path, name: str) -> Path:
    """Resolve a workshop by name under root, verifying workshop.json exists."""
    root = Path(root)
    candidates = list(root.glob(name))
    if len(candidates) == 1 and candidates[0].is_dir():
        ws_dir = candidates[0]
        if (ws_dir / WORKSHOP_CONFIG).exists():
            return ws_dir
    ws_dir = root / name
    if not ws_dir.is_dir() or not (ws_dir / WORKSHOP_CONFIG).exists():
        raise WorkshopError(f"Workshop not found: {ws_dir}")
    return ws_dir


def get_workshop_info(workshop_root: str | Path) -> dict[str, Any]:
    """Get information about an existing workshop.

    Args:
        workshop_root: Path to workshop directory.

    Returns:
        dict with workshop metadata and subdirectory listing.
    """
    ws_dir = Path(workshop_root)
    config = _read_config(ws_dir)

    stl_files = sorted([f.name for f in (ws_dir / "stl").glob("*.stl")]) if (ws_dir / "stl").is_dir() else []
    case_dirs = sorted([d.name for d in (ws_dir / "cases").iterdir() if d.is_dir()]) if (ws_dir / "cases").is_dir() else []

    return {
        "workshop_root": str(ws_dir.resolve()),
        "config": config,
        "stl_files": stl_files,
        "cases": case_dirs,
    }


def list_workshops(root: str | Path) -> list[dict[str, Any]]:
    """List all workshops under root directory.

    Args:
        root: Parent directory to search for workshops.

    Returns:
        List of workshop info dicts.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    workshops = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / WORKSHOP_CONFIG).exists():
            try:
                info = get_workshop_info(d)
                workshops.append({"name": d.name, "workshop_root": str(d.resolve()), "config": info["config"]})
            except WorkshopError:
                continue
    return workshops


def delete_workshop(workshop_root: str | Path) -> dict[str, Any]:
    """Delete an existing workshop directory and all its contents.

    Args:
        workshop_root: Path to workshop directory.
    """
    ws_dir = Path(workshop_root)
    if not ws_dir.exists():
        raise WorkshopError(f"Workshop not found: {ws_dir}")
    _read_config(ws_dir)  # verify it's a workshop
    name = ws_dir.name
    shutil.rmtree(ws_dir)
    return {"deleted": str(ws_dir.resolve()), "name": name}


def get_stl_path(workshop_root: str | Path, stl_name: str) -> Path:
    """Get the path to an STL file in the workshop's stl/ directory."""
    ws_dir = Path(workshop_root)
    _read_config(ws_dir)  # verify
    stl_dir = ws_dir / "stl"
    _ensure_dir(stl_dir)
    if not stl_name.endswith(".stl"):
        stl_name = stl_name + ".stl"
    return stl_dir / stl_name


def get_case_path(workshop_root: str | Path, case_name: str) -> Path:
    """Get the path to a case directory in the workshop's cases/ directory."""
    ws_dir = Path(workshop_root)
    _read_config(ws_dir)  # verify
    cases_dir = ws_dir / "cases"
    _ensure_dir(cases_dir)
    return cases_dir / case_name
