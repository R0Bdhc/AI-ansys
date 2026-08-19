#!/usr/bin/env python3
"""
generate_mechanical_report.py
综合脚本：Mechanical 悬臂梁模板执行 + 后处理可视化 + Word 报告生成

产出：
    - reports/mechanical_cantilever_stress.png
    - reports/mechanical_cantilever_disp.png
    - reports/mechanical_cantilever_results.json
    - reports/mechanical_cantilever_report.docx

用法：
    python scripts/generate_mechanical_report.py
    python scripts/generate_mechanical_report.py --launch        # 真实启动 Mechanical
"""

from __future__ import annotations

import argparse
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

from mechanical_post_processor import MechanicalPostProcessor
from mechanical_runner import MechanicalRunner


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


def run_mechanical_simulation(runner: MechanicalRunner, launch: bool, workdir: Path) -> dict:
    """运行 Mechanical 悬臂梁模板。"""
    print("[1/4] 准备 Mechanical 悬臂梁脚本...")
    script = runner._build_cantilever_beam_script(PARAMETERS)

    if not launch:
        print("    预览模式（未启动 Mechanical）。脚本长度：", len(script), "字符")
        return {
            "success": True,
            "preview": True,
            "script": script,
            "message": "预览模式：未真实启动 Mechanical。",
        }

    print("[1/4] 启动 Mechanical 并执行悬臂梁求解...")
    result = runner.run_python_script(
        script=script,
        context="cantilever_beam",
        launch_mechanical=True,
        working_directory=str(workdir),
    )
    return result


def generate_visualizations(
    runner: MechanicalRunner,
    pp: MechanicalPostProcessor,
    workdir: Path,
    report_dir: Path,
) -> dict:
    """生成应力云图、位移云图和结果数据。"""
    print("[2/4] 生成后处理可视化图表...")
    results = {"success": True, "plots": [], "data": {}}

    # 应力云图
    stress_path = str(report_dir / "mechanical_cantilever_stress.png")
    stress_script = pp.build_stress_export_script(stress_path)
    stress_result = runner.export_mechanical_image(
        mechanical_exec=None,
        script=stress_script,
        image_path=stress_path,
        context="stress_cloud",
    )
    if stress_result.get("success"):
        results["plots"].append({"type": "stress", "path": stress_path})
    else:
        results["stress_error"] = stress_result.get("error", "未知错误")

    # 位移云图
    disp_path = str(report_dir / "mechanical_cantilever_disp.png")
    disp_script = pp.build_displacement_export_script(disp_path)
    disp_result = runner.export_mechanical_image(
        mechanical_exec=None,
        script=disp_script,
        image_path=disp_path,
        context="displacement_cloud",
    )
    if disp_result.get("success"):
        results["plots"].append({"type": "displacement", "path": disp_path})
    else:
        results["disp_error"] = disp_result.get("error", "未知错误")

    # 结果数据提取
    extract_script = pp.build_result_extraction_script(["stress", "displacement"])
    extract_result = runner.run_python_script(
        script=extract_script,
        context="result_extraction",
        launch_mechanical=True,
        working_directory=str(workdir),
    )
    if extract_result.get("success"):
        execution_result = extract_result.get("execution_result", {})
        results["data"] = execution_result.get("results", {})
        # 保存 JSON
        json_path = report_dir / "mechanical_cantilever_results.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results["data"], f, ensure_ascii=False, indent=2)
        results["json_path"] = str(json_path)
    else:
        results["data_error"] = extract_result.get("message", "未知错误")

    return results


