---
name: check-ansys-env
description: Diagnose CAE Agent environment readiness across LLM connectivity, PyMAPDL, MAPDL executable discovery, PyMechanical, and Mechanical version support. Use when ANSYS tools fail, paths or licenses changed, or the user asks whether the CAE environment is usable.
---

# Check ANSYS Environment

Run an independent status check for each CAE layer and summarize the result without hiding degraded modes.

## Workflow

1. Call `health_check` from the `ansys-local` MCP server.
2. Call `mapdl_status` to inspect PyMAPDL importability, executable discovery, ANSYS environment variables, and runtime directory.
3. Call `mechanical_status` to inspect PyMechanical importability, executable discovery, detected version, and 242+ support.
4. Run the three checks concurrently when the tool surface permits because they are independent.
5. Separate configuration failures, missing executables, license/runtime failures, and optional LLM unavailability.

## Report

Present three sections: LLM analysis layer, PyMAPDL execution layer, and PyMechanical layer. For every check, show pass/fail, the detected path or version, and the actionable next step. If the LLM is unavailable but local rules work, label the environment degraded rather than unusable.

## Knowledge lifecycle

Before substantial use or behavior changes, invoke `$knowledge-driven-skill-sync` to pull curated knowledge for `check-ansys-env` and read `references/knowledge.md` when present. After reusable learning or a capability update, record it and run the lifecycle sync before committing.
