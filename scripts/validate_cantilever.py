"""Run and validate the cantilever template against a real MAPDL host."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from ansys_runner import AnsysRunner


DEFAULT_PARAMETERS = {
    "length": 1.0,
    "width": 0.1,
    "height": 0.1,
    "mesh_size": 0.02,
    "young_modulus": 2.0e11,
    "poisson_ratio": 0.3,
    "force_y": -1000.0,
}


def expected_tip_displacement(parameters: dict[str, float]) -> float:
    second_moment = parameters["height"] * parameters["width"] ** 3 / 12
    return parameters["force_y"] * parameters["length"] ** 3 / (3 * parameters["young_modulus"] * second_moment)


def write_result(output_path: Path, result: dict) -> None:
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir",
        type=Path,
        default=Path("runtime_data") / "cantilever_validation",
        help="Directory for MAPDL outputs and validation.json.",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.25,
        help="Maximum relative error from Euler-Bernoulli theory.",
    )
    arguments = parser.parse_args()

    load_dotenv()
    runner = AnsysRunner()
    validation = {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "parameters": DEFAULT_PARAMETERS,
        "expected_tip_uy": expected_tip_displacement(DEFAULT_PARAMETERS),
        "tolerance": arguments.tolerance,
    }

    status = runner.get_environment_status()
    validation["environment"] = status
    if not status["pymapdl_importable"] or not status["detected_mapdl_exec"]:
        validation["success"] = False
        validation["failure"] = "PyMAPDL or MAPDL executable is unavailable."
        write_result(arguments.workdir, validation)
        return 2

    result = runner.run_template_simulation(
        template_type="cantilever",
        params=DEFAULT_PARAMETERS,
        working_directory=str(arguments.workdir),
        launch_mapdl=True,
    )
    validation["execution"] = result
    tip_uy = result.get("result_summary", {}).get("tip_uy")
    expected = validation["expected_tip_uy"]

    if not result.get("success") or not isinstance(tip_uy, (int, float)):
        validation["success"] = False
        validation["failure"] = "MAPDL did not return a usable cantilever tip displacement."
        write_result(arguments.workdir, validation)
        return 3

    relative_error = abs(tip_uy - expected) / abs(expected)
    validation["actual_tip_uy"] = tip_uy
    validation["relative_error"] = relative_error
    validation["success"] = bool(tip_uy < 0 and math.isfinite(tip_uy) and relative_error <= arguments.tolerance)
    if not validation["success"]:
        validation["failure"] = "Tip displacement failed the sign or theory-tolerance check."

    write_result(arguments.workdir, validation)
    return 0 if validation["success"] else 4


if __name__ == "__main__":
    sys.exit(main())
