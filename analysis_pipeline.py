"""
analysis_pipeline.py
统一诊断分析链路：错误检测 → 证据合并 → LLM 分析 → 报告生成 → 落盘。

同步端点与异步 job 共用同一条链路，保证行为一致；
LLMAnalyzer 使用模块级单例，健康检查缓存全局共享。
"""

from __future__ import annotations

from llm_analyzer import LLMAnalyzer
from log_parser import detect_errors
from observability import record_log_analysis
from report_generator import build_markdown_report, save_markdown_report

_llm_analyzer: LLMAnalyzer | None = None

_EVIDENCE_SUMMARY_MAX_CHARS = 2500
_SNIPPET_MAX_CHARS = 500


def get_llm_analyzer() -> LLMAnalyzer:
    """返回全局唯一的 LLMAnalyzer 实例。"""
    global _llm_analyzer
    if _llm_analyzer is None:
        _llm_analyzer = LLMAnalyzer()
    return _llm_analyzer


def evidence_summary_text(evidence: dict | None) -> str:
    """把证据包压成紧凑文本，拼在分析源日志之前，让 LLM 直接看到全场结构化证据。"""
    if not evidence:
        return ""

    lines: list[str] = ["=== 实时诊断证据（solve_watcher 流式采集） ==="]
    lines.append(
        f"监视目录: {evidence.get('watch_dir', '?')} | 结束原因: {evidence.get('reason', '?')}"
        f" | 持续: {evidence.get('duration_s', 0)}s | 采集字节: {evidence.get('total_bytes_seen', 0)}"
        f" | 输出静默: {'是' if evidence.get('stalled') else '否'}"
    )
    for event in evidence.get("error_events") or []:
        lines.append(
            f"[ERROR] {event.get('code')} {event.get('title')} x{event.get('count', 1)}"
            f" 首现 {event.get('first_seen', '')} 建议: {event.get('suggestion', '')}"
        )
    for event in evidence.get("warning_events") or []:
        lines.append(
            f"[WARNING] {event.get('code')} {event.get('title')} x{event.get('count', 1)}"
            f" 首现 {event.get('first_seen', '')} 建议: {event.get('suggestion', '')}"
        )
    unmatched = evidence.get("unmatched") or {}
    for level in ("ERROR", "WARNING"):
        count = (unmatched.get(level) or {}).get("count", 0)
        if count:
            lines.append(f"[UNMATCHED-{level}] x{count}")

    summary = "\n".join(lines)
    if len(summary) > _EVIDENCE_SUMMARY_MAX_CHARS:
        summary = summary[:_EVIDENCE_SUMMARY_MAX_CHARS] + "\n...(截断)"
    return summary


def merge_evidence_errors(detected_errors: list[dict] | None, evidence: dict | None) -> list[dict]:
    """把证据中的 ERROR 事件合并进检测结果，按 error_code 去重（流式证据可能比日志尾部更完整）。"""
    merged = list(detected_errors or [])
    if not evidence:
        return merged

    existing_codes = {item.get("error_code") for item in merged}
    for event in evidence.get("error_events") or []:
        code = event.get("code")
        if not code or code in existing_codes:
            continue
        merged.append(
            {
                "error_code": code,
                "title": event.get("title", code),
                "description": event.get("description", ""),
                "matched_text": event.get("matched_text", code),
                "snippet": (event.get("text") or "")[:_SNIPPET_MAX_CHARS],
                "suggestion": event.get("suggestion", ""),
                "occurrences": event.get("count", 1),
                "source": "solve_watcher",
            }
        )
        existing_codes.add(code)
    return merged


def analyze_execution(
    source_name: str,
    log_text: str,
    detected_errors: list[dict] | None = None,
    evidence: dict | None = None,
    engineering_results: dict | None = None,
    image_paths: list[str] | None = None,
    llm_analyzer: LLMAnalyzer | None = None,
) -> dict:
    """统一诊断链路，返回可直接挂到 result["analysis"] 的 dict。"""
    analyzer = llm_analyzer or get_llm_analyzer()

    if detected_errors is None:
        detected_errors = detect_errors(log_text or "") if log_text else []
    detected_errors = merge_evidence_errors(detected_errors, evidence)

    analysis_source = log_text or ""
    summary = evidence_summary_text(evidence)
    if summary:
        analysis_source = summary + "\n\n" + analysis_source

    llm_result = analyzer.analyze(
        source_name=source_name,
        log_text=analysis_source,
        detected_errors=detected_errors,
    )

    markdown_content = build_markdown_report(
        source_name=source_name,
        detected_errors=detected_errors,
        llm_result=llm_result,
        engineering_results=engineering_results,
        image_paths=image_paths,
        evidence=evidence,
    )
    report_path = save_markdown_report(markdown_content)

    record_log_analysis(
        source=source_name,
        error_count=len(detected_errors),
        codes=sorted({item["error_code"] for item in detected_errors}),
        text_chars=len(log_text or ""),
        report_path=str(report_path),
    )

    return {
        "success": True,
        "source_name": source_name,
        "error_count": len(detected_errors),
        "detected_errors": detected_errors,
        "llm_result": llm_result,
        "report_path": str(report_path),
        "markdown_preview": markdown_content,
    }
