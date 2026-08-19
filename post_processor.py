"""
post_processor.py
后处理可视化与应力曲线提取模块。

依赖：
    pip install pyvista ansys-tools-visualization-interface matplotlib numpy

功能：
    - PyVista 离屏应力/位移云图绘制
    - 沿几何路径的应力曲线提取与绘图
    - 结果保存为 PNG 图片到 reports/ 目录
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


class PostProcessor:
    """封装 PyMAPDL 后处理可视化与数据提取流程。"""

    def __init__(self, output_dir: str | Path = "reports") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ───────────────────────────────
    # stdio 流保护（MCP 模式必需）
    # ───────────────────────────────

    @staticmethod
    def _stdio_guard(func):
        """装饰器：在工具调用期间将 sys.stdout 重定向到 sys.stderr，防止污染 JSON-RPC stdio 流。"""

        def wrapper(*args, **kwargs):
            original_stdout = sys.stdout
            try:
                sys.stdout = sys.stderr
                return func(*args, **kwargs)
            finally:
                sys.stdout = original_stdout

        return wrapper

    # ───────────────────────────────
    # 1. 应力云图
    # ───────────────────────────────

    @_stdio_guard
    def plot_stress_cloud(self, mapdl, filename: str | None = None) -> dict[str, Any]:
        """绘制 Von Mises 应力云图，保存为 PNG。"""
        try:
            import pyvista as pv
        except ImportError as exc:
            return {"success": False, "error": f"缺少可视化依赖：{exc}"}

        save_path = self.output_dir / (filename or "stress_cloud.png")

        try:
            mapdl.post1()
            mapdl.set("LAST")
            mapdl.allsel()

            # 读取结果到 PyVista grid
            grid = mapdl.mesh._grid.copy()
            grid["Von Mises Stress"] = mapdl.post_processing.nodal_eqv_stress()

            plotter = pv.Plotter(off_screen=True)
            plotter.add_mesh(
                grid,
                scalars="Von Mises Stress",
                cmap="jet",
                show_edges=True,
                scalar_bar_args={"title": "Von Mises (Pa)"},
            )
            plotter.add_title("Von Mises Stress Cloud")
            plotter.camera_position = "iso"
            plotter.screenshot(str(save_path), window_size=(1024, 768))
            plotter.close()

            return {
                "success": True,
                "image_path": str(save_path.resolve()),
                "variable": "Von Mises Stress",
                "type": "cloud_plot",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ───────────────────────────────
    # 2. 位移云图
    # ───────────────────────────────

    @_stdio_guard
    def plot_displacement_cloud(self, mapdl, filename: str | None = None) -> dict[str, Any]:
        """绘制合位移云图，保存为 PNG。"""
        try:
            import pyvista as pv
        except ImportError as exc:
            return {"success": False, "error": f"缺少可视化依赖：{exc}"}

        save_path = self.output_dir / (filename or "displacement_cloud.png")

        try:
            mapdl.post1()
            mapdl.set("LAST")
            mapdl.allsel()

            grid = mapdl.mesh._grid.copy()
            grid["Total Displacement"] = mapdl.post_processing.nodal_displacement("NORM")

            plotter = pv.Plotter(off_screen=True)
            plotter.add_mesh(
                grid,
                scalars="Total Displacement",
                cmap="viridis",
                show_edges=True,
                scalar_bar_args={"title": "Displacement (m)"},
            )
            plotter.add_title("Total Displacement Cloud")
            plotter.camera_position = "iso"
            plotter.screenshot(str(save_path), window_size=(1024, 768))
            plotter.close()

            return {
                "success": True,
                "image_path": str(save_path.resolve()),
                "variable": "Total Displacement",
                "type": "cloud_plot",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ───────────────────────────────
    # 3. 应力曲线提取（沿路径）
    # ───────────────────────────────

    @_stdio_guard
    def extract_stress_curve(
        self,
        mapdl,
        path_points: list[list[float]],
        filename: str | None = None,
        curve_title: str = "Stress Curve",
    ) -> dict[str, Any]:
        """
        沿指定几何路径提取 Von Mises 应力，绘制曲线并导出 JSON 数据。

        Args:
            mapdl: PyMAPDL 实例（已求解完成）
            path_points: 路径上的三维点列表，例如 [[x1,y1,z1], [x2,y2,z2], ...]
            filename: 输出图片文件名（不含后缀）
            curve_title: 图表标题
        """
        try:
            import matplotlib

            matplotlib.use("Agg")  # 离屏后端
            import matplotlib.pyplot as plt

            # 配置中文字体（Windows 优先 Microsoft YaHei，后备 SimHei）
            plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False

            import numpy as np
            import pyvista as pv
        except ImportError as exc:
            return {"success": False, "error": f"缺少绘图依赖：{exc}"}

        if len(path_points) < 2:
            return {"success": False, "error": "路径点至少需要 2 个。"}

        img_path = self.output_dir / (f"{filename}.png" if filename else "stress_curve.png")
        json_path = self.output_dir / (f"{filename}.json" if filename else "stress_curve.json")

        try:
            mapdl.post1()
            mapdl.set("LAST")
            mapdl.allsel()

            # 构造 PyVista Line 用于采样
            points = np.array(path_points, dtype=float)
            line = pv.Line(points[0], points[-1], resolution=len(path_points) * 10)

            # 读取结果网格
            grid = mapdl.mesh._grid.copy()
            grid["Von Mises Stress"] = mapdl.post_processing.nodal_eqv_stress()

            # 沿 Line 采样应力值
            sampled = line.sample(grid)
            distances = np.linspace(0, np.linalg.norm(points[-1] - points[0]), sampled.n_points)
            stress_values = sampled["Von Mises Stress"]

            # 绘图
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.plot(distances, stress_values, marker="o", markersize=3, linewidth=1.5)
            ax.set_xlabel("Distance along path (m)")
            ax.set_ylabel("Von Mises Stress (Pa)")
            ax.set_title(curve_title)
            ax.grid(True, linestyle="--", alpha=0.6)
            fig.tight_layout()
            fig.savefig(str(img_path), dpi=150)
            plt.close(fig)

            # 导出 JSON
            data = {
                "title": curve_title,
                "path_points": path_points,
                "distances": distances.tolist(),
                "von_mises_stress": stress_values.tolist(),
            }
            json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

            return {
                "success": True,
                "image_path": str(img_path.resolve()),
                "json_path": str(json_path.resolve()),
                "sample_count": len(distances),
                "max_stress": float(np.max(stress_values)),
                "min_stress": float(np.min(stress_values)),
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ───────────────────────────────
    # 4. 批量后处理（一键云图 + 曲线）
    # ───────────────────────────────

    @_stdio_guard
    def run_full_postprocess(
        self,
        mapdl,
        stress_curve_path: list[list[float]] | None = None,
        basename: str = "post",
    ) -> dict[str, Any]:
        """一键执行：应力云图 + 位移云图 + 可选应力曲线。"""
        results: dict[str, Any] = {"success": True, "plots": []}

        stress_result = self.plot_stress_cloud(mapdl, filename=f"{basename}_stress.png")
        if stress_result.get("success"):
            results["plots"].append(stress_result)
        else:
            results["stress_error"] = stress_result.get("error")

        disp_result = self.plot_displacement_cloud(mapdl, filename=f"{basename}_disp.png")
        if disp_result.get("success"):
            results["plots"].append(disp_result)
        else:
            results["disp_error"] = disp_result.get("error")

        if stress_curve_path:
            curve_result = self.extract_stress_curve(
                mapdl,
                path_points=stress_curve_path,
                filename=f"{basename}_curve",
                curve_title=f"Stress along path ({basename})",
            )
            if curve_result.get("success"):
                results["plots"].append(curve_result)
            else:
                results["curve_error"] = curve_result.get("error")

        return results

    # ───────────────────────────────
    # 5. 环境检查
    # ───────────────────────────────

    @staticmethod
    def check_visualization_env() -> dict[str, Any]:
        """检查后处理可视化依赖是否就绪。"""
        status: dict[str, Any] = {}

        try:
            import pyvista as pv

            status["pyvista"] = {"importable": True, "version": pv.__version__}
        except Exception as exc:
            status["pyvista"] = {"importable": False, "error": str(exc)}

        try:
            import matplotlib

            status["matplotlib"] = {"importable": True, "version": matplotlib.__version__}
        except Exception as exc:
            status["matplotlib"] = {"importable": False, "error": str(exc)}

        try:
            import numpy as np

            status["numpy"] = {"importable": True, "version": np.__version__}
        except Exception as exc:
            status["numpy"] = {"importable": False, "error": str(exc)}

        try:
            import ansys.tools.visualization_interface

            status["ansys_tools_visualization_interface"] = {"importable": True}
        except Exception as exc:
            status["ansys_tools_visualization_interface"] = {"importable": False, "error": str(exc)}

        status["ready"] = all(
            v.get("importable", False)
            for k, v in status.items()
            if k != "ready"
        )
        return status
