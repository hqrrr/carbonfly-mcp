"""Boundary condition tools for Carbonfly MCP.

Configure OpenFOAM boundary conditions for patches without Rhino dependency.
Boundary conditions are stored as plain dicts in a JSON file in the workshop.
The patch name is always derived from the STL file stem for consistency with
snappyHexMesh region naming (OpenFOAM derives patch names from STL solid names).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..workshop.manager import _read_config


BOUNDARY_STATE_FILE = "boundaries.json"


def _boundary_path(workshop_root: Path) -> Path:
    """Get path to boundaries state file in a workshop."""
    return Path(workshop_root) / BOUNDARY_STATE_FILE


def _load_boundaries(workshop_root: Path) -> dict[str, Any]:
    """Load boundary configuration from workshop."""
    bp = _boundary_path(workshop_root)
    if bp.exists():
        return json.loads(bp.read_text(encoding="utf-8"))
    return {"boundaries": {}}


def _save_boundaries(workshop_root: Path, data: dict[str, Any]):
    """Save boundary configuration to workshop."""
    bp = _boundary_path(workshop_root)
    bp.write_text(json.dumps(data, indent=2), encoding="utf-8")


def configure_inlet(
    workshop_root: str | Path,
    stl_name: str,
    velocity: tuple[float, float, float] = (0, 0, 1),
    temperature: float = 293.15,
    co2_fraction: float = 0.0004,
    turbulence_intensity: float = 0.14,
    mixing_length: float = 0.0168,
) -> dict:
    """Configure a velocity inlet boundary.

    Args:
        workshop_root: Workshop directory.
        stl_name: Name of the STL file (geometry name) to bind. The patch name
            is derived from the STL file stem.
        velocity: (Ux, Uy, Uz) velocity vector in m/s.
        temperature: Temperature in Kelvin.
        co2_fraction: CO2 mass fraction (e.g. 0.0004 = 400 ppm equivalent).
        turbulence_intensity: Turbulence intensity (0-1).
        mixing_length: Turbulent mixing length (m).

    Returns:
        dict with boundary configuration.
    """
    ws_dir = Path(workshop_root)
    _read_config(ws_dir)  # verify workshop

    if not stl_name.endswith(".stl"):
        stl_name = stl_name + ".stl"

    patch = Path(stl_name).stem

    config = {
        "stl_name": stl_name,
        "patch_name": patch,
        "type": "inletVelocity",
        "fields": {
            "U": {
                "type": "fixedValue",
                "value": list(velocity),
            },
            "T": {
                "type": "fixedValue",
                "value": temperature,
            },
            "CO2": {
                "type": "fixedValue",
                "value": co2_fraction,
            },
            "p_rgh": {
                "type": "fixedFluxPressure",
            },
            "p": {
                "type": "calculated",
                "value": "$internalField",
            },
            "k": {
                "type": "turbulentIntensityKineticEnergyInlet",
                "intensity": turbulence_intensity,
                "value": 0.0,
            },
            "epsilon": {
                "type": "turbulentMixingLengthDissipationRateInlet",
                "value": 0.0,
                "mixingLength": mixing_length,
            },
            "alphat": {
                "type": "calculated",
                "value": 0.0,
            },
        },
    }

    data = _load_boundaries(ws_dir)
    data["boundaries"][patch] = config
    _save_boundaries(ws_dir, data)

    return {"status": "configured", "boundary": config}


def configure_outlet(
    workshop_root: str | Path,
    stl_name: str,
    pressure: float = 0.0,
    temperature: float = 293.15,
    co2_fraction: float = 0.0004,
) -> dict:
    """Configure a pressure outlet boundary.

    Args:
        workshop_root: Workshop directory.
        stl_name: STL file name to bind. Patch name derived from STL stem.
        pressure: Outlet pressure (Pa gauge).
        temperature: Backflow temperature in Kelvin.
        co2_fraction: Backflow CO2 mass fraction.

    Returns:
        dict with boundary configuration.
    """
    ws_dir = Path(workshop_root)
    _read_config(ws_dir)

    if not stl_name.endswith(".stl"):
        stl_name = stl_name + ".stl"

    patch = Path(stl_name).stem

    config = {
        "stl_name": stl_name,
        "patch_name": patch,
        "type": "outletPressure",
        "fields": {
            "U": {
                "type": "pressureInletOutletVelocity",
                "inletValue": [0, 0, 0],
                "value": [0, 0, 0],
            },
            "T": {
                "type": "inletOutlet",
                "inletValue": temperature,
                "value": temperature,
            },
            "CO2": {
                "type": "inletOutlet",
                "inletValue": co2_fraction,
                "value": co2_fraction,
            },
            "p_rgh": {
                "type": "totalPressure",
                "p0": pressure,
                "value": pressure,
            },
            "p": {
                "type": "calculated",
                "value": "$internalField",
            },
            "k": {
                "type": "inletOutlet",
                "inletValue": "$internalField",
                "value": "$internalField",
            },
            "epsilon": {
                "type": "inletOutlet",
                "inletValue": "$internalField",
                "value": "$internalField",
            },
            "alphat": {
                "type": "calculated",
                "value": 0.0,
            },
        },
    }

    data = _load_boundaries(ws_dir)
    data["boundaries"][patch] = config
    _save_boundaries(ws_dir, data)

    return {"status": "configured", "boundary": config}


def configure_wall(
    workshop_root: str | Path,
    stl_name: str,
    temperature: float = 293.15,
    heat_transfer_coefficient: float = 0.0,
) -> dict:
    """Configure a wall boundary.

    Args:
        workshop_root: Workshop directory.
        stl_name: STL file name to bind. Patch name derived from STL stem.
        temperature: Wall temperature (K), used when h > 0.
        heat_transfer_coefficient: External heat transfer coefficient. 0 = adiabatic.

    Returns:
        dict with boundary configuration.
    """
    ws_dir = Path(workshop_root)
    _read_config(ws_dir)

    if not stl_name.endswith(".stl"):
        stl_name = stl_name + ".stl"

    patch = Path(stl_name).stem

    fields = {
        "U": {"type": "noSlip"},
        "CO2": {"type": "zeroGradient"},
        "p": {"type": "zeroGradient"},
        "p_rgh": {"type": "fixedFluxPressure"},
        "k": {"type": "kqRWallFunction", "value": 0.0},
        "epsilon": {"type": "epsilonWallFunction", "value": 0.0},
        "nut": {"type": "nutkWallFunction", "value": 0.0},
        "alphat": {
            "type": "compressible::alphatJayatillekeWallFunction",
            "value": 0.0,
            "Prt": 0.85,
        },
        "G": {"type": "MarshakRadiation", "emissivityMode": "lookup", "emissivity": 0.98, "value": 0.0},
    }

    if heat_transfer_coefficient > 0:
        fields["T"] = {
            "type": "externalWallHeatFluxTemperature",
            "mode": "coefficient",
            "h": heat_transfer_coefficient,
            "Ta": temperature,
            "value": temperature,
        }
    else:
        fields["T"] = {"type": "zeroGradient"}

    config = {
        "stl_name": stl_name,
        "patch_name": patch,
        "type": "wall",
        "fields": fields,
    }

    data = _load_boundaries(ws_dir)
    data["boundaries"][patch] = config
    _save_boundaries(ws_dir, data)

    return {"status": "configured", "boundary": config}


def configure_dynamic_respiration(
    workshop_root: str | Path,
    stl_name: str,
    freq: float = 12.0,
    minute_vent_L_min: float = 7.2,
    temperature: float = 307.15,
    co2_fraction: float = 0.04,
) -> dict:
    """Configure a dynamic respiration boundary (sinusoidal velocity).

    Uses OpenFOAM codedFixedValue for time-varying velocity.

    Args:
        workshop_root: Workshop directory.
        stl_name: STL file name to bind. Patch name derived from STL stem.
        freq: Breathing frequency (breaths/min).
        minute_vent_L_min: Minute ventilation (L/min).
        temperature: Exhaled air temperature (K).
        co2_fraction: Exhaled CO2 mass fraction.

    Returns:
        dict with boundary configuration.
    """
    ws_dir = Path(workshop_root)
    _read_config(ws_dir)

    if not stl_name.endswith(".stl"):
        stl_name = stl_name + ".stl"

    patch = Path(stl_name).stem

    VE_m3_s = (minute_vent_L_min / 1000.0) / 60.0
    freq_hz = freq / 60.0

    code = (
        f"#{{\n"
        f"    const fvPatch& p = patch();\n"
        f"    const vectorField n = p.nf();\n"
        f"    const scalar A = gSum(mag(p.Sf()));\n"
        f"    const scalar f = {freq_hz};\n"
        f"    const scalar VE = {VE_m3_s};\n"
        f"    const scalar U0 = constant::mathematical::pi * VE / A;\n"
        f"    const scalar t = this->db().time().value();\n"
        f"    const scalar Un = U0 * sin(2.0 * constant::mathematical::pi * f * t);\n"
        f"    vectorField V(p.size(), vector::zero);\n"
        f"    forAll(V, i) {{ V[i] = n[i] * Un; }}\n"
        f"    operator==(V);\n"
        f"    fixedValueFvPatchVectorField::updateCoeffs();\n"
        f"#}};"
    )

    config = {
        "stl_name": stl_name,
        "patch_name": patch,
        "type": "dynamicRespiration",
        "frequency_bpm": freq,
        "minute_vent_L_min": minute_vent_L_min,
        "fields": {
            "U": {
                "type": "codedFixedValue",
                "value": "uniform (0 0 0)",
                "name": "breathingSine",
                "code": code,
            },
            "T": {
                "type": "fixedValue",
                "value": temperature,
            },
            "CO2": {
                "type": "fixedValue",
                "value": co2_fraction,
            },
            "p_rgh": {
                "type": "fixedFluxPressure",
            },
            "p": {
                "type": "calculated",
                "value": "$internalField",
            },
            "k": {
                "type": "kqRWallFunction",
                "value": 0.0,
            },
            "epsilon": {
                "type": "epsilonWallFunction",
                "value": 0.0,
            },
            "nut": {
                "type": "nutkWallFunction",
                "value": 0.0,
            },
            "alphat": {
                "type": "compressible::alphatJayatillekeWallFunction",
                "value": 0.0,
                "Prt": 0.85,
            },
            "G": {
                "type": "MarshakRadiation",
                "emissivityMode": "lookup",
                "emissivity": 0.98,
                "value": 0.0,
            },
        },
    }

    data = _load_boundaries(ws_dir)
    data["boundaries"][patch] = config
    _save_boundaries(ws_dir, data)

    return {"status": "configured", "boundary": config}


def configure_recirculation(
    workshop_root: str | Path,
    supply_stl: str,
    return_stl: str,
    velocity: tuple[float, float, float] = (0, 0, 1),
    temperature: float = 293.15,
) -> dict:
    """Configure recirculated supply & return boundary pair.

    The supply CO2 is dynamically set to the area-weighted average CO2 on the return patch.
    Patch names are derived from STL file stems.

    Args:
        workshop_root: Workshop directory.
        supply_stl: STL name for the supply patch.
        return_stl: STL name for the return patch (to sample CO2 from).
        velocity: Supply velocity vector (m/s).
        temperature: Supply temperature (K).

    Returns:
        dict with boundary configurations for both patches.
    """
    ws_dir = Path(workshop_root)
    _read_config(ws_dir)

    if not supply_stl.endswith(".stl"):
        supply_stl = supply_stl + ".stl"
    if return_stl and not return_stl.endswith(".stl"):
        return_stl = return_stl + ".stl"

    sp = Path(supply_stl).stem
    rp = Path(return_stl).stem if return_stl else sp + "_return"

    co2_code = (
        f"#{{\n"
        f"    const label srcPid = this->patch().boundaryMesh().findPatchID(\"{rp}\");\n"
        f"    if (srcPid < 0)\n"
        f"    {{\n"
        f"        FatalErrorInFunction\n"
        f"            << \"Cannot find source patch '{rp}'\" << nl\n"
        f"            << abort(FatalError);\n"
        f"    }}\n"
        f"    const volScalarField& CO2 = this->db().lookupObject<volScalarField>(\"CO2\");\n"
        f"    const fvPatchScalarField& srcPf = CO2.boundaryField()[srcPid];\n"
        f"    const scalarField srcVals(srcPf);\n"
        f"    if (srcVals.empty())\n"
        f"    {{\n"
        f"        FatalErrorInFunction\n"
        f"            << \"Source patch '{rp}' has zero faces\" << nl\n"
        f"            << abort(FatalError);\n"
        f"    }}\n"
        f"    const fvPatch& srcPatch = CO2.mesh().boundary()[srcPid];\n"
        f"    const scalarField A(mag(srcPatch.Sf()));\n"
        f"    const scalar num = gSum(srcVals * A);\n"
        f"    const scalar den = gSum(A);\n"
        f"    const scalar avgCO2 = (den > SMALL) ? (num/den) : (gSum(srcVals)/srcVals.size());\n"
        f"    operator==(avgCO2);\n"
        f"    fixedValueFvPatchScalarField::updateCoeffs();\n"
        f"#}};"
    )

    supply_config = {
        "stl_name": supply_stl,
        "patch_name": sp,
        "type": "recirculationSupply",
        "fields": {
            "U": {"type": "fixedValue", "value": list(velocity)},
            "T": {"type": "fixedValue", "value": temperature},
            "CO2": {
                "type": "codedFixedValue",
                "value": "$internalField",
                "name": "co2FromPatchAvg",
                "code": co2_code,
            },
            "p_rgh": {"type": "fixedFluxPressure"},
            "p": {"type": "calculated", "value": "$internalField"},
            "k": {"type": "turbulentIntensityKineticEnergyInlet", "intensity": 0.14, "value": 0.0},
            "epsilon": {"type": "turbulentMixingLengthDissipationRateInlet", "value": 0.0, "mixingLength": 0.0168},
            "alphat": {"type": "calculated", "value": 0.0},
        },
    }

    return_config = {
        "stl_name": return_stl,
        "patch_name": rp,
        "type": "recirculationReturn",
        "fields": {
            "U": {"type": "pressureInletOutletVelocity", "inletValue": (0, 0, 0), "value": (0, 0, 0)},
            "T": {"type": "inletOutlet", "inletValue": temperature, "value": temperature},
            "CO2": {"type": "zeroGradient"},
            "p_rgh": {"type": "totalPressure", "p0": "$internalField", "value": "$internalField"},
            "p": {"type": "calculated", "value": "$internalField"},
            "k": {"type": "inletOutlet", "inletValue": "$internalField", "value": "$internalField"},
            "epsilon": {"type": "inletOutlet", "inletValue": "$internalField", "value": "$internalField"},
            "alphat": {"type": "calculated", "value": 0.0},
        },
    }

    data = _load_boundaries(ws_dir)
    data["boundaries"][sp] = supply_config
    data["boundaries"][rp] = return_config
    _save_boundaries(ws_dir, data)

    return {
        "status": "configured",
        "supply": supply_config,
        "return": return_config,
    }


def list_boundaries(workshop_root: str | Path) -> dict:
    """List all configured boundaries in the workshop.

    Args:
        workshop_root: Workshop directory path.

    Returns:
        dict with boundaries.
    """
    ws_dir = Path(workshop_root)
    _read_config(ws_dir)
    data = _load_boundaries(ws_dir)
    return {"workshop_root": str(ws_dir.resolve()), "boundaries": data.get("boundaries", {})}


def clear_boundaries(workshop_root: str | Path) -> dict:
    """Clear all boundary configurations from the workshop.

    Args:
        workshop_root: Workshop directory path.
    """
    ws_dir = Path(workshop_root)
    _read_config(ws_dir)
    _save_boundaries(ws_dir, {"boundaries": {}})
    return {"status": "cleared", "workshop_root": str(ws_dir.resolve())}
