# Carbonfly MCP

[![License: LGPL-3.0](https://img.shields.io/badge/License-LGPL--3.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![OpenFOAM v10](https://img.shields.io/badge/OpenFOAM-v10-7a6fac)](https://openfoam.org/version/10/)
[![WSL 2](https://img.shields.io/badge/Windows-10_&_11_|_WSL_2-7a6fac)](https://learn.microsoft.com/en-us/windows/wsl/install)

**MCP server for Carbonfly** – Headless indoor CO2 CFD simulation with OpenFOAM via WSL, accessible through any MCP-compatible agent application (OpenCode, Claude Code, Codex, Cursor, etc.).

> **No Rhino. No Grasshopper. No CAD required.** Just your terminal and an AI agent.
>
> For the **original Carbonfly Grasshopper plugin**, see the [Carbonfly repository](https://github.com/RWTH-E3D/carbonfly).

---

## What it does

Carbonfly MCP wraps the [Carbonfly](https://github.com/RWTH-E3D/carbonfly) Python library into an MCP server, enabling AI agents to:

1. **Create simulation workspaces** to organize cases
2. **Generate 3D geometry** as STL (box with cutouts, disc, cylinder, sphere, or import external STLs)
3. **Configure boundary conditions** (inlets, outlets, walls, dynamic respiration, recirculation)
4. **Generate OpenFOAM cases** with mesh, fields, and solver settings
5. **Run meshing** (blockMesh + snappyHexMesh) via WSL
6. **Execute simulations** (buoyantReactingFoam) via WSL
7. **Post-process results** and assess Indoor Air Quality (IAQ) per international standards

**Trigger keywords**: `carbonfly`, `cbf`

---

## Prerequisites

- **Windows 10/11** with **WSL 2**
- **Ubuntu** (20.04 or 22.04) in WSL
- **OpenFOAM v10** installed in WSL (`/opt/openfoam10/etc/bashrc`)
- **Python 3.10+** on Windows

WSL and OpenFOAM setup guide: [How to Install](https://github.com/RWTH-E3D/carbonfly/blob/master/HowToInstall.md)

---

## Installation

### One-click: let an agent do it (recommended)

**Just paste the following prompt into your agent application** (OpenCode, Claude Code, Codex, Cursor, etc.):

```
Install and configure the Carbonfly MCP server from this repo:
https://github.com/hqrrr/carbonfly-mcp

Read the README for instructions.
You need to:
1. Clone the repo
2. Install dependencies: pip install fastmcp numpy
3. Add this MCP server to the agent's config file
4. Tell me when it's ready to test
```

The agent will read the README, install dependencies, edit the MCP config file, and verify the server starts. No manual steps needed.

> **Tip**: When using OhMyOpenCode, include `ulw` in your prompt for best results.

### Manual installation

```powershell
git clone https://github.com/hqrrr/carbonfly-mcp.git
cd carbonfly-mcp
pip install fastmcp numpy
```

#### Configure MCP server

Add the MCP server to your agent's config file:

<details>
<summary><b>OpenCode</b> — add to <code>opencode.json</code></summary>

```json
{
  "mcp": {
    "carbonfly": {
      "type": "local",
      "command": ["<python-path>"],
      "args": ["-m", "carbonfly_mcp.server"],
      "cwd": "<clone-path>\\mcp\\src",
      "enabled": true
    }
  }
}
```

`<python-path>` — your Python executable (e.g. `C:\\Users\\...\\Python310\\python.exe`)  
`<clone-path>` — the cloned repo root (e.g. `D:\\Projects\\carbonfly-mcp`)

</details>

<details>
<summary><b>Claude Code</b> — CLI command</summary>

```bash
claude mcp add carbonfly -- "<python-path>" -m carbonfly_mcp.server
```

</details>

<details>
<summary><b>Codex</b> — add to <code>~/.codex/config.toml</code></summary>

```toml
[mcp_servers.carbonfly]
command = "<python-path>"
args = ["-m", "carbonfly_mcp.server"]
cwd = "<clone-path>\\mcp\\src"
```

</details>

---

## Quick Start

**Phase 1 — Setup**

```
@carbonfly check_environment
```

**Phase 2 — Start a workspace**

```
@carbonfly create_workshop with name "demo" in this project folder
```

**Phase 3 — Add geometry**

All geometry goes into a single multi-region ``scene.stl``.  Use cutouts for
openings and discs for flush-mounted inlet/outlet patches — no overlapping surfaces.

```
@carbonfly create a 5x4x3m room with a 0.15m radius ceiling opening at (1, 2)
```

```
@carbonfly create a 0.15m radius inlet disc on the ceiling at (1, 2, 3)
```

```
@carbonfly create an outlet cylinder radius 0.15m height 0.3m at (4, 2, 0.05)
```

**Phase 4 — Configure boundaries**

```
@carbonfly configure inlet velocity 1.5 m/s downward, room wall, outlet pressure
```

**Phase 5 — Generate & run**

```
@carbonfly generate case "ventilation_demo" with cell_size=0.25 transient 120s
```

```
@carbonfly run meshing then run simulation
```

**Phase 6 — Check results**

```
@carbonfly get simulation status
```

```
@carbonfly assess IAQ with EN standard
```

---

## How it works — directory layout & file locations

Carbonfly MCP organizes everything under a **workshop directory** (created by `create_workshop`).

### Workshop directory structure

```
<your-workshop>/                      # Created by create_workshop
├── workshop.json                     # Metadata: name, timestamps, version
├── stl/
│   └── scene.stl                     # Single multi-region STL (all geometry)
├── boundaries.json                   # Boundary condition configuration
└── cases/
    └── <case_name>/                  # OpenFOAM case directory
        ├── <case_name>.foam          # ParaView marker — open this in ParaView
        ├── 0/                        # Initial fields at t=0
        │   ├── U                     #   velocity field
        │   ├── T                     #   temperature field
        │   ├── CO2                   #   CO2 mass fraction field
        │   └── p                     #   pressure field
        ├── constant/
        │   ├── triSurface/           # Working copies of STL files
        │   └── polyMesh/             # Final mesh (after snappyHexMesh)
        ├── system/
        │   ├── blockMeshDict         # Background mesh definition
        │   ├── snappyHexMeshDict     # Snapping/meshing settings
        │   ├── controlDict           # Time step, end time, output control
        │   ├── fvSchemes             # Discretization schemes
        │   └── fvSolution            # Solver settings
        ├── 10/                       # Results at t=10s
        │   ├── U                     #   velocity snapshot
        │   ├── T                     #   temperature snapshot
        │   └── CO2                   #   CO2 snapshot
        └── 60/                       # Results at t=60s ...
```

### Where to put manual STL files

Place your existing STL files into the workshop's `stl/` folder, **then** call `import_stl`:

```
# Option A: put the file there first, then register
Copy my_model.stl  →  <workshop>/stl/my_model.stl
@carbonfly import_stl with source "<workshop>/stl/my_model.stl" and name "my_model"

# Option B: import from anywhere (copies into stl/ automatically)
@carbonfly import_stl with source "C:\Users\me\Downloads\ventilation.stl" and name "duct"
```

### Where to find generated cases

After calling `generate_case`: `<workshop>/cases/<case_name>/`

Use `get_workshop_info` to reveal the full path.

### Where to find simulation results

Results appear as numbered time directories inside the case:

```
<workshop>/cases/<case_name>/10/     # CO2, U, T at t=10s
<workshop>/cases/<case_name>/60/     # at t=60s (e.g., final time)
```

Use `list_results` to see available time directories and fields.

### How to view 3D results (ParaView)

**ParaView must be installed separately** — [paraview.org/download](https://www.paraview.org/download/)

1. Open ParaView → **File → Open**
2. Navigate to `<workshop>/cases/<case_name>/`
3. Select the `<case_name>.foam` file → **Apply**
4. Choose fields from the dropdown: `CO2`, `U`, `T`, `p`
5. Use **Filters** (Slice, Contour, Glyph) for advanced visualization

No OpenFOAM installation needed on Windows for viewing — ParaView reads `.foam` files directly.

### How to read results programmatically (without ParaView)

| Tool | What it does |
|---|---|
| `list_results` | Lists all time directories and available fields |
| `read_co2_field` | Reads CO2 internal field values from a time step |
| `read_temperature_field` | Reads temperature internal field values |
| `probe_point` | Samples a field at a specific (x, y, z) point |
| `assess_iaq` | Evaluates IAQ using the CO2 field and a chosen standard |

### How to inspect or edit case files

All case files are plain text (OpenFOAM dictionary format):

- **Mesh**: `system/blockMeshDict`, `system/snappyHexMeshDict`
- **Solver**: `system/controlDict`, `system/fvSchemes`, `system/fvSolution`
- **Initial conditions**: `0/U`, `0/T`, `0/CO2`, ...
- **Boundaries**: `boundaries.json` (in workshop root)

### How to re-run or modify a simulation

1. Edit case files manually or re-run `generate_case` (overwrites all files)
2. Delete time directories (keep `0/`, `constant/`, `system/`)
3. `run_meshing` then `run_simulation` again

Or create a new case with a different name for comparison.

---

## Available Tools

| Category | Tool | Description |
|---|---|---|
| **Workshop** | `create_workshop` | Create a simulation workspace |
| | `list_workshops` | List all workspaces |
| | `get_workshop_info` | Get workspace details |
| | `delete_workshop` | Delete a workspace |
| **Geometry** | `create_box_stl` | Create box with optional face cutouts |
| | `create_disc_stl` | Create flat circular disc (inlet/outlet patch) |
| | `create_cylinder_stl` | Create cylinder STL |
| | `create_sphere_stl` | Create sphere STL |
| | `import_stl` | Import external STL file |
| | `list_geometry` | List workshop geometry |
| | `clear_geometry` | Remove all geometry from scene |
| **Boundary** | `configure_inlet` | Configure velocity inlet |
| | `configure_outlet` | Configure pressure outlet |
| | `configure_wall` | Configure wall boundary |
| | `configure_dynamic_respiration` | Configure breathing manikin |
| | `configure_recirculation` | Configure recirculation pair |
| | `list_boundaries` | List configured boundaries |
| | `clear_boundaries` | Clear all boundaries |
| **Simulation** | `check_environment` | Check WSL + OpenFOAM |
| | `generate_case` | Generate OpenFOAM case |
| | `run_meshing` | Run blockMesh + snappyHexMesh |
| | `run_simulation` | Run buoyantReactingFoam |
| | `get_simulation_status` | Check simulation progress |
| **Post-process** | `list_results` | List result time directories |
| | `probe_point` | Probe field at a point |
| | `assess_iaq` | Assess IAQ per standards |
| | `read_co2_field` | Read CO2 field values |
| | `read_temperature_field` | Read temperature field values |

---

## Project Structure

```
carbonfly-mcp/                          # ← this repo
├── carbonfly/                          #   Original Carbonfly library (unchanged)
├── mcp/                                #   MCP server
│   ├── .agents/skills/carbonfly-mcp-use/
│   │   └── SKILL.md                    #     Agent usage guide
│   ├── src/carbonfly_mcp/
│   │   ├── server.py                   #     FastMCP entry point (26 tools)
│   │   ├── registry.py                 #     Tool registration
│   │   ├── workshop/manager.py         #     Workspace management
│   │   └── tools/
│   │       ├── geometry.py             #     STL generation (no Rhino)
│   │       ├── boundary.py             #     Boundary configuration
│   │       ├── simulation.py           #     Case gen + WSL runner
│   │       └── postproc.py             #     Results + IAQ assessment
│   └── pyproject.toml
├── docs/                               #   Carbonfly Python API docs
├── examples/                           #   Carbonfly usage examples
└── README.md                           #   ← you are here
```

---

## Supported IAQ Standards

| Code | Standard | Basis |
|---|---|---|
| EN | CEN/EN 16798-1 (Europe) | delta(CO2) indoor-outdoor |
| LEHB | Japanese LEHB | Indoor CO2 |
| SS | Singapore SS 554:2016 | delta(CO2) indoor-outdoor |
| HK | Hong Kong EPD | Indoor CO2 |
| UBA | German Umweltbundesamt | Indoor CO2 |
| DOSH | Malaysia DOSH ICOP IAQ 2010 | Indoor CO2 |
| NBR | Brazil ABNT NBR 16401/17037 | delta(CO2) indoor-outdoor |

---

## License

LGPL-3.0 – see [LICENSE](LICENSE).

Copyright (C) 2026 Qirui Huang, Institute of Energy Efficiency and Sustainable Building (E3D), RWTH Aachen University.

---

## Citation

Carbonfly MCP is an extension of the Carbonfly project. If you use it in academic work, please cite:

```bibtex
@article{Huang_2026_Carbonfly_SoftwareX,
  author  = {Huang, Qirui and Langenbeck, Anna and Frisch, J{\'e}r{\^o}me and van Treeck, Christoph},
  title   = {{Carbonfly}: {An} easy-to-use {Python} library and {Grasshopper} toolbox for {CO}$_2$-based indoor airflow and air quality {CFD} simulation},
  journal = {SoftwareX},
  year    = {2026},
  volume  = {34},
  pages   = {102580},
  doi     = {10.1016/j.softx.2026.102580},
}
```
