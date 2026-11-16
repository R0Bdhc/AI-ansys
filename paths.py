"""
paths.py
项目路径锚定：所有模块的文件系统默认路径统一经此模块解析到项目根。

跨机器部署的关键约定：
- 不得使用相对 CWD 的路径（从任意目录启动 uvicorn 都必须正确落盘）；
- 不得在业务模块里硬编码绝对盘符路径；
- 机器专属配置（ANSYS 安装路径、Obsidian 库位置）一律走环境变量，
  缺省值只做项目内兜底。
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def project_path(*parts: str | Path) -> Path:
    """返回相对项目根的绝对路径。"""
    return PROJECT_ROOT.joinpath(*parts)
