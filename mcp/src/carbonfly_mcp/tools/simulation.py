"""Simulation tools – case generation, mesh, and solver execution via WSL.

Handles the full CFD workflow without Rhino dependency:
1. Generate OpenFOAM case files using Carbonfly writers
2. Run meshing (blockMesh + snappyHexMesh) headlessly via WSL
3. Run solver (buoyantReactingFoam) headlessly via WSL
4. Check status and read logs
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from ..errors import SimulationError, WslError
from ..workshop.manager import _read_config, get_case_path

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # carbonfly-mcp root


# ---- Path helpers ----

def win_to_wsl_path(p: str) -> str:
    """Convert Windows path to WSL path."""
    p = str(p).replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        return f"/mnt/{p[0].lower()}/{p[2:]}"
    return p



# ---- WSL headless utilities ----

def _is_wsl_available() -> bool:
    """Check if wsl.exe is available and functional on the system."""
    try:
        result = subprocess.run(
            ["wsl.exe", "--", "echo", "OK"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0 and "OK" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def run_wsl_headless(
    command: str,
    *,
    cwd_win: Optional[Path | str] = None,
    foam_bashrc: str = "/opt/openfoam10/etc/bashrc",
    distro: Optional[str] = None,
    timeout: Optional[int] = None,
) -> dict:
    """Run a command inside WSL headlessly and return stdout, stderr, returncode.

    Args:
        command: Bash command to run inside WSL.
        cwd_win: Working directory on Windows (converted to WSL path for cd).
        foam_bashrc: Path to OpenFOAM bashrc to source.
        distro: WSL distro name. Uses default if None.
        timeout: Timeout in seconds for the subprocess.

    Returns:
        dict with keys: returncode, stdout, stderr.
    """
    inner_parts = []

    if cwd_win:
        cwd_wsl = win_to_wsl_path(str(cwd_win))
        inner_parts.append(f"cd {shlex.quote(cwd_wsl)}")

    inner_parts.append(f'source "{foam_bashrc}" >/dev/null 2>&1 || true')
    inner_parts.append(command)
    inner = " && ".join(inner_parts)

    wsl_argv = ["wsl.exe"]
    if distro:
        wsl_argv += ["-d", distro]
    wsl_argv += ["--", "bash", "-lc", inner]

    try:
        result = subprocess.run(
            wsl_argv,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
        }
    except FileNotFoundError:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "wsl.exe not found — WSL is not installed",
        }


# ---- Environment check ----

def check_environment(
    distro: Optional[str] = None,
    foam_bashrc: str = "/opt/openfoam10/etc/bashrc",
) -> dict[str, Any]:
    """Check if WSL and OpenFOAM are available.

    Args:
        distro: WSL distro name.
        foam_bashrc: Path to OpenFOAM bashrc in WSL.

    Returns:
        dict with status of each component.
    """
    wsl_ok = _is_wsl_available()
    of_ok = False
    of_version = None

    if wsl_ok:
        result = run_wsl_headless(
            "blockMesh -help 2>&1 | head -1 || echo NOTFOUND",
            foam_bashrc=foam_bashrc,
            distro=distro,
            timeout=30,
        )
        of_ok = "NOTFOUND" not in result.get("stdout", "")
        if of_ok:
            for line in result.get("stdout", "").splitlines():
                if "version" in line.lower() or "OpenFOAM" in line:
                    of_version = line.strip()
                    break

    return {
        "wsl_available": wsl_ok,
        "openfoam_available": of_ok,
        "openfoam_version": of_version,
        "platform": os.name,
    }


# ---- Case generation ----

def _parse_stl_facets(stl_path: Path) -> list[list[float]]:
    """Extract all vertices from an ASCII STL file."""
    vertices = []
    with open(stl_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.strip().startswith("vertex"):
                parts = line.strip().split()
                if len(parts) >= 4:
                    vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
    return vertices


def _all_stl_bounds(stl_dir: Path, stl_names: list[str]) -> tuple[list[float], list[float]]:
    """Compute union bounding box for all STL files."""
    all_verts = []
    for name in stl_names:
        stl_path = stl_dir / name
        if stl_path.exists():
            verts = _parse_stl_facets(stl_path)
            all_verts.extend(verts)
    if not all_verts:
        raise SimulationError("No STL geometry found to compute bounds.")

    xs = [v[0] for v in all_verts]
    ys = [v[1] for v in all_verts]
    zs = [v[2] for v in all_verts]
    return [min(xs), min(ys), min(zs)], [max(xs), max(ys), max(zs)]


def generate_case(
    workshop_root: str | Path,
    case_name: str,
    *,
    stl_files: Optional[list[str]] = None,
    simulation_type: str = "transient",
    cell_size_m: float = 0.25,
    padding_m: float = 1.0,
    snap: bool = False,
    end_time: float = 120.0,
    delta_t: float = 0.01,
    write_interval: float = 10.0,
    internal_temperature: float = 293.15,
    internal_co2_fraction: float = 0.0004,
    internal_velocity: Optional[list[float]] = None,
    fv_mode: str = "transient",
    distro: Optional[str] = None,
    foam_bashrc: str = "/opt/openfoam10/etc/bashrc",
) -> dict:
    """Generate an OpenFOAM case from workshop geometry and boundary config.

    This function writes all necessary OpenFOAM dictionaries and field files,
    using the STL geometry and boundary configurations stored in the workshop.

    Args:
        workshop_root: Workshop directory path.
        case_name: Name for the case directory.
        stl_files: List of STL filenames to include. If None, uses all STLs in workshop.
        simulation_type: 'steady' or 'transient'.
        cell_size_m: Target cell size in meters.
        padding_m: Extra padding around geometry for blockMesh.
        snap: Enable snapping in snappyHexMesh.
        end_time: Simulation end time (for controlDict).
        delta_t: Time step (for transient).
        write_interval: Result write interval.
        internal_temperature: Initial internal temperature (K).
        internal_co2_fraction: Initial internal CO2 mass fraction.
        internal_velocity: Initial internal velocity vector [Ux, Uy, Uz].
        fv_mode: FV template mode ('transient' or 'steadystate').
        distro: WSL distro name.
        foam_bashrc: OpenFOAM bashrc path in WSL.

    Returns:
        dict with case paths, logs, and next steps.
    """
    ws_dir = Path(workshop_root)
    _read_config(ws_dir)  # verify workshop
    stl_dir = ws_dir / "stl"

    # Determine which STL files to use
    if stl_files is None:
        stl_files = sorted([f.name for f in stl_dir.glob("*.stl")])
    if not stl_files:
        raise SimulationError("No STL files found in workshop.")

    # Validate STL files exist
    for sf in stl_files:
        if not (stl_dir / sf).exists():
            raise SimulationError(f"STL file not found: {sf}")

    case_dir = get_case_path(workshop_root, case_name)
    case_dir.mkdir(parents=True, exist_ok=True)

    # Setup OpenFOAM standard directories
    (case_dir / "0").mkdir(exist_ok=True)
    (case_dir / "system").mkdir(exist_ok=True)
    const_tri = case_dir / "constant" / "triSurface"
    const_tri.mkdir(parents=True, exist_ok=True)

    logs = []

    # 1. Copy STL files to case
    for sf in stl_files:
        dest = const_tri / sf
        if not dest.exists() or dest.stat().st_mtime < (stl_dir / sf).stat().st_mtime:
            shutil.copy2(stl_dir / sf, dest)
            logs.append(f"Copied STL: {sf}")

    # 2. Compute bounds and write blockMeshDict
    min_bnd, max_bnd = _all_stl_bounds(stl_dir, stl_files)
    min_bnd = [min_bnd[0] - padding_m, min_bnd[1] - padding_m, min_bnd[2] - padding_m]
    max_bnd = [max_bnd[0] + padding_m, max_bnd[1] + padding_m, max_bnd[2] + padding_m]

    # Import Carbonfly's writers
    try:
        from carbonfly.blockmesh_writer import write_blockmesh_dict
        from carbonfly.snappy_writer import write_surface_features_dict, write_snappy_geometry
        from carbonfly.constant_writer import write_constant_files, write_residuals_file
        from carbonfly.fv_writer import copy_fv_templates_to_case, get_template_path
        from carbonfly.control_dict import write_control_dict, STEADY_DEFAULT, TRANSIENT_DEFAULT
        from carbonfly.utils import foam_header
    except ImportError as e:
        raise SimulationError(f"Cannot import Carbonfly library. Ensure the carbonfly package is in sys.path: {e}")

    bm_path = write_blockmesh_dict(
        case_dir,
        min_xyz=tuple(min_bnd),
        max_xyz=tuple(max_bnd),
        cell_size=cell_size_m,
        convert_to_meters=1.0,
    )
    logs.append(f"Written: blockMeshDict (bounds: {min_bnd} -> {max_bnd})")

    # 3. Write snappyHexMesh dictionaries
    stl_main = stl_files[0]  # use first STL as main
    write_surface_features_dict(case_dir, stl_main)
    logs.append("Written: surfaceFeaturesDict")

    # Build region info from STL solid names
    region_names = [Path(sf).stem for sf in stl_files]
    region_levels = {rn: (0, 2) for rn in region_names}  # default refinement

    write_snappy_geometry(
        case_dir,
        stl_main,
        regions=region_names,
        region_levels=region_levels,
        snap=snap,
    )
    logs.append(f"Written: snappyHexMeshDict ({len(region_names)} regions)")

    # 4. Write constant files
    write_constant_files(case_dir)
    write_residuals_file(case_dir)
    logs.append("Written: constant/ files + residuals")

    # 5. Copy FV templates
    fvSchemes_src = get_template_path("fvSchemes", fv_mode)
    fvSolution_src = get_template_path("fvSolution", fv_mode)
    copy_fv_templates_to_case(case_dir, fvSchemes_src=fvSchemes_src, fvSolution_src=fvSolution_src)
    logs.append(f"Written: fvSchemes, fvSolution (mode={fv_mode})")

    # 6. Write controlDict
    cd_overrides = {
        "endTime": end_time,
        "deltaT": delta_t,
        "writeInterval": write_interval,
    }
    if simulation_type == "steady":
        base = STEADY_DEFAULT.copy()
    else:
        base = TRANSIENT_DEFAULT.copy()
    base.update(cd_overrides)
    write_control_dict(case_dir, base)
    logs.append(f"Written: controlDict (type={simulation_type}, endTime={end_time})")

    # 7. Write field files (0/U, 0/T, 0/CO2, 0/p, etc.)
    # Load boundary configuration
    bp = ws_dir / "boundaries.json"
    boundaries = {}
    if bp.exists():
        boundaries = json.loads(bp.read_text(encoding="utf-8")).get("boundaries", {})

    # Keys that require the 'uniform' keyword before their value in OpenFOAM syntax
    _UNIFORM_VALUE_KEYS = {"value", "inletValue", "p0", "h", "Ta", "mixingLength", "intensity", "emissivity"}

    def _dict_to_of_block(spec: dict, indent: str = "        ") -> str:
        """Convert a plain dict boundary spec to OpenFOAM field block text."""
        lines = []
        for key, val in spec.items():
            if key == "code":
                lines.append(f"{indent}{key} {val}")
            elif isinstance(val, (list, tuple)):
                inner = "(" + " ".join(str(v) for v in val) + ")"
                uniform = "uniform " if key in _UNIFORM_VALUE_KEYS else ""
                lines.append(f"{indent}{key}\t\t{uniform}{inner};")
            elif isinstance(val, str):
                lines.append(f"{indent}{key}\t\t{val};")
            elif isinstance(val, bool):
                lines.append(f"{indent}{key}\t\t{'true' if val else 'false'};")
            else:
                uniform = "uniform " if key in _UNIFORM_VALUE_KEYS else ""
                lines.append(f"{indent}{key}\t\t{uniform}{val};")
        return "\n".join(lines)

    def _write_field_file(field_name, is_vector, internal_value, dimensions):
        """Write a single 0/ field file."""
        out = case_dir / "0" / field_name
        OFclass = "volVectorField" if is_vector else "volScalarField"
        header = foam_header(field_name, OFclass, location="0")
        lines = [header]
        lines.append(f"dimensions      {dimensions};")
        if is_vector and isinstance(internal_value, (list, tuple)):
            lines.append(f"internalField   uniform ({internal_value[0]} {internal_value[1]} {internal_value[2]});")
        else:
            lines.append(f"internalField   uniform {internal_value};")
        lines.append("\nboundaryField\n{")

        # Write each configured patch
        for patch_name, bcfg in boundaries.items():
            fields = bcfg.get("fields", {})
            if field_name in fields:
                lines.append(f"    {patch_name}\n    {{")
                lines.append(_dict_to_of_block(fields[field_name]))
                lines.append("    }")

        # Write boundingbox wall patch
        if field_name == "U":
            bb_spec = "        type noSlip;\n"
        elif field_name in ("T", "CO2"):
            bb_spec = "        type zeroGradient;\n"
        elif field_name in ("p", "p_rgh"):
            bb_spec = "        type fixedFluxPressure;\n        value $internalField;\n"
        elif field_name == "k":
            bb_spec = "        type kqRWallFunction;\n        value 1e-6;\n"
        elif field_name == "epsilon":
            bb_spec = "        type epsilonWallFunction;\n        value 1e-6;\n"
        elif field_name == "nut":
            bb_spec = "        type nutkWallFunction;\n        value 0;\n"
        elif field_name == "alphat":
            bb_spec = "        type compressible::alphatJayatillekeWallFunction;\n        value 0;\n        Prt 0.85;\n"
        else:
            bb_spec = "        type zeroGradient;\n"
        lines.append(f"    boundingbox\n    {{\n{bb_spec}    }}")

        lines.append("}")
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Field dimensions for buoyantReactingFoam
    field_dims = {
        "U":       "[0 1 -1 0 0 0 0]",
        "T":       "[0 0 0 1 0 0 0]",
        "CO2":     "[0 0 0 0 0 0 0]",
        "p":       "[1 -1 -2 0 0 0 0]",
        "p_rgh":   "[1 -1 -2 0 0 0 0]",
        "k":       "[0 2 -2 0 0 0 0]",
        "epsilon": "[0 2 -3 0 0 0 0]",
        "nut":     "[0 2 -1 0 0 0 0]",
        "alphat":  "[1 -1 -1 0 0 0 0]",
    }

    if internal_velocity is None:
        internal_velocity = [0.0, 0.0, 0.0]

    _write_field_file("U", True, internal_velocity, field_dims["U"])
    _write_field_file("T", False, internal_temperature, field_dims["T"])
    _write_field_file("CO2", False, internal_co2_fraction, field_dims["CO2"])
    _write_field_file("p", False, 101325.0, field_dims["p"])
    _write_field_file("p_rgh", False, 0.0, field_dims["p_rgh"])
    _write_field_file("k", False, 1e-6, field_dims["k"])
    _write_field_file("epsilon", False, 1e-6, field_dims["epsilon"])
    _write_field_file("nut", False, 0.0, field_dims["nut"])
    _write_field_file("alphat", False, 0.0, field_dims["alphat"])
    logs.append("Written: 0/ (U, T, CO2, p, p_rgh, k, epsilon, nut, alphat)")

    # Write ParaView marker
    marker = case_dir / f"{case_name}.foam"
    if not marker.exists():
        marker.write_text("// carbonfly ParaView marker\n", encoding="utf-8")
    logs.append(f"Written: {case_name}.foam marker")

    return {
        "status": "generated",
        "case_root": str(case_dir.resolve()),
        "case_name": case_name,
        "workshop_root": str(ws_dir.resolve()),
        "stl_files": stl_files,
        "domain_bounds_m": {
            "min": [round(x, 4) for x in min_bnd],
            "max": [round(x, 4) for x in max_bnd],
        },
        "boundaries_configured": len(boundaries),
        "simulation_type": simulation_type,
        "logs": logs,
        "next_steps": [
            f"Run meshing: call run_meshing(workshop_root='{ws_dir}', case_name='{case_name}')",
            f"Run simulation: call run_simulation(workshop_root='{ws_dir}', case_name='{case_name}')",
        ],
    }


# ---- Running commands ----

def run_blockmesh(
    workshop_root: str | Path,
    case_name: str,
    *,
    distro: Optional[str] = None,
    foam_bashrc: str = "/opt/openfoam10/etc/bashrc",
    timeout: int = 120,
) -> dict:
    """Run blockMesh on the case."""
    case_dir = get_case_path(workshop_root, case_name)
    if not case_dir.exists():
        raise SimulationError(f"Case not found: {case_dir}")

    result = run_wsl_headless(
        "blockMesh -case . 2>&1",
        cwd_win=case_dir,
        foam_bashrc=foam_bashrc,
        distro=distro,
        timeout=timeout,
    )

    success = result["returncode"] == 0
    return {
        "status": "completed" if success else "failed",
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "case_name": case_name,
    }


def run_surface_features(
    workshop_root: str | Path,
    case_name: str,
    *,
    distro: Optional[str] = None,
    foam_bashrc: str = "/opt/openfoam10/etc/bashrc",
    timeout: int = 120,
) -> dict:
    """Run surfaceFeatures on the case."""
    case_dir = get_case_path(workshop_root, case_name)
    if not case_dir.exists():
        raise SimulationError(f"Case not found: {case_dir}")

    result = run_wsl_headless(
        "surfaceFeatures 2>&1",
        cwd_win=case_dir,
        foam_bashrc=foam_bashrc,
        distro=distro,
        timeout=timeout,
    )

    success = result["returncode"] == 0
    return {
        "status": "completed" if success else "failed",
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


def run_snappy(
    workshop_root: str | Path,
    case_name: str,
    *,
    distro: Optional[str] = None,
    foam_bashrc: str = "/opt/openfoam10/etc/bashrc",
    timeout: int = 600,
) -> dict:
    """Run snappyHexMesh on the case."""
    case_dir = get_case_path(workshop_root, case_name)
    if not case_dir.exists():
        raise SimulationError(f"Case not found: {case_dir}")

    result = run_wsl_headless(
        "snappyHexMesh -overwrite 2>&1",
        cwd_win=case_dir,
        foam_bashrc=foam_bashrc,
        distro=distro,
        timeout=timeout,
    )

    success = result["returncode"] == 0
    return {
        "status": "completed" if success else "failed",
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


def run_meshing(
    workshop_root: str | Path,
    case_name: str,
    *,
    distro: Optional[str] = None,
    foam_bashrc: str = "/opt/openfoam10/etc/bashrc",
) -> dict:
    """Run full meshing pipeline: blockMesh -> surfaceFeatures -> snappyHexMesh -> checkMesh.

    Args:
        workshop_root: Workshop directory.
        case_name: Case name.
        distro: WSL distro.
        foam_bashrc: OpenFOAM bashrc path.

    Returns:
        dict with results for each step.
    """
    results = {}

    # blockMesh
    bm = run_blockmesh(workshop_root, case_name, distro=distro, foam_bashrc=foam_bashrc)
    results["blockMesh"] = bm
    if bm["returncode"] != 0:
        results["status"] = "failed_at_blockMesh"
        return results

    # surfaceFeatures
    sf = run_surface_features(workshop_root, case_name, distro=distro, foam_bashrc=foam_bashrc)
    results["surfaceFeatures"] = sf
    if sf["returncode"] != 0:
        results["status"] = "failed_at_surfaceFeatures"
        return results

    # snappyHexMesh
    shm = run_snappy(workshop_root, case_name, distro=distro, foam_bashrc=foam_bashrc)
    results["snappyHexMesh"] = shm
    if shm["returncode"] != 0:
        results["status"] = "failed_at_snappyHexMesh"
        return results

    results["status"] = "completed"
    return results


def run_simulation(
    workshop_root: str | Path,
    case_name: str,
    *,
    distro: Optional[str] = None,
    foam_bashrc: str = "/opt/openfoam10/etc/bashrc",
    timeout: int = 3600,
) -> dict:
    """Run buoyantReactingFoam solver on the case (headless).

    Args:
        workshop_root: Workshop directory.
        case_name: Case name.
        distro: WSL distro.
        foam_bashrc: OpenFOAM bashrc path.
        timeout: Timeout in seconds (default 1 hour).

    Returns:
        dict with run results.
    """
    case_dir = get_case_path(workshop_root, case_name)
    if not case_dir.exists():
        raise SimulationError(f"Case not found: {case_dir}")

    result = run_wsl_headless(
        "buoyantReactingFoam 2>&1",
        cwd_win=case_dir,
        foam_bashrc=foam_bashrc,
        distro=distro,
        timeout=timeout,
    )

    success = result["returncode"] == 0
    return {
        "status": "completed" if success else "failed",
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "case_name": case_name,
        "case_root": str(case_dir.resolve()),
    }


def get_simulation_status(
    workshop_root: str | Path,
    case_name: str,
    *,
    distro: Optional[str] = None,
    foam_bashrc: str = "/opt/openfoam10/etc/bashrc",
) -> dict:
    """Check the status of a simulation by reading log files.

    Args:
        workshop_root: Workshop directory.
        case_name: Case name.
        distro: WSL distro.
        foam_bashrc: OpenFOAM bashrc path.

    Returns:
        dict with status, log info, and result directories.
    """
    case_dir = get_case_path(workshop_root, case_name)
    if not case_dir.exists():
        raise SimulationError(f"Case not found: {case_dir}")

    info = {
        "case_name": case_name,
        "case_root": str(case_dir.resolve()),
    }

    # Check for time directories (results)
    time_dirs = []
    for d in sorted(case_dir.iterdir()):
        if d.is_dir() and d.name not in ("0", "system", "constant", "postProcessing", "processor0"):
            try:
                float(d.name)
                time_dirs.append(d.name)
            except ValueError:
                pass

    info["time_directories"] = time_dirs
    info["has_results"] = len(time_dirs) > 1  # more than just 0/

    # Check if simulation is running
    result = run_wsl_headless(
        "pgrep -f buoyantReactingFoam 2>/dev/null && echo RUNNING || echo NOT_RUNNING",
        cwd_win=case_dir,
        foam_bashrc=foam_bashrc,
        distro=distro,
        timeout=10,
    )
    info["simulation_running"] = "RUNNING" in result.get("stdout", "")

    # Read log file if available
    log_file = case_dir / "log.buoyantReactingFoam"
    if log_file.exists():
        log_content = log_file.read_text(encoding="utf-8", errors="ignore")
        lines = log_content.strip().splitlines()
        info["log_lines"] = len(lines)
        info["log_tail"] = lines[-20:] if len(lines) > 20 else lines
    else:
        info["log_lines"] = 0
        info["log_tail"] = []

    return info
