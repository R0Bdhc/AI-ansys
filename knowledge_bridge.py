#!/usr/bin/env python3
"""
Knowledge Bridge — ansys-agent → obsidian-stack 集成接口

将仿真经验、错误诊断结论、批量处理记录等工程知识
自动推送到 Obsidian 知识库 (D:\\knowledgement)。

用法:
    from knowledge_bridge import push_experience
    push_experience(
        title="螺栓接触批量创建经验",
        content="对阵列螺栓使用 NS_SRC_ + NS_TGT_ 前缀批量配对...",
        tags=["接触分析", "批量处理", "Mechanical"]
    )
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from paths import project_path

# Obsidian Vault 目标路径（可通过环境变量覆盖；缺省为项目内 knowledge_vault，跨机器可移植）
VAULT_ROOT = Path(os.getenv("OBSIDIAN_VAULT_ROOT", "") or project_path("knowledge_vault"))
PROJECT_DIR = VAULT_ROOT / "Projects" / "ansysagent"


def push_experience(
    title: str,
    content: str,
    tags: Optional[list[str]] = None,
    category: str = "工程经验",
) -> Path:
    """
    将单条工程经验写入 Obsidian 知识库。

    Args:
        title: 经验标题（用于文件名和文档标题）
        content: Markdown 格式的经验内容
        tags: Obsidian 标签列表，如 ["接触分析", "批量处理"]
        category: 子分类目录名，默认 "工程经验"

    Returns:
        生成的 Markdown 文件路径
    """
    today = datetime.now().strftime("%Y-%m-%d")
    safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title).strip()
    filename = f"{today} {safe_title}.md"

    target_dir = PROJECT_DIR / category
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename

    tag_line = ""
    if tags:
        tag_line = "\n".join(f"#{t.replace(' ', '-')}" for t in tags) + "\n"

    markdown = f"""---
date: {today}
category: {category}
source: ansys-agent
---

# {title}

> 自动生成于 {today} | 来源: ansys-agent 仿真/分析过程

{tag_line}
## 内容

{content}

---
*由 knowledge_bridge 自动推送*
"""

    target_path.write_text(markdown, encoding="utf-8")
    return target_path


def push_report_summary(report_path: str | Path, summary: Optional[str] = None) -> Path:
    """
    将已有的 Markdown 报告摘要纳入知识库。

    Args:
        report_path: 原始报告文件路径（如 reports/2026-07-10-analysis.md）
        summary: 可选的自定义摘要；为空则读取报告前 50 行

    Returns:
        生成的知识库文件路径
    """
    report_path = Path(report_path)
    if summary is None and report_path.exists():
        lines = report_path.read_text(encoding="utf-8").splitlines()
        summary = "\n".join(lines[:50])

    title = report_path.stem
    return push_experience(
        title=f"报告摘要: {title}",
        content=f"""**原始报告**: `{report_path}`

**摘要**:

{summary}
""",
        tags=["报告", "日志分析"],
        category="报告归档",
    )


if __name__ == "__main__":
    # 简单自测
    test_path = push_experience(
        title="测试知识推送",
        content="这是一条测试经验，验证 knowledge_bridge 工作正常。",
        tags=["测试"],
    )
    print(f"已生成: {test_path}")
