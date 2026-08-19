#!/usr/bin/env python3
"""
generate_cantilever_report.py
综合脚本：悬臂梁求解 + 后处理可视化 + Word 报告生成

产出：
    - reports/cantilever_stress.png
    - reports/cantilever_disp.png
    - reports/cantilever_stress_curve.png
    - reports/cantilever_stress_curve.json
    - reports/cantilever_validation_report.docx
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv()

from ansys.mapdl.core import launch_mapdl
from post_processor import PostProcessor


# ───────────────────────────────
# 仿真参数
# ───────────────────────────────

PARAMETERS = {
    "length": 1.0,
    "width": 0.1,
    "height": 0.1,
    "mesh_size": 0.02,
    "young_modulus": 2.0e11,
    "poisson_ratio": 0.3,
    "force_y": -1000.0,
}


def expected_tip_displacement(params: dict) -> float:
    second_moment = params["height"] * params["width"] ** 3 / 12
    return params["force_y"] * params["length"] ** 3 / (
        3 * params["young_modulus"] * second_moment
    )


def run_simulation(mapdl, params: dict) -> float:
    """在已启动的 MAPDL 实例上运行悬臂梁求解，返回端部位移 TIP_UY。"""
    print("[1/4] 执行悬臂梁 APDL 求解...")
    mapdl.clear()
    mapdl.prep7()
    mapdl.et(1, "SOLID185")
    mapdl.mp("EX", 1, params["young_modulus"])
    mapdl.mp("PRXY", 1, params["poisson_ratio"])
    mapdl.block(0, params["length"], 0, params["width"], 0, params["height"])
    mapdl.esize(params["mesh_size"])
    mapdl.mshape(0, "3D")
    mapdl.mshkey(1)
    mapdl.vmesh("ALL")
    mapdl.nsel("S", "LOC", "X", 0)
    mapdl.d("ALL", "ALL", 0)
    mapdl.nsel("ALL")
    mapdl.nsel("S", "LOC", "X", params["length"])
    mapdl.nsel("R", "LOC", "Y", 0)
    mapdl.nsel("R", "LOC", "Z", 0)
    mapdl.run("*GET,LOAD_NODE,NODE,,NUM,MIN")
    mapdl.nsel("ALL")
    mapdl.f("LOAD_NODE", "FY", params["force_y"])
    mapdl.run("/SOLU")
    mapdl.antype("STATIC")
    mapdl.solve()
    mapdl.finish()
    mapdl.post1()
    mapdl.set("LAST")
    mapdl.allsel()
    mapdl.run("*GET,TIP_UY,NODE,LOAD_NODE,U,Y")
    return float(mapdl.parameters["TIP_UY"])


def generate_visualizations(mapdl, report_dir: Path) -> dict:
    """生成应力云图、位移云图和应力曲线。"""
    print("[2/4] 生成后处理可视化图表...")
    pp = PostProcessor(output_dir=str(report_dir))

    stress = pp.plot_stress_cloud(mapdl, filename="cantilever_stress.png")
    disp = pp.plot_displacement_cloud(mapdl, filename="cantilever_disp.png")

    # 沿梁中心线的应力曲线
    path_points = [
        [0, PARAMETERS["width"] / 2, PARAMETERS["height"] / 2],
        [PARAMETERS["length"] * 0.25, PARAMETERS["width"] / 2, PARAMETERS["height"] / 2],
        [PARAMETERS["length"] * 0.5, PARAMETERS["width"] / 2, PARAMETERS["height"] / 2],
        [PARAMETERS["length"] * 0.75, PARAMETERS["width"] / 2, PARAMETERS["height"] / 2],
        [PARAMETERS["length"], PARAMETERS["width"] / 2, PARAMETERS["height"] / 2],
    ]
    curve = pp.extract_stress_curve(
        mapdl,
        path_points=path_points,
        filename="cantilever_stress_curve",
        curve_title="沿梁长度方向 Von Mises 应力分布",
    )

    return {
        "stress": stress,
        "disp": disp,
        "curve": curve,
    }


def generate_word_report(
    report_dir: Path,
    tip_uy: float,
    viz_results: dict,
    max_stress: float,
    max_disp: float,
) -> Path:
    """生成包含数据和图表的 Word 文档。"""
    print("[3/4] 生成 Word 报告...")
    expected = expected_tip_displacement(PARAMETERS)
    rel_error = abs(tip_uy - expected) / abs(expected)

    doc = Document()

    # 标题
    title = doc.add_heading("悬臂梁弯曲仿真验证报告", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    doc.add_paragraph("验证工具：AI-Ansys / PyMAPDL + ANSYS v252")
    doc.add_paragraph()

    # ── 1. 仿真参数 ──
    doc.add_heading("1. 仿真参数", level=1)
    table = doc.add_table(rows=1, cols=2)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    hdr[0].text = "参数"
    hdr[1].text = "数值"

    rows = [
        ("梁长度 (m)", f"{PARAMETERS['length']}"),
        ("截面宽度 (m)", f"{PARAMETERS['width']}"),
        ("截面高度 (m)", f"{PARAMETERS['height']}"),
        ("网格尺寸 (m)", f"{PARAMETERS['mesh_size']}"),
        ("弹性模量 (Pa)", f"{PARAMETERS['young_modulus']:.2e}"),
        ("泊松比", f"{PARAMETERS['poisson_ratio']}"),
        ("端部载荷 (N)", f"{PARAMETERS['force_y']}"),
        ("单元类型", "SOLID185"),
    ]
    for name, val in rows:
        c = table.add_row().cells
        c[0].text = name
        c[1].text = val
    doc.add_paragraph()

    # ── 2. 结果摘要 ──
    doc.add_heading("2. 结果摘要", level=1)
    t2 = doc.add_table(rows=1, cols=3)
    t2.style = "Light Grid Accent 1"
    h2 = t2.rows[0].cells
    h2[0].text = "指标"
    h2[1].text = "数值"
    h2[2].text = "备注"

    r2 = [
        ("理论端部位移 (mm)", f"{expected * 1000:.4f}", "Euler-Bernoulli 解析解"),
        ("数值端部位移 (mm)", f"{tip_uy * 1000:.4f}", "MAPDL SOLID185 有限元解"),
        ("相对误差", f"{rel_error * 100:.2f}%", "容忍度：25%"),
        ("最大 Von Mises 应力 (MPa)", f"{max_stress / 1e6:.2f}", "位于固定端附近"),
        ("最大合位移 (mm)", f"{max_disp * 1000:.4f}", "USUM"),
    ]
    for name, val, note in r2:
        c = t2.add_row().cells
        c[0].text = name
        c[1].text = val
        c[2].text = note
    doc.add_paragraph()

    # ── 3. 可视化结果 ──
    doc.add_heading("3. 可视化结果", level=1)

    if viz_results["stress"].get("success"):
        doc.add_paragraph("图 1：Von Mises 应力云图")
        doc.add_picture(str(report_dir / "cantilever_stress.png"), width=Inches(5.5))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

    if viz_results["disp"].get("success"):
        doc.add_paragraph("图 2：合位移云图")
        doc.add_picture(str(report_dir / "cantilever_disp.png"), width=Inches(5.5))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

    if viz_results["curve"].get("success"):
        doc.add_paragraph("图 3：沿梁长度方向 Von Mises 应力分布曲线")
        doc.add_picture(
            str(report_dir / "cantilever_stress_curve.png"), width=Inches(5.5)
        )
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

        # ── 4. 应力曲线数据 ──
        doc.add_paragraph()
        doc.add_heading("4. 应力曲线数据（采样）", level=1)
        with open(report_dir / "cantilever_stress_curve.json", encoding="utf-8") as f:
            curve_data = json.load(f)

        t3 = doc.add_table(rows=1, cols=3)
        t3.style = "Light Grid Accent 1"
        h3 = t3.rows[0].cells
        h3[0].text = "距离 (m)"
        h3[1].text = "Von Mises 应力 (Pa)"
        h3[2].text = "Von Mises 应力 (MPa)"

        n = len(curve_data["distances"])
        step = max(1, n // 20)
        for i in range(0, n, step):
            c = t3.add_row().cells
            c[0].text = f"{curve_data['distances'][i]:.4f}"
            c[1].text = f"{curve_data['von_mises_stress'][i]:.4e}"
            c[2].text = f"{curve_data['von_mises_stress'][i] / 1e6:.4f}"

    # ── 5. 结论 ──
    doc.add_paragraph()
    doc.add_heading("5. 结论", level=1)
    if rel_error <= 0.25:
        p = doc.add_paragraph(
            "✅ 验证通过：悬臂梁数值解与理论解的相对误差在允许范围内，仿真模型可信。"
        )
    else:
        p = doc.add_paragraph(
            "❌ 验证未通过：相对误差超出容忍度，建议检查模型设置。"
        )
    p.runs[0].font.bold = True

    doc_path = report_dir / "cantilever_validation_report.docx"
    doc.save(str(doc_path))
    print(f"[4/4] Word 报告已保存：{doc_path}")
    return doc_path


def main() -> int:
    workdir = PROJECT_ROOT / "runtime_data" / "cantilever_report_v2"
    workdir.mkdir(parents=True, exist_ok=True)

    # 清理旧文件（仅清理当前新目录）
    for f in workdir.glob("*"):
        if f.is_file():
            try:
                f.unlink()
            except PermissionError:
                pass

    report_dir = PROJECT_ROOT / "reports"
    report_dir.mkdir(exist_ok=True)

    print("启动 MAPDL...")
    mapdl = launch_mapdl(
        exec_file=r"D:\Program Files (x86)\ANSYS Inc25\v252\ANSYS\bin\winx64\MAPDL.exe",
        run_location=str(workdir),
        jobname="cantilever",
        override=True,
        mode="grpc",
        loglevel="ERROR",
    )

    try:
        tip_uy = run_simulation(mapdl, PARAMETERS)
        viz = generate_visualizations(mapdl, report_dir)

        max_stress = float(mapdl.post_processing.nodal_eqv_stress().max())
        max_disp = float(mapdl.post_processing.nodal_displacement("NORM").max())

        doc_path = generate_word_report(report_dir, tip_uy, viz, max_stress, max_disp)
        print(f"\n全部完成！报告路径：{doc_path}")
    finally:
        mapdl.exit()

    return 0


if __name__ == "__main__":
    sys.exit(main())
