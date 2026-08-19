"""
mechanical_post_processor.py
Mechanical 后处理可视化与结果提取模块。

功能：
    - 生成 Mechanical 脚本用于导出应力/位移/变形云图
    - 生成 Mechanical 脚本用于提取结果数据表格
    - 与 mechanical_runner.py 配合完成一键后处理

依赖：
    pip install ansys-mechanical-core

用法：
    from mechanical_post_processor import MechanicalPostProcessor
    from mechanical_runner import MechanicalRunner

    runner = MechanicalRunner()
    pp = MechanicalPostProcessor(output_dir="reports")
    result = pp.run_full_postprocess(runner, working_directory="mechanical_workspace")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class MechanicalPostProcessor:
    """封装 Mechanical 后处理可视化与数据提取流程。"""

    def __init__(self, output_dir: str | Path = "reports") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ───────────────────────────────
    # 1. 应力云图导出脚本
    # ───────────────────────────────

    @staticmethod
    def build_stress_export_script(image_path: str) -> str:
        """生成导出 Equivalent Stress 云图的 Mechanical 脚本。"""
        return f'''
model = ExtAPI.DataModel.Project.Model
analysis = model.Analyses[0]
solution = analysis.Solution

# 确保有 Equivalent Stress 结果对象
stress_results = [r for r in solution.GetChildren(DataModelObjectCategory.Result) if "Stress" in r.Name or "Equivalent" in r.Name]
if not stress_results:
    stress = solution.AddEquivalentStress()
else:
    stress = stress_results[0]

stress.Activate()
ExtAPI.Graphics.ExportImage(r"{image_path}", width=1920, height=1080)

wb_script_result = json.dumps({{
    "success": True,
    "image_path": r"{image_path}",
    "variable": "Equivalent Stress",
    "type": "cloud_plot",
}}, ensure_ascii=False)
'''.strip()

    # ───────────────────────────────
    # 2. 位移云图导出脚本
    # ───────────────────────────────

    @staticmethod
    def build_displacement_export_script(image_path: str) -> str:
        """生成导出 Total Deformation 云图的 Mechanical 脚本。"""
        return f'''
model = ExtAPI.DataModel.Project.Model
analysis = model.Analyses[0]
solution = analysis.Solution

deform_results = [r for r in solution.GetChildren(DataModelObjectCategory.Result) if "Deformation" in r.Name or "Displacement" in r.Name]
if not deform_results:
    deformation = solution.AddTotalDeformation()
else:
    deformation = deform_results[0]

deformation.Activate()
ExtAPI.Graphics.ExportImage(r"{image_path}", width=1920, height=1080)

wb_script_result = json.dumps({{
    "success": True,
    "image_path": r"{image_path}",
    "variable": "Total Deformation",
    "type": "cloud_plot",
}}, ensure_ascii=False)
'''.strip()

    # ───────────────────────────────
    # 3. 结果数据提取脚本
    # ───────────────────────────────

    @staticmethod
    def build_result_extraction_script(result_types: list[str] | None = None) -> str:
        """生成提取指定结果类型数据的 Mechanical 脚本。

        Args:
            result_types: 结果类型列表，例如 ["stress", "displacement", "frequency"]
        """
        result_types = result_types or ["stress", "displacement"]
        return f'''
model = ExtAPI.DataModel.Project.Model
analysis = model.Analyses[0]
solution = analysis.Solution

results_data = {{}}

for result_obj in solution.GetChildren(DataModelObjectCategory.Result):
    name = result_obj.Name
    if hasattr(result_obj, "Maximum"):
        results_data[name] = {{
            "maximum": float(result_obj.Maximum),
            "minimum": float(result_obj.Minimum) if hasattr(result_obj, "Minimum") else None,
        }}

# 模态频率提取
if hasattr(analysis, "NumberOfModes"):
    freqs = []
    for i, mode in enumerate(solution.GetChildren(DataModelObjectCategory.Result), 1):
        if hasattr(mode, "Frequency"):
            freqs.append({{"order": i, "frequency_hz": float(mode.Frequency)}})
    if freqs:
        results_data["modal_frequencies"] = freqs

wb_script_result = json.dumps({{
    "success": True,
    "result_types": {json.dumps(result_types, ensure_ascii=False)},
    "results": results_data,
}}, ensure_ascii=False)
'''.strip()

    # ───────────────────────────────
    # 4. 批量后处理（一键云图 + 数据）
    # ───────────────────────────────

    def run_full_postprocess(
        self,
        runner,
        working_directory: str | None = None,
        basename: str = "mechanical_post",
    ) -> dict[str, Any]:
        """一键执行：应力云图 + 位移云图 + 结果数据提取。

        Args:
            runner: MechanicalRunner 实例
            working_directory: Mechanical 工作目录
            basename: 输出文件前缀
        """
        results: dict[str, Any] = {"success": True, "plots": [], "data": {}}

        # 应力云图
        stress_path = str(self.output_dir / f"{basename}_stress.png")
        stress_script = self.build_stress_export_script(stress_path)
        stress_result = runner.export_mechanical_image(
            mechanical_exec=None,
            script=stress_script,
            image_path=stress_path,
            context="stress_cloud",
        )
        if stress_result.get("success"):
            results["plots"].append(stress_result)
        else:
            results["stress_error"] = stress_result.get("error")

        # 位移云图
        disp_path = str(self.output_dir / f"{basename}_disp.png")
        disp_script = self.build_displacement_export_script(disp_path)
        disp_result = runner.export_mechanical_image(
            mechanical_exec=None,
            script=disp_script,
            image_path=disp_path,
            context="displacement_cloud",
        )
        if disp_result.get("success"):
            results["plots"].append(disp_result)
        else:
            results["disp_error"] = disp_result.get("error")

        # 结果数据提取
        extract_script = self.build_result_extraction_script()
        extract_result = runner.run_python_script(
            script=extract_script,
            context="result_extraction",
            launch_mechanical=True,
            working_directory=working_directory,
        )
        if extract_result.get("success"):
            execution_result = extract_result.get("execution_result", {})
            results["data"] = execution_result.get("results", {})
        else:
            results["data_error"] = extract_result.get("message")

        return results

    # ───────────────────────────────
    # 5. 环境检查
    # ───────────────────────────────

    @staticmethod
    def check_visualization_env() -> dict[str, Any]:
        """检查 Mechanical 后处理依赖是否就绪。"""
        status: dict[str, Any] = {}

        try:
            from ansys.mechanical.core import launch_mechanical

            status["pymechanical"] = {"importable": True}
        except Exception as exc:
            status["pymechanical"] = {"importable": False, "error": str(exc)}

        status["ready"] = status.get("pymechanical", {}).get("importable", False)
        return status
