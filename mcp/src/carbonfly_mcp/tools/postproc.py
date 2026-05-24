"""Post-processing tools – probe results, IAQ assessment, field reading."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ..errors import PostProcError
from ..workshop.manager import get_case_path, _read_config


def _find_latest_time(case_dir: Path) -> Optional[str]:
    """Find the latest time directory in a case."""
    times = []
    for d in sorted(case_dir.iterdir()):
        if d.is_dir():
            try:
                t = float(d.name)
                times.append((t, d.name))
            except ValueError:
                pass
    if not times:
        return None
    times.sort(key=lambda x: x[0])
    return times[-1][1]


def list_results(
    workshop_root: str | Path,
    case_name: str,
) -> dict:
    """List available result time directories in a case.

    Args:
        workshop_root: Workshop directory.
        case_name: Case name.

    Returns:
        dict with time directories and available fields.
    """
    case_dir = get_case_path(workshop_root, case_name)
    if not case_dir.exists():
        raise PostProcError(f"Case not found: {case_dir}")

    time_dirs = []
    for d in sorted(case_dir.iterdir()):
        if d.is_dir():
            try:
                t = float(d.name)
                fields = [f.name for f in d.iterdir() if f.is_file()]
                time_dirs.append({
                    "time": t,
                    "directory": d.name,
                    "fields": sorted(fields),
                })
            except ValueError:
                pass

    return {
        "case_name": case_name,
        "case_root": str(case_dir.resolve()),
        "time_directories": time_dirs,
    }


def probe_point(
    workshop_root: str | Path,
    case_name: str,
    point: list[float],
    field: str = "CO2",
    time: Optional[str] = None,
) -> dict:
    """Probe a single field value at a specific point from OpenFOAM results.

    This attempts to parse the field file and find the cell value nearest the point.
    For a simple implementation, it reads the internalField uniform value.

    Args:
        workshop_root: Workshop directory.
        case_name: Case name.
        point: [x, y, z] probe location in meters.
        field: Field name (e.g. 'CO2', 'T', 'U').
        time: Time directory string. If None, uses latest.

    Returns:
        dict with probe result.
    """
    case_dir = get_case_path(workshop_root, case_name)
    if not case_dir.exists():
        raise PostProcError(f"Case not found: {case_dir}")

    if time is None:
        time = _find_latest_time(case_dir)
        if time is None:
            raise PostProcError("No result time directories found.")

    field_path = case_dir / time / field
    if not field_path.exists():
        raise PostProcError(f"Field file not found: {field_path}")

    try:
        content = field_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        raise PostProcError(f"Cannot read field file: {e}")

    # Parse OpenFOAM field file to extract internalField value
    internal_value = _parse_internal_field(content)

    return {
        "case_name": case_name,
        "time": time,
        "field": field,
        "point": point,
        "internal_field_uniform_value": internal_value,
        "note": "Value is the uniform internalField. For point-specific values, use OpenFOAM probes.",
    }


def _parse_internal_field(content: str) -> Any:
    """Parse internalField value from an OpenFOAM field file.

    Handles:
    - uniform scalar: internalField uniform 0.0004;
    - uniform vector: internalField uniform (0 0 0);
    - nonuniform list: returns count
    """
    import re

    m = re.search(r"internalField\s+uniform\s+\(([^)]+)\)", content)
    if m:
        parts = m.group(1).strip().split()
        try:
            return [float(p) for p in parts]
        except ValueError:
            return m.group(1).strip()

    m = re.search(r"internalField\s+uniform\s+([^;\n]+)", content)
    if m:
        val = m.group(1).strip()
        try:
            return float(val)
        except ValueError:
            return val

    m = re.search(r"internalField\s+nonuniform\s+(\d+)", content)
    if m:
        count = int(m.group(1))
        return {"type": "nonuniform", "count": count, "note": "Non-uniform field - use OpenFOAM postProcess for sampling"}

    return None


def assess_iaq(
    workshop_root: str | Path,
    case_name: str,
    standard: str = "EN",
    co2_outdoor: float = 400.0,
    time: Optional[str] = None,
) -> dict:
    """Assess Indoor Air Quality (IAQ) from simulation results using CO2 field.

    Args:
        workshop_root: Workshop directory.
        case_name: Case name.
        standard: IAQ standard code ('EN', 'LEHB', 'SS', 'HK', 'UBA', 'DOSH', 'NBR').
        co2_outdoor: Outdoor CO2 concentration in ppm.
        time: Time directory. If None, uses latest.

    Returns:
        dict with IAQ assessment.
    """
    case_dir = get_case_path(workshop_root, case_name)
    if not case_dir.exists():
        raise PostProcError(f"Case not found: {case_dir}")

    if time is None:
        time = _find_latest_time(case_dir)
        if time is None:
            raise PostProcError("No result time directories found.")

    # Read CO2 field
    co2_path = case_dir / time / "CO2"
    if not co2_path.exists():
        raise PostProcError(f"CO2 field file not found: {co2_path}")

    co2_internal = _parse_internal_field(co2_path.read_text(encoding="utf-8", errors="ignore"))

    if co2_internal is None:
        raise PostProcError("Could not parse CO2 internalField value.")

    # CO2 is stored as mass fraction in OpenFOAM. Convert to ppm for IAQ.
    # Mass fraction to ppm: ppm = mass_fraction * 1e6 (approximate)
    # More precisely: ppm_vol = mass_fraction * (M_air / M_CO2) * 1e6
    # M_CO2 = 44.01 g/mol, M_air = 28.96 g/mol
    if isinstance(co2_internal, (int, float)):
        co2_ppm = co2_internal * (28.96 / 44.01) * 1_000_000
    elif isinstance(co2_internal, list):
        # vector field - take magnitude
        co2_ppm = sum(abs(v) for v in co2_internal) * 1_000_000
    else:
        co2_ppm = 400  # default

    # Import and run IAQ assessment
    try:
        from carbonfly.iaq import iaq_co2
    except ImportError as e:
        raise PostProcError(f"Cannot import Carbonfly IAQ module: {e}")

    report, indices = iaq_co2(co2_indoor=co2_ppm, co2_outdoor=co2_outdoor, standard=standard)

    # Map index to readable label per standard
    index_labels = _iaq_labels(standard)

    return {
        "case_name": case_name,
        "time": time,
        "standard": standard,
        "standard_description": report["standard"],
        "co2_indoor_ppm": round(co2_ppm, 1),
        "co2_outdoor_ppm": co2_outdoor,
        "iaq_index": indices[0] if indices else None,
        "iaq_label": index_labels.get(indices[0] if indices else 0, "Unknown"),
        "all_indices": indices,
    }


def _iaq_labels(standard: str) -> dict:
    """Get index -> label mapping for each standard."""
    labels = {
        "EN": {1: "Category I (best)", 2: "Category II", 3: "Category III", 4: "Category IV (worst)"},
        "LEHB": {1: "Acceptable", 2: "Unacceptable"},
        "SS": {1: "Acceptable", 2: "Unacceptable"},
        "HK": {1: "Excellent Class", 2: "Good Class", 3: "Unacceptable"},
        "UBA": {1: "Hygienically safe", 2: "Hygienically conspicuous", 3: "Hygienically unacceptable"},
        "DOSH": {1: "Acceptable", 2: "Unacceptable"},
        "NBR": {1: "Acceptable", 2: "Unacceptable"},
    }
    return labels.get(standard, {})


def read_co2_field(
    workshop_root: str | Path,
    case_name: str,
    time: Optional[str] = None,
) -> dict:
    """Read CO2 field values from simulation results.

    Args:
        workshop_root: Workshop directory.
        case_name: Case name.
        time: Time directory. If None, uses latest.

    Returns:
        dict with CO2 field data.
    """
    case_dir = get_case_path(workshop_root, case_name)
    if not case_dir.exists():
        raise PostProcError(f"Case not found: {case_dir}")

    if time is None:
        time = _find_latest_time(case_dir)
        if time is None:
            raise PostProcError("No result time directories found.")

    co2_path = case_dir / time / "CO2"
    if not co2_path.exists():
        raise PostProcError(f"CO2 field file not found: {co2_path}")

    content = co2_path.read_text(encoding="utf-8", errors="ignore")
    internal = _parse_internal_field(content)

    # Also read dimensions
    import re
    dims_match = re.search(r"dimensions\s+\[([^\]]+)\]", content)
    dimensions = dims_match.group(1).strip() if dims_match else None

    return {
        "case_name": case_name,
        "time": time,
        "field": "CO2",
        "internal_field": internal,
        "dimensions": dimensions,
        "file_path": str(co2_path.resolve()),
    }


def read_temperature_field(
    workshop_root: str | Path,
    case_name: str,
    time: Optional[str] = None,
) -> dict:
    """Read temperature field from simulation results.

    Args:
        workshop_root: Workshop directory.
        case_name: Case name.
        time: Time directory. If None, uses latest.
    """
    case_dir = get_case_path(workshop_root, case_name)
    if not case_dir.exists():
        raise PostProcError(f"Case not found: {case_dir}")

    if time is None:
        time = _find_latest_time(case_dir)
        if time is None:
            raise PostProcError("No result time directories found.")

    t_path = case_dir / time / "T"
    if not t_path.exists():
        raise PostProcError(f"Temperature field file not found: {t_path}")

    content = t_path.read_text(encoding="utf-8", errors="ignore")
    internal = _parse_internal_field(content)

    return {
        "case_name": case_name,
        "time": time,
        "field": "T",
        "internal_field": internal,
        "file_path": str(t_path.resolve()),
    }
