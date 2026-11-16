"""
observability.py
轻量运行观测层：为仪表盘提供 LLM 调用、日志诊断、求解任务三类事件流。

设计：
- 线程安全环形缓冲（deque，自增 id），进程内低延迟读取；
- append-only JSONL 落盘（runtime_data/observability/events.jsonl），
  进程重启后事件可回放，作为二级兜底；
- 事件负载在入口处截断，防止单条超大 prompt/日志占满缓冲。
"""

from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime

from paths import project_path

_MAX_EVENTS = 500
_PREVIEW_CHARS = 1500
JournalHook = None  # 预留：外部可注入自定义持久化钩子

_lock = threading.Lock()
_events: deque[dict] = deque(maxlen=_MAX_EVENTS)
_next_id = 1
_journal_path = project_path("runtime_data", "observability", "events.jsonl")


def _truncate(value, limit: int = _PREVIEW_CHARS):
    """字符串截断；非字符串原样返回（数值/列表等直接进 JSON）。"""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "...(截断)"
    return value


def _persist(event: dict) -> None:
    try:
        _journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(_journal_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 落盘失败不影响内存事件流


def record_event(kind: str, message: str, payload: dict | None = None, level: str = "info") -> dict:
    """记录一条观测事件并返回完整事件（含 id 与时间戳）。"""
    global _next_id
    event = {
        "id": 0,  # 占位，加锁后填充
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "kind": kind,
        "level": level,
        "message": message,
        "payload": payload or {},
    }
    with _lock:
        event["id"] = _next_id
        _next_id += 1
        _events.append(event)
    _persist(event)
    return event


def get_events(since_id: int = 0, limit: int = 200) -> dict:
    """增量读取事件：返回 id > since_id 的事件（旧→新）与当前最大 id。"""
    with _lock:
        items = [dict(e) for e in _events if e["id"] > since_id]
        last_id = _events[-1]["id"] if _events else since_id
    items = items[-limit:]
    return {"events": items, "last_id": max(last_id, since_id), "total_in_buffer": len(_events)}


def replay_journal(limit: int = 500) -> list[dict]:
    """从落盘 JSONL 回放事件（用于进程重启后恢复仪表盘历史）。"""
    items: list[dict] = []
    try:
        with open(_journal_path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return items[-limit:]


# ───────────────────────────────
# 语义化便捷函数
# ───────────────────────────────

def record_llm_call(
    source_name: str,
    mode: str,
    model: str | None = None,
    provider: str | None = None,
    detected_error_count: int = 0,
    prompt: str | None = None,
    response: str | None = None,
    latency_ms: float | None = None,
    llm_error: str | None = None,
) -> dict:
    """记录一次 LLM/规则分析调用——仪表盘"LLM 接口输入"面板的数据源。"""
    payload = {
        "source_name": source_name,
        "mode": mode,
        "model": model,
        "provider": provider,
        "detected_error_count": detected_error_count,
        "prompt_preview": _truncate(prompt),
        "response_preview": _truncate(response),
        "latency_ms": round(latency_ms, 1) if latency_ms is not None else None,
        "llm_error": _truncate(llm_error, 300),
    }
    level = "error" if llm_error else "info"
    return record_event("llm_call", f"LLM 分析：{source_name}（{mode}）", payload, level=level)


def record_log_analysis(
    source: str,
    error_count: int,
    codes: list[str],
    text_chars: int = 0,
    report_path: str | None = None,
) -> dict:
    """记录一次日志读取与错误检测——仪表盘"日志/错误检测流"面板的数据源。"""
    payload = {
        "source": source,
        "error_count": error_count,
        "codes": codes,
        "text_chars": text_chars,
        "report_path": report_path,
    }
    level = "warning" if error_count else "info"
    return record_event("log_analysis", f"日志诊断：{source}（{error_count} 个错误）", payload, level=level)


def record_solve_run(
    run_id: str,
    kind: str,
    status: str,
    message: str = "",
    extra: dict | None = None,
) -> dict:
    """记录求解任务状态转移——仪表盘任务面板的事件流。"""
    payload = {"run_id": run_id, "kind": kind, "status": status}
    if extra:
        payload.update(extra)
    level = {"failed": "error", "timeout": "error", "completed": "success"}.get(status, "info")
    return record_event("solve_run", message or f"任务 {run_id} → {status}", payload, level=level)
