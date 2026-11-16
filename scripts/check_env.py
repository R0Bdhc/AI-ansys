#!/usr/bin/env python3
"""
check_env.py — cae-agent 部署前环境自检。

检查项（按阻断性分级）：
  [必须] Python 版本 ≥ 3.11
  [必须] 核心依赖可导入（fastapi / uvicorn / openai / dotenv / ansys-mapdl-core / 可视化三件套）
  [必须] 项目数据目录可写（runtime_data / reports / ansys_workspace）
  [提示] 可选依赖（ansys-mechanical-core / mcp / python-docx）
  [提示] ANSYS 求解器自动发现结果（版本与路径）
  [提示] .env 存在性与 LLM 配置状态

退出码：0 = 可以启动；1 = 存在必须项失败。
"""

from __future__ import annotations

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FAILURES: list[str] = []
WARNINGS: list[str] = []


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def check(name: str, ok: bool, detail: str = "", required: bool = True) -> None:
    mark = "PASS" if ok else ("FAIL" if required else "SKIP")
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        (FAILURES if required else WARNINGS).append(name)


def main() -> int:
    print(f"cae-agent 环境自检  |  项目根: {PROJECT_ROOT}")

    # ── 1. Python 版本 ──
    section("Python 版本")
    check(
        "Python ≥ 3.11",
        sys.version_info >= (3, 11),
        f"当前 {sys.version.split()[0]}",
    )

    # ── 2. 核心依赖 ──
    section("核心依赖")
    core_imports = [
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("openai", "openai"),
        ("python-dotenv", "dotenv"),
        ("pydantic", "pydantic"),
        ("ansys-mapdl-core", "ansys.mapdl.core"),
        ("pyvista", "pyvista"),
        ("matplotlib", "matplotlib"),
        ("numpy", "numpy"),
        ("platformdirs", "platformdirs"),
        ("appdirs", "appdirs"),
    ]
    for label, module in core_imports:
        try:
            __import__(module)
            check(f"导入 {label}", True)
        except Exception as exc:
            check(f"导入 {label}", False, str(exc)[:80])

    # ── 3. 可选依赖 ──
    section("可选依赖（缺失不影响核心功能）")
    optional_imports = [
        ("ansys-mechanical-core（Mechanical 242+）", "ansys.mechanical.core"),
        ("mcp（ansys-local MCP 服务器）", "mcp"),
        ("python-docx（scripts Word 报告）", "docx"),
    ]
    for label, module in optional_imports:
        try:
            __import__(module)
            check(f"导入 {label}", True, required=False)
        except Exception as exc:
            check(f"导入 {label}", False, f"{type(exc).__name__}（如需此能力请安装）", required=False)

    # ── 4. 项目数据目录可写 ──
    section("项目数据目录")
    from paths import project_path

    for name in ("runtime_data", "reports", "ansys_workspace"):
        target = project_path(name)
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            check(f"{name}/ 可写", True)
        except Exception as exc:
            check(f"{name}/ 可写", False, str(exc)[:80])

    # ── 5. 求解器发现 ──
    section("ANSYS 求解器自动发现")
    try:
        from ansys_discovery import (
            check_license_status,
            discover_mapdl,
            discover_mechanical,
            platform_label,
        )

        print(f"[INFO] 平台: {platform_label()}")
        mapdl = discover_mapdl()
        if mapdl["exec_path"]:
            check(
                f"MAPDL 发现（v{mapdl['version']}, {mapdl['source']}）",
                True,
                str(mapdl["exec_path"]),
                required=False,
            )
        else:
            check(
                "MAPDL 发现",
                False,
                "未找到——求解端点不可用，其余功能正常。可用 MAPDL_EXECUTABLE 显式指定",
                required=False,
            )

        mech = discover_mechanical()
        if mech["exec_path"]:
            version = mech["version"]
            ok = version is not None and version >= 242
            check(
                f"Mechanical 发现（v{version}, {mech['source']}）",
                ok,
                str(mech["exec_path"]),
                required=False,
            )
        else:
            check("Mechanical 发现", False, "未找到（可选能力）", required=False)

        license_info = check_license_status()
        print(f"[INFO] 许可证: {license_info['message']}")
    except Exception as exc:
        check("求解器发现模块", False, str(exc)[:100], required=False)

    # ── 6. .env 与 LLM 配置 ──
    section("LLM 配置")
    env_file = PROJECT_ROOT / ".env"
    check(
        ".env 存在",
        env_file.is_file(),
        "不存在时复制 .env.example 为 .env 并填写 LLM_API_KEY（可选）",
        required=False,
    )
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file)
        provider = __import__("os").getenv("LLM_PROVIDER", "")
        has_key = bool(__import__("os").getenv("LLM_API_KEY"))
        if has_key:
            check(f"LLM Key 已配置（{provider or 'deepseek'}）", True, required=False)
        else:
            check(
                "LLM Key 已配置",
                False,
                "未配置——诊断将回退本地规则；可启动后在仪表盘“配置 Key”运行时注入",
                required=False,
            )
    except Exception as exc:
        check("LLM 配置读取", False, str(exc)[:80], required=False)

    # ── 汇总 ──
    print("\n=== 汇总 ===")
    if FAILURES:
        print(f"阻断项 {len(FAILURES)} 个: {FAILURES}")
        print("结论: 不可启动，请先修复以上 FAIL 项。")
        return 1
    print("阻断项 0 个，可以启动。")
    if WARNINGS:
        print(f"提示项 {len(WARNINGS)} 个: {WARNINGS}")
    print("结论: 服务可启动；可选能力按上方 SKIP 提示按需安装。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