def generate_word_report(
    report_dir: Path,
    sim_result: dict,
    viz_results: dict,
    launch: bool,
) -> Path:
    """生成包含数据和图表的 Word 文档。"""
    print("[3/4] 生成 Word 报告...")
    expected = expected_tip_displacement(PARAMETERS)

    doc = Document()

    # 标题
    title = doc.add_heading("Mechanical 悬臂梁弯曲仿真报告", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    doc.add_paragraph("验证工具：AI-Ansys / PyMechanical + ANSYS Workbench")
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
        ("求解器", "ANSYS Mechanical (Structural Static)"),
    ]
    for name, val in rows:
        c = table.add_row().cells
        c[0].text = name
        c[1].text = val
    doc.add_paragraph()

    # ── 2. 执行状态 ──
    doc.add_heading("2. 执行状态", level=1)
    if launch and sim_result.get("success") and not sim_result.get("preview"):
        doc.add_paragraph("✅ Mechanical 求解已成功完成。")
    elif sim_result.get("preview"):
        doc.add_paragraph("⚠️ 预览模式：Mechanical 未真实启动，以下为脚本预览和预期结果。")
    else:
        doc.add_paragraph(f"❌ Mechanical 执行失败：{sim_result.get('message', '未知错误')}")
    doc.add_paragraph()

    # ── 3. 结果摘要 ──
    doc.add_heading("3. 结果摘要", level=1)
    t2 = doc.add_table(rows=1, cols=3)
    t2.style = "Light Grid Accent 1"
    h2 = t2.rows[0].cells
    h2[0].text = "指标"
    h2[1].text = "数值"
    h2[2].text = "备注"

    data = viz_results.get("data", {})
    stress_data = data.get("Equivalent Stress", {})
    disp_data = data.get("Total Deformation", {})

    max_stress = stress_data.get("maximum")
    max_disp = disp_data.get("maximum")

    r2 = [
        ("理论端部位移 (mm)", f"{expected * 1000:.4f}", "Euler-Bernoulli 解析解"),
    ]

    if max_disp is not None:
        r2.append(("数值最大位移 (mm)", f"{max_disp * 1000:.4f}", "Mechanical Total Deformation"))
        rel_error = abs(max_disp - expected) / abs(expected)
        r2.append(("相对误差", f"{rel_error * 100:.2f}%", "容忍度：25%"))
    else:
        r2.append(("数值最大位移 (mm)", "N/A", "未能提取"))
        r2.append(("相对误差", "N/A", "—"))

    if max_stress is not None:
        r2.append(("最大 Equivalent Stress (MPa)", f"{max_stress / 1e6:.2f}", "位于固定端附近"))
    else:
        r2.append(("最大 Equivalent Stress (MPa)", "N/A", "未能提取"))

    for name, val, note in r2:
        c = t2.add_row().cells
        c[0].text = name
        c[1].text = val
        c[2].text = note
    doc.add_paragraph()

    # ── 4. 可视化结果 ──
    doc.add_heading("4. 可视化结果", level=1)

    for plot in viz_results.get("plots", []):
        ptype = plot["type"]
        ppath = plot["path"]
        if Path(ppath).exists():
            if ptype == "stress":
                doc.add_paragraph("图 1：Equivalent Stress 云图")
            elif ptype == "displacement":
                doc.add_paragraph("图 2：Total Deformation 云图")
            doc.add_picture(ppath, width=Inches(5.5))
            doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            doc.add_paragraph()

    if not viz_results.get("plots"):
        doc.add_paragraph("（无可用的可视化图片，可能 Mechanical 未启动或后处理失败。）")

    # ── 5. 原始结果数据 ──
    doc.add_heading("5. 原始结果数据", level=1)
    if data:
        doc.add_paragraph(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        doc.add_paragraph("（未提取到结果数据。）")

    # ── 6. 结论 ──
    doc.add_paragraph()
    doc.add_heading("6. 结论", level=1)
    if sim_result.get("preview"):
        p = doc.add_paragraph(
            "ℹ️ 当前为预览模式。如需真实执行，请确保 Mechanical 环境可用，并添加 --launch 参数重新运行。"
        )
    elif sim_result.get("success"):
        if max_disp is not None:
            rel_error = abs(max_disp - expected) / abs(expected)
            if rel_error <= 0.25:
                p = doc.add_paragraph(
                    "✅ 验证通过：悬臂梁数值解与理论解的相对误差在允许范围内，仿真模型可信。"
                )
            else:
                p = doc.add_paragraph(
                    "❌ 验证未通过：相对误差超出容忍度，建议检查模型设置。"
                )
        else:
            p = doc.add_paragraph("⚠️ 求解已完成，但未能提取位移结果用于验证。")
    else:
        p = doc.add_paragraph("❌ Mechanical 执行失败，请检查环境配置和日志。")
    p.runs[0].font.bold = True

    doc_path = report_dir / "mechanical_cantilever_report.docx"
    doc.save(str(doc_path))
    print(f"[4/4] Word 报告已保存：{doc_path}")
    return doc_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Mechanical 悬臂梁报告生成")
    parser.add_argument("--launch", action="store_true", help="真实启动 Mechanical")
    args = parser.parse_args()

    workdir = PROJECT_ROOT / "runtime_data" / "mechanical_cantilever_report"
    workdir.mkdir(parents=True, exist_ok=True)

    report_dir = PROJECT_ROOT / "reports"
    report_dir.mkdir(exist_ok=True)

    runner = MechanicalRunner()
    pp = MechanicalPostProcessor(output_dir=str(report_dir))

    sim_result = run_mechanical_simulation(runner, args.launch, workdir)

    viz_results: dict = {"success": False, "plots": [], "data": {}}
    if args.launch and sim_result.get("success"):
        viz_results = generate_visualizations(runner, pp, workdir, report_dir)
    else:
        print("[2/4] 跳过可视化（未启动 Mechanical 或执行失败）。")

    doc_path = generate_word_report(report_dir, sim_result, viz_results, args.launch)
    print(f"\n全部完成！报告路径：{doc_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
