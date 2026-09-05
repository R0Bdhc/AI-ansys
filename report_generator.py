from datetime import datetime
from pathlib import Path

# 集成 obsidian-stack 知识推送
from knowledge_bridge import push_report_summary


def build_markdown_report(
    source_name: str,
    detected_errors: list[dict],
    llm_result: dict,
    engineering_results: dict | None = None,
    image_paths: list[str] | None = None,
    evidence: dict | None = None,
) -> str:
    """构造 Markdown 报告内容，可选嵌入可视化图片与流式诊断证据。"""
    lines: list[str] = []

    lines.append("# CAE 日志分析报告")
    lines.append("")
    lines.append(f"- 日志来源：`{source_name}`")
    lines.append(f"- 生成时间：`{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`")
    lines.append(f"- 检测到错误数量：`{len(detected_errors)}`")
    lines.append("")

    # ── 求解结果数据（优先展示，因与求解质量直接相关） ──
    if engineering_results:
        lines.append("## 1. 求解结果数据")
        lines.append("")
        _render_engineering_results(lines, engineering_results)

    section = 2
    error_section = section
    section += 1
    evidence_section = section
    section += 1
    llm_section = section

    # ── 可视化结果 ──
    if image_paths:
        lines.append(f"## {error_section}. 后处理可视化")
        lines.append("")
        for img_path in image_paths:
            img_name = Path(img_path).name
            lines.append(f"### {img_name}")
            lines.append("")
            lines.append(f"![{img_name}]({img_path})")
            lines.append("")
        error_section += 1
        evidence_section += 1
        llm_section += 1

    lines.append(f"## {error_section}. 错误检测结果")
    lines.append("")

    if not detected_errors:
        lines.append("未检测到预设错误关键词。")
        lines.append("")
    else:
        for index, item in enumerate(detected_errors, start=1):
            lines.append(f"### {error_section}.{index} {item['title']}")
            lines.append("")
            lines.append(f"- 错误代码：`{item['error_code']}`")
            lines.append(f"- 匹配文本：`{item['matched_text']}`")
            lines.append(f"- 错误说明：{item['description']}")
            if item.get("occurrences", 1) > 1:
                lines.append(f"- 出现次数：{item['occurrences']}")
            if item.get("suggestion"):
                lines.append(f"- 修正建议：{item['suggestion']}")
            lines.append("")
            lines.append("```text")
            lines.append(item["snippet"])
            lines.append("```")
            lines.append("")

    if evidence:
        _render_evidence(lines, evidence, evidence_section)

    lines.append(f"## {llm_section}. LLM / 规则分析结果")
    lines.append("")
    lines.append(f"- 分析模式：`{llm_result.get('mode', 'unknown')}`")
    lines.append(f"- 分析摘要：{llm_result.get('summary', '无')}")
    lines.append("")

    raw_analysis = llm_result.get("raw_analysis")
    if raw_analysis:
        lines.append(f"### {llm_section}.1 DeepSeek 原始分析")
        lines.append("")
        lines.append(raw_analysis)
        lines.append("")

    possible_causes = llm_result.get("possible_causes", [])
    if possible_causes:
        lines.append(f"### {llm_section}.2 可能原因")
        lines.append("")
        for item in possible_causes:
            lines.append(f"- {item}")
        lines.append("")

    suggestions = llm_result.get("suggestions", [])
    if suggestions:
        lines.append(f"### {llm_section}.3 修改建议")
        lines.append("")
        for item in suggestions:
            lines.append(f"- {item}")
        lines.append("")

    llm_error = llm_result.get("llm_error")
    if llm_error:
        lines.append(f"### {llm_section}.4 LLM 调用异常")
        lines.append("")
        lines.append(f"`{llm_error}`")
        lines.append("")

    return "\n".join(lines)


def _render_engineering_results(lines: list[str], results: dict) -> None:
    """在 Markdown 行列表中渲染工程结果数据段。"""
    extraction_error = results.get("extraction_error")
    if extraction_error:
        lines.append(f"> 结果提取异常：{extraction_error}")
        lines.append("")
        return

    displacement = results.get("displacement")
    if displacement:
        lines.append("### 1.1 位移")
        lines.append("")
        lines.append("| 指标 | 最大值 |")
        lines.append("|------|--------|")
        for key in ("max_usum", "max_ux", "max_uy", "max_uz"):
            value = displacement.get(key)
            if value is not None:
                label = displacement.get(f"label_{key[4:]}", key)
                lines.append(f"| {label} | {value:.6e} |")
        lines.append("")

    stress = results.get("stress")
    if stress:
        lines.append("### 1.2 应力")
        lines.append("")
        lines.append("| 指标 | 最大值 |")
        lines.append("|------|--------|")
        for key in ("max_von_mises", "max_s1", "max_s3", "max_sx"):
            value = stress.get(key)
            if value is not None:
                label = stress.get(f"label_{key[4:]}", key)
                lines.append(f"| {label} | {value:.6e} |")
        lines.append("")

    reaction = results.get("reaction_forces")
    if reaction:
        lines.append("### 1.3 支反力合力")
        lines.append("")
        lines.append("| 方向 | 合力 |")
        lines.append("|------|------|")
        for axis in ("fx", "fy", "fz"):
            value = reaction.get(axis)
            if value is not None:
                lines.append(f"| {axis.upper()} | {value:.6e} |")
        lines.append("")

    frequency = results.get("frequency")
    if frequency:
        modes = frequency.get("modes", [])
        if modes:
            lines.append("### 1.4 模态频率")
            lines.append("")
            lines.append("| 阶数 | 频率 (Hz) |")
            lines.append("|------|-----------|")
            for mode in modes:
                lines.append(f"| {mode['order']} | {mode['frequency_hz']:.4f} |")
            lines.append("")


