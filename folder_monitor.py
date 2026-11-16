"""
folder_monitor.py
被动项目文件夹监听器：持续跟踪用户选定项目目录中的求解日志。

实时性策略（分级实时，与活动 job 的 1s watcher 区分）：
- 中等频率轮询：默认 5s 可配——消费端是人看面板与触发式 LLM 诊断，秒级已足够；
- 静默退避：整个监听树连续 quiet_minutes 无任何新内容 → 轮询间隔翻倍至 max_interval
  上限，任何活动立即恢复基础间隔——避免在大项目树上持续做无谓 I/O；
- 稳定触发：文件停止增长 settle_seconds 或出现求解终止标记（ROUTINE COMPLETED）
  才标记"可分析"，避免对半截日志反复触发昂贵的 LLM 调用——读取便宜、触发才贵。

职责边界：只读文件、只做模式分类与事件记录；LLM 分析由外部回调（Manager）执行。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from log_parser import ERROR_PATTERNS, WARNING_PATTERNS
from observability import record_event
from paths import project_path
from solve_watcher import BlockStreamParser, _normalize_for_signature

_SOLVE_DONE_MARKER = re.compile(r"ROUTINE\s+COMPLETED", re.IGNORECASE)
_MAX_UNMATCHED_SAMPLES = 5
_EVENT_TEXT_LIMIT = 1200


class FolderMonitor:
    """单个项目目录的被动监听器。"""

    def __init__(
        self,
        path: str | Path,
        monitor_id: str | None = None,
        interval: float = 5.0,
        depth: int = 3,
        auto_analyze: bool = False,
        settle_seconds: float = 10.0,
        quiet_backoff_minutes: float = 10.0,
        max_interval: float = 60.0,
        file_suffixes: tuple[str, ...] = (".out", ".err"),
        on_settle: Callable[["FolderMonitor", str, dict], None] | None = None,
        created_at_override: str | None = None,
        paused: bool = False,
    ) -> None:
        self.monitor_id = monitor_id or f"mon_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.path = Path(path)
        self.interval = max(1.0, float(interval))
        self.depth = max(0, int(depth))
        self.auto_analyze = bool(auto_analyze)
        self.settle_seconds = float(settle_seconds)
        self.quiet_backoff_minutes = float(quiet_backoff_minutes)
        self.max_interval = float(max_interval)
        self.file_suffixes = tuple(s.lower() for s in file_suffixes)
        self.on_settle = on_settle
        self.created_at = created_at_override or datetime.now().isoformat(timespec="seconds")

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._file_state: dict[str, dict] = {}  # rel_key -> 偏移/解析器/增长时间/稳定标记
        self._events: dict[str, dict] = {}      # signature -> event（file+level+归一化文本）
        self._unmatched_count = {"ERROR": 0, "WARNING": 0}
        self._unmatched_samples: list[dict] = []
        self._last_activity = time.monotonic()
        self._current_interval = self.interval
        self._watcher_error: str | None = None
        self._started_monotonic: float | None = None
        self._paused = bool(paused)

    # ───────────────────────────────
    # 生命周期
    # ───────────────────────────────

    def start(self) -> None:
        if self._thread is not None:
            return
        if not self.path.is_dir():
            raise NotADirectoryError(f"监听路径不存在或不是目录：{self.path}")
        self._started_monotonic = time.monotonic()
        self._thread = threading.Thread(target=self._loop, name=f"folder-monitor-{self.monitor_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self._current_interval))
            self._thread = None

    # ───────────────────────────────
    # 主循环：扫描 → 增量解析 → 稳定检查 → 退避
    # ───────────────────────────────

    def _loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                if self._paused:
                    # 暂停：不扫描不触发，线程保持存活以便即时恢复
                    self._stop_event.wait(0.5)
                    continue
                self._scan_once()
                self._check_settles()
                self._adjust_backoff()
                self._stop_event.wait(self._current_interval)
        except Exception as exc:
            self._watcher_error = f"{type(exc).__name__}: {exc}"

    def _iter_candidate_files(self) -> list[Path]:
        """有界递归枚举匹配后缀的文件；跳过隐藏目录。"""
        found: list[Path] = []
        root_depth = len(self.path.parts)
        for dirpath, dirnames, filenames in os.walk(self.path):
            rel_depth = len(Path(dirpath).parts) - root_depth
            if rel_depth >= self.depth:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                if name.lower().endswith(self.file_suffixes):
                    found.append(Path(dirpath) / name)
        return found

    def _scan_once(self) -> None:
        grew_any = False
        for file_path in self._iter_candidate_files():
            rel_key = file_path.relative_to(self.path).as_posix()
            try:
                size = file_path.stat().st_size
            except OSError:
                continue

            with self._lock:
                state = self._file_state.get(rel_key)
                if state is None:
                    state = {
                        "offset": 0,
                        "parser": BlockStreamParser(),
                        "last_growth": time.monotonic(),
                        "size": 0,
                        "settled": False,
                        "blocks_since_settle": 0,
                        "error_since_settle": 0,
                        "warning_since_settle": 0,
                        "done_marker_seen": False,
                    }
                    self._file_state[rel_key] = state

            if size <= state["offset"]:
                continue

            try:
                with open(file_path, "rb") as handle:
                    handle.seek(state["offset"])
                    raw = handle.read()
            except OSError:
                continue

            state["offset"] += len(raw)
            state["size"] = size
            state["last_growth"] = time.monotonic()
            state["settled"] = False
            grew_any = True

            text = raw.decode("utf-8", errors="replace")
            if _SOLVE_DONE_MARKER.search(text):
                state["done_marker_seen"] = True

            blocks = state["parser"].feed(text)
            for block in blocks:
                self._classify_block(rel_key, block)
                with self._lock:
                    state["blocks_since_settle"] += 1

        if grew_any:
            self._last_activity = time.monotonic()
            self._current_interval = self.interval

    def _classify_block(self, rel_key: str, block: dict) -> None:
        level = block.get("level")
        if level not in ("ERROR", "WARNING"):
            return
        text = block.get("text", "")
        patterns = ERROR_PATTERNS if level == "ERROR" else WARNING_PATTERNS
        matched = None
        for code, config in patterns.items():
            found = re.search(config["pattern"], text, flags=re.IGNORECASE)
            if found:
                matched = (code, config, found.group(0))
                break

        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            state = self._file_state.get(rel_key)
            if level == "ERROR":
                state["error_since_settle"] += 1
            else:
                state["warning_since_settle"] += 1

            if matched is None:
                self._unmatched_count[level] += 1
                if len(self._unmatched_samples) < _MAX_UNMATCHED_SAMPLES:
                    sample = {
                        "monitor_id": self.monitor_id,
                        "file": rel_key,
                        "level": level,
                        "seen_at": now,
                        "text": text[:_EVENT_TEXT_LIMIT],
                    }
                    self._unmatched_samples.append(sample)
                    record_event(
                        "monitor_event",
                        f"监听发现未归类{level}块：{rel_key}",
                        sample,
                        level="info",
                    )
                return

            code, config, matched_text = matched
            signature = f"{rel_key}|{level}|{_normalize_for_signature(text)}"
            event = self._events.get(signature)
            if event is not None:
                event["count"] += 1
                event["last_seen"] = now
                record_event(
                    "monitor_event",
                    f"监听{level}重复：{rel_key} {code} ×{event['count']}",
                    {"monitor_id": self.monitor_id, "file": rel_key, "level": level, "code": code, "count": event["count"]},
                    level="info",
                )
                return

            event = {
                "monitor_id": self.monitor_id,
                "file": rel_key,
                "level": level,
                "code": code,
                "title": config.get("title", code),
                "description": config.get("description", ""),
                "suggestion": config.get("suggestion", ""),
                "matched_text": matched_text,
                "count": 1,
                "first_seen": now,
                "last_seen": now,
                "text": text[:_EVENT_TEXT_LIMIT],
            }
            self._events[signature] = event
            record_event(
                "monitor_event",
                f"监听发现{level}：{rel_key} {code}（{config.get('title', code)}）",
                {k: event[k] for k in ("monitor_id", "file", "level", "code", "title", "suggestion", "count", "text")},
                level="warning" if level == "WARNING" else "error",
            )

    def _check_settles(self) -> None:
        now = time.monotonic()
        with self._lock:
            states = [(key, dict(state)) for key, state in self._file_state.items()]
        for key, snapshot in states:
            quiet_for = now - snapshot["last_growth"]
            stable_by_time = quiet_for >= self.settle_seconds
            stable_by_marker = snapshot["done_marker_seen"] and quiet_for >= 1.0
            if not (stable_by_time or stable_by_marker):
                continue
            with self._lock:
                state = self._file_state.get(key)
                if state is None or state["settled"]:
                    continue
                if state["size"] == 0:
                    continue
                state["settled"] = True
                summary = {
                    "file": key,
                    "size": state["size"],
                    "blocks_since_settle": state["blocks_since_settle"],
                    "error_since_settle": state["error_since_settle"],
                    "warning_since_settle": state["warning_since_settle"],
                    "done_marker": state["done_marker_seen"],
                }
                state["blocks_since_settle"] = 0
                state["error_since_settle"] = 0
                state["warning_since_settle"] = 0
                state["done_marker_seen"] = False
            self._emit_settle(key, summary)

    def _emit_settle(self, rel_key: str, summary: dict) -> None:
        record_event(
            "monitor_event",
            f"文件已稳定可分析：{rel_key}（错误 {summary['error_since_settle']} / 警告 {summary['warning_since_settle']}）",
            {"monitor_id": self.monitor_id, **summary},
            level="info",
        )
        if self.on_settle is not None:
            try:
                self.on_settle(self, rel_key, summary)
            except Exception as exc:
                self._watcher_error = f"on_settle 回调失败：{exc}"

    def _adjust_backoff(self) -> None:
        with self._lock:
            quiet_seconds = time.monotonic() - self._last_activity
        if quiet_seconds < self.quiet_backoff_minutes * 60:
            self._current_interval = self.interval
            return
        self._current_interval = min(self._current_interval * 2, self.max_interval)

    # ───────────────────────────────
    # 查询与操作
    # ───────────────────────────────

    def force_settle_all(self) -> None:
        """把所有未稳定文件立即标记稳定（人工分析前调用，保证摘要收口）。"""
        with self._lock:
            for state in self._file_state.values():
                state["last_growth"] = 0.0
                state["settled"] = False

    def set_auto_analyze(self, enabled: bool) -> None:
        self.auto_analyze = bool(enabled)

    def set_paused(self, paused: bool) -> None:
        """暂停/恢复监听：暂停期间不扫描不触发，线程保持存活。"""
        self._paused = bool(paused)

    def view(self) -> dict:
        with self._lock:
            events = sorted(self._events.values(), key=lambda e: e["first_seen"])
            error_count = sum(e["count"] for e in events if e["level"] == "ERROR")
            warning_count = sum(e["count"] for e in events if e["level"] == "WARNING")
            view = {
                "monitor_id": self.monitor_id,
                "path": str(self.path),
                "status": "paused" if self._paused else ("running" if self._thread is not None else "stopped"),
                "paused": self._paused,
                "interval": self.interval,
                "effective_interval": round(self._current_interval, 1),
                "backing_off": self._current_interval > self.interval,
                "depth": self.depth,
                "auto_analyze": self.auto_analyze,
                "created_at": self.created_at,
                "files_tracked": len(self._file_state),
                "error_event_count": error_count,
                "warning_event_count": warning_count,
                "matched_error_codes": sorted({e["code"] for e in events if e["level"] == "ERROR"}),
                "unmatched": dict(self._unmatched_count),
                "watcher_error": self._watcher_error,
                "recent_events": [
                    {k: e.get(k) for k in ("file", "level", "code", "title", "count", "first_seen")}
                    for e in events[-5:]
                ],
            }
        return view

    def _resolve_tracked_file(self, rel_key: str) -> Path | None:
        """解析监听内相对路径并做目录包含校验（rel_key 来自 API 外部输入，防路径穿越）。"""
        try:
            candidate = (self.path / rel_key).resolve()
        except (OSError, ValueError):
            return None
        root = self.path.resolve()
        if candidate != root and root not in candidate.parents:
            return None
        return candidate

    def file_text(self, rel_key: str, max_bytes: int = 200_000) -> str | None:
        """读取被监听文件的尾部内容（供 LLM 分析），超出上限取尾部。"""
        with self._lock:
            state = self._file_state.get(rel_key)
        file_path = self._resolve_tracked_file(rel_key)
        if file_path is None or not file_path.is_file():
            return None
        try:
            size = file_path.stat().st_size
            with open(file_path, "rb") as handle:
                handle.seek(max(0, size - max_bytes))
                return handle.read(max_bytes).decode("utf-8", errors="replace")
        except OSError:
            return None

    def file_event_summary(self, rel_key: str) -> dict:
        with self._lock:
            events = [e for e in self._events.values() if e["file"] == rel_key]
        return {
            "file": rel_key,
            "events": [dict(e) for e in sorted(events, key=lambda e: e["first_seen"])],
        }


class FolderMonitorManager:
    """监听器注册表：创建/枚举/删除/切换自动分析，配置持久化，服务重启后恢复。"""

    def __init__(self, persistence_path: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        self._monitors: dict[str, FolderMonitor] = {}
        self._persistence_path = Path(persistence_path) if persistence_path else project_path("runtime_data", "monitors.json")
        self._llm_analyzer = None  # 延迟注入，避免循环依赖
        self._restore()

    def bind_llm_analyzer(self, llm_analyzer) -> None:
        self._llm_analyzer = llm_analyzer

    # ── 公开接口 ──

    def create(
        self,
        path: str,
        interval: float = 5.0,
        depth: int = 3,
        auto_analyze: bool = False,
    ) -> FolderMonitor:
        monitor = FolderMonitor(
            path=path,
            interval=interval,
            depth=depth,
            auto_analyze=auto_analyze,
            on_settle=self._handle_settle,
        )
        monitor.start()
        with self._lock:
            self._monitors[monitor.monitor_id] = monitor
        self._persist()
        record_event("monitor_event", f"创建项目监听：{path}", {"monitor_id": monitor.monitor_id, "path": str(monitor.path)})
        return monitor

    def remove(self, monitor_id: str) -> bool:
        with self._lock:
            monitor = self._monitors.pop(monitor_id, None)
        if monitor is None:
            return False
        monitor.stop()
        self._persist()
        record_event("monitor_event", f"移除项目监听：{monitor.path}", {"monitor_id": monitor_id})
        return True

    def get(self, monitor_id: str) -> FolderMonitor | None:
        with self._lock:
            return self._monitors.get(monitor_id)

    def list_views(self) -> list[dict]:
        with self._lock:
            monitors = list(self._monitors.values())
        return [m.view() for m in sorted(monitors, key=lambda m: m.created_at, reverse=True)]

    def set_auto_analyze(self, monitor_id: str, enabled: bool) -> bool:
        monitor = self.get(monitor_id)
        if monitor is None:
            return False
        monitor.set_auto_analyze(enabled)
        self._persist()
        return True

    def set_paused(self, monitor_id: str, paused: bool) -> bool:
        monitor = self.get(monitor_id)
        if monitor is None:
            return False
        monitor.set_paused(paused)
        self._persist()
        record_event(
            "monitor_event",
            f"{'暂停' if paused else '恢复'}项目监听：{monitor.path}",
            {"monitor_id": monitor_id, "paused": bool(paused)},
        )
        return True

    # ── 稳定触发 → LLM 分析（自动开关）──

    def _handle_settle(self, monitor: FolderMonitor, rel_key: str, summary: dict) -> None:
        if not monitor.auto_analyze:
            return
        if summary.get("error_since_settle", 0) <= 0:
            return  # 无错误不烧 LLM；警告仅面板标记
        threading.Thread(
            target=self.run_analysis,
            args=(monitor.monitor_id, rel_key),
            name=f"monitor-analyze-{monitor.monitor_id}",
            daemon=True,
        ).start()

    def run_analysis(self, monitor_id: str, rel_key: str, force: bool = False) -> dict:
        """对监听文件执行 LLM 分析链路（人工触发或自动开关）。"""
        monitor = self.get(monitor_id)
        if monitor is None:
            return {"success": False, "message": f"监听不存在：{monitor_id}"}

        text = monitor.file_text(rel_key)
        if text is None:
            return {"success": False, "message": f"文件不存在：{rel_key}"}

        from analysis_pipeline import analyze_execution

        result = analyze_execution(
            source_name=str(monitor.path / rel_key),
            log_text=text,
            llm_analyzer=self._llm_analyzer,
        )
        record_event(
            "monitor_event",
            f"监听文件 LLM 分析完成：{rel_key}（{result.get('error_count', 0)} 个错误）",
            {
                "monitor_id": monitor_id,
                "file": rel_key,
                "error_count": result.get("error_count", 0),
                "codes": sorted({item["error_code"] for item in result.get("detected_errors", [])}),
                "report_path": result.get("report_path"),
            },
            level="info",
        )
        return result

    # ── 持久化 ──

    def _persist(self) -> None:
        try:
            with self._lock:
                configs = [
                    {
                        "monitor_id": m.monitor_id,
                        "path": str(m.path),
                        "interval": m.interval,
                        "depth": m.depth,
                        "auto_analyze": m.auto_analyze,
                        "paused": m._paused,
                        "created_at": m.created_at,
                    }
                    for m in self._monitors.values()
                ]
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            self._persistence_path.write_text(json.dumps(configs, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _restore(self) -> None:
        try:
            configs = json.loads(self._persistence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for config in configs:
            try:
                monitor = FolderMonitor(
                    path=config["path"],
                    monitor_id=config["monitor_id"],
                    interval=config.get("interval", 5.0),
                    depth=config.get("depth", 3),
                    auto_analyze=config.get("auto_analyze", False),
                    created_at_override=config.get("created_at"),
                    paused=config.get("paused", False),
                    on_settle=self._handle_settle,
                )
                monitor.start()
                with self._lock:
                    self._monitors[monitor.monitor_id] = monitor
            except Exception:
                continue  # 单个监听恢复失败不影响其他


# ───────────────────────────────
# 自测：合成项目目录渐进写入
# ───────────────────────────────

if __name__ == "__main__":
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="folder_monitor_test_"))
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        status = "PASS" if condition else "FAIL"
        print(f"[{status}] {name}" + (f" — {detail}" if detail and not condition else ""))
        if not condition:
            failures.append(name)

    settled_seen: list[tuple[str, dict]] = []
    monitor = FolderMonitor(
        tmp,
        monitor_id="mon_selftest",
        interval=0.3,
        depth=2,
        settle_seconds=1.0,
        on_settle=lambda m, k, s: settled_seen.append((k, s)),
    )
    monitor.start()

    # 1) 根目录文件 + 子目录文件均被发现，错误被分类
    (tmp / "case1.out").write_text(
        "*** ERROR *** CP = 1.0\nA singular matrix was detected at node 3.\n\n",
        encoding="utf-8",
    )
    sub = tmp / "solve" / "run2"
    sub.mkdir(parents=True)
    (sub / "file0.err").write_text(
        "*** WARNING *** CP = 2.0\nThe initial penetration between contact pair 1 is 0.2.\n\n",
        encoding="utf-8",
    )
    time.sleep(1.2)
    view = monitor.view()
    check("发现 2 个文件", view["files_tracked"] == 2, str(view["files_tracked"]))
    check("错误事件命中 singular_matrix", "singular_matrix" in view["matched_error_codes"], str(view["matched_error_codes"]))

    # 2) 同文件追加同签名警告 → 去重计数
    with open(sub / "file0.err", "a", encoding="utf-8") as handle:
        handle.write("*** WARNING *** CP = 3.0\nThe initial penetration between contact pair 2 is 0.3.\n\n")
    time.sleep(1.0)
    view = monitor.view()
    check("警告去重计数=2", view["warning_event_count"] == 2, str(view["warning_event_count"]))

    # 3) 稳定触发：停止写入 settle_seconds 后应收到 on_settle
    time.sleep(1.5)
    keys = [k for k, _ in settled_seen]
    check("稳定触发覆盖两个文件", "case1.out" in keys and "solve/run2/file0.err" in keys, str(settled_seen))
    case1_summary = next((s for k, s in settled_seen if k == "case1.out"), {})
    check("稳定摘要含错误计数", case1_summary.get("error_since_settle", 0) >= 1, str(case1_summary))

    # 4) 深度限制：depth=0 时不发现子目录文件
    shallow = FolderMonitor(tmp, monitor_id="mon_shallow", interval=0.3, depth=0, settle_seconds=0.5)
    shallow.start()
    time.sleep(1.0)
    check("depth=0 只看根层", shallow.view()["files_tracked"] == 1, str(shallow.view()["files_tracked"]))
    shallow.stop()

    monitor.stop()
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if failures:
        print(f"自测失败 {len(failures)} 项: {failures}")
        raise SystemExit(1)
    print("folder_monitor 自测全部通过。")
