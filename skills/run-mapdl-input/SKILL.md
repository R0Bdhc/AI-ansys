---
name: run-mapdl-input
description: Validate and execute ANSYS MAPDL .inp, .dat, or .mac files and optionally analyze the primary solver log. Use when the user wants to run APDL input, verify MAPDL readiness, collect result summaries, or diagnose execution failures.
---

# Run MAPDL Input

Execute supported APDL input through the `ansys-local` MCP server and preserve an auditable result trail.

## Workflow

1. Require an absolute `.inp`, `.dat`, or `.mac` path. Reject `.wbpj` and explain that it must be exported to APDL input first.
2. Verify the file exists, is non-empty, and contains plausible APDL commands such as `/PREP7` or `/SOLU`.
3. Call `mapdl_status`; require `pymapdl_importable=true` and a discovered MAPDL executable.
4. Call `mapdl_execute` with the input path and an explicit working directory. Prefer a user-provided safe working directory; otherwise use the CAE Agent workspace.
5. If log analysis is requested or unspecified, call `log_analyze` on the returned `primary_log_path`.

## Safety and reporting

Warn that execution may consume an ANSYS license and take several minutes. Report input path, execution status, primary log, returned result metrics, solver-output preview, analysis mode, errors, and report path. Never report success solely because the process launched.

## Knowledge lifecycle

Before substantial use or behavior changes, invoke `$knowledge-driven-skill-sync` to pull curated knowledge for `run-mapdl-input` and read `references/knowledge.md` when present. After reusable learning or a capability update, record it and run the lifecycle sync before committing.