def _render_evidence(lines: list[str], evidence: dict, section_num: int) -> None:
    """渲染流式诊断证据段（来自 solve_watcher 的 finalize 证据包）。全部字段防御式读取。"""
    lines.append(f"## {section_num}. 实时诊断证据（流式监视）")
    lines.append("")
    lines.append(
        f"- 监视目录：`{evidence.get('watch_dir', '未知')}`"
        f" ｜ 结束原因：`{evidence.get('reason', 'unknown')}`"
        f" ｜ 持续：`{evidence.get('duration_s', 0)}s`"
        f" ｜ 采集字节：`{evidence.get('total_bytes_seen', 0)}`"
    )
    if evidence.get("stalled"):
        lines.append("- ⚠️ 求解输出出现静默期（stalled），可能存在求解停滞。")
    if evidence.get("watcher_error"):
        lines.append(f"- 监视器异常：`{evidence['watcher_error']}`")
    lines.append("")

    error_events = evidence.get("error_events") or []
    warning_events = evidence.get("warning_events") or []

    if error_events:
        lines.append(f"### {section_num}.1 错误事件")
        lines.append("")
        lines.append("| 代码 | 标题 | 次数 | 首次出现 | 来源 |")
        lines.append("|------|------|------|----------|------|")
        for event in error_events:
            lines.append(
                f"| `{event.get('code', 'unknown')}` | {event.get('title', '')} "
                f"| {event.get('count', 1)} | {event.get('first_seen', '')} "
                f"| {event.get('source_file', '')} |"
            )
        lines.append("")

    if warning_events:
        lines.append(f"### {section_num}.2 警告事件")
        lines.append("")
        lines.append("| 代码 | 标题 | 次数 | 首次出现 | 建议 |")
        lines.append("|------|------|------|----------|------|")
        for event in warning_events:
            lines.append(
                f"| `{event.get('code', 'unknown')}` | {event.get('title', '')} "
                f"| {event.get('count', 1)} | {event.get('first_seen', '')} "
                f"| {event.get('suggestion', '')} |"
            )
        lines.append("")

    unmatched = evidence.get("unmatched") or {}
    unmatched_lines = []
    for level in ("ERROR", "WARNING"):
        bucket = unmatched.get(level) or {}
        count = bucket.get("count", 0)
        if count:
            unmatched_lines.append(f"- 未匹配{level}块：`{count}` 个（已保留前 {len(bucket.get('samples', []))} 条样本）")
    if unmatched_lines:
        lines.append(f"### {section_num}.3 未归类诊断块")
        lines.append("")
        lines.extend(unmatched_lines)
        lines.append("")

    suggestions = evidence.get("suggestions") or []
    if suggestions:
        lines.append(f"### {section_num}.4 证据驱动的修正建议")
        lines.append("")
        for item in suggestions:
            lines.append(f"- {item}")
        lines.append("")

    log_tail = evidence.get("log_tail") or {}
    if log_tail:
        lines.append(f"### {section_num}.5 求解日志尾部快照")
        lines.append("")
        for filename, content in log_tail.items():
            lines.append(f"**{filename}**（最后 {content.count(chr(10)) + 1} 行）")
            lines.append("")
            lines.append("```text")
            lines.append(content)
            lines.append("```")
            lines.append("")

    journal_path = evidence.get("journal_path")
    if journal_path:
        lines.append(f"> 完整证据流水：`{journal_path}`")
        lines.append("")


def save_markdown_report(
    markdown_content: str,
    output_dir: str | Path = "reports",
    push_to_knowledge: bool = True,
) -> Path:
    """把 Markdown 报告保存到本地文件，并可选推送至 Obsidian 知识库。"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_file = output_path / filename
    report_file.write_text(markdown_content, encoding="utf-8")

    # 推送报告摘要到知识库
    if push_to_knowledge:
        try:
            push_report_summary(report_file, summary=markdown_content[:2000])
        except Exception:
            # 知识推送失败不应阻断报告保存
            pass

    return report_file
