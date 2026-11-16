"""
solve_watcher.py
求解器输出流式证据监视器（错误反馈协议的核心组件）。

设计要点：
- 证据采集从"求解结束后的日志尾部快照"升级为"求解过程中的全场结构化证据流"。
- 监视器通过跨进程文件跟随独立运行，证据宿主与求解器返回值解耦：
  求解超时、进程被杀时，已采集的证据依然完整可用（另有 JSONL 落盘二级兜底）。
- 块级捕获 + 签名去重计数：非线性求解中每 substep 重复的 WARNING 不会淹没证据。
- 事件流（为什么死）与日志尾部快照（死在哪）在 finalize 结果中并存，二者互补。
- 监视器只读文件、只做模式分类，不管理求解器生命周期（职责归 runner/job 层）。
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from log_parser import ERROR_PATTERNS, WARNING_PATTERNS, _BLOCK_HEADER
from paths import project_path

_TAIL_READ_BYTES = 64 * 1024
_MAX_UNMATCHED_SAMPLES = 3
_SIGNATURE_LENGTH = 160


def _normalize_for_signature(text: str) -> str:
    """数字归一化 + 压缩空白，用于同一警告跨 substep 重复出现的去重签名。"""
    collapsed = re.sub(r"\s+", " ", text).strip().lower()
    normalized = re.sub(r"\d+([.,]\d+)?", "#", collapsed)
    return normalized[:_SIGNATURE_LENGTH]


class BlockStreamParser:
    """增量解析 MAPDL 诊断块：feed() 新文本，只吐出已终结的完整块。

    块 = 头行（*** WARNING *** 等）+ 正文，正文终结于空行分隔、
    下一个块头，或 finalize 时由 flush() 强制收尾。半块保留在缓冲中。
    """

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, text: str) -> list[dict]:
        if not text:
            return []
        # Windows 文本模式写入的是 \r\n（MAPDL file.out 正是如此），
        # 解析逻辑统一按 \n 处理；悬挂在缓冲末尾的孤立 \r 留待下一段拼合，
        # 避免 \r | \n 被跨段拆开时误判成两个换行。
        self._buffer += text
        if self._buffer.endswith("\r"):
            head = self._buffer[:-1]
            self._buffer = head.replace("\r\n", "\n").replace("\r", "\n") + "\r"
        else:
            self._buffer = self._buffer.replace("\r\n", "\n").replace("\r", "\n")
        return self._extract(flush=False)

    def flush(self) -> list[dict]:
        """强制产出缓冲中残留的未终结块（用于求解结束/监视终止时）。"""
        blocks = self._extract(flush=True)
        self._buffer = ""
        return blocks

    def pending_size(self) -> int:
        return len(self._buffer)

    def _extract(self, flush: bool) -> list[dict]:
        produced: list[dict] = []
        while True:
            match = _BLOCK_HEADER.search(self._buffer)
            if not match:
                # 头行之前的普通输出不进证据，直接丢弃
                if not flush:
                    # 保留末尾可能被截断的半行头，防止 "*** ERR" 被误丢
                    last_newline = self._buffer.rfind("\n")
                    self._buffer = self._buffer[last_newline + 1:] if last_newline != -1 else self._buffer
                else:
                    self._buffer = ""
                return produced

            body_start = match.end()
            next_match = _BLOCK_HEADER.search(self._buffer, body_start)
            segment_limit = next_match.start() if next_match else len(self._buffer)
            segment = self._buffer[body_start:segment_limit]

            blank = segment.find("\n\n")
            if blank != -1:
                body_end = body_start + blank
            elif next_match is not None:
                body_end = next_match.start()
            elif flush:
                body_end = len(self._buffer)
            else:
                # 块尚未终结：等待更多数据
                return produced

            body = self._buffer[body_start:body_end].strip()
            produced.append(
                {
                    "level": match.group(1).upper(),
                    "header": match.group(0).strip(),
                    "body": body,
                    "text": (match.group(0).strip() + "\n" + body).strip(),
                }
            )
            self._buffer = self._buffer[body_end:]


class SolverOutputWatcher:
    """跟随工作目录中的 *.out / *.err 文件，流式采集诊断证据。

    用法（通常由 job_manager 管理，也可独立使用）：
        watcher = SolverOutputWatcher(watch_dir, run_id="run_xxx")
        watcher.start()
        ...求解进行中可用 watcher.snapshot() 轮询实时进度...
        evidence = watcher.finalize(reason="completed")
    """

    def __init__(
        self,
        watch_dir: str | Path,
        run_id: str | None = None,
        poll_interval: float = 1.0,
        stall_timeout: float | None = None,
        journal_dir: str | Path | None = None,
        tail_lines: int = 30,
        error_patterns: dict | None = None,
        warning_patterns: dict | None = None,
    ) -> None:
        self.watch_dir = Path(watch_dir)
        self.run_id = run_id or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.poll_interval = max(0.1, float(poll_interval))
        self.stall_timeout = stall_timeout
        self.tail_lines = tail_lines
        self.error_patterns = error_patterns or ERROR_PATTERNS
        self.warning_patterns = warning_patterns or WARNING_PATTERNS

        self.journal_dir = Path(journal_dir) if journal_dir else project_path("runtime_data", "evidence")
        self.journal_path = self.journal_dir / f"{self.run_id}.jsonl"

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._offsets: dict[str, int] = {}
        self._parsers: dict[str, BlockStreamParser] = {}
        self._files_bytes: dict[str, int] = {}
        self._events: dict[str, dict] = {}  # signature -> event
        self._unmatched: dict[str, dict] = {
            "ERROR": {"count": 0, "samples": []},
            "WARNING": {"count": 0, "samples": []},
        }
        self._last_activity_monotonic = time.monotonic()
        self._started_at: str | None = None
        self._started_monotonic: float | None = None
        self._finalized = False
        self._watcher_error: str | None = None

    # ───────────────────────────────
    # 生命周期
    # ───────────────────────────────

    def start(self) -> None:
        if self._thread is not None:
            return
        self.watch_dir.mkdir(parents=True, exist_ok=True)
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self._started_at = datetime.now().isoformat(timespec="seconds")
        self._started_monotonic = time.monotonic()
        self._thread = threading.Thread(
            target=self._loop, name=f"solve-watcher-{self.run_id}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.poll_interval * 3))
            self._thread = None

    def __enter__(self) -> "SolverOutputWatcher":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.finalize(reason="context_exit")

    # ───────────────────────────────
    # 后台跟随循环
    # ───────────────────────────────

    def _loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                self._scan_once()
                self._stop_event.wait(self.poll_interval)
            self._scan_once()
        except Exception as exc:  # 监视器自身异常不能拖垮求解流程
            with self._lock:
                self._watcher_error = f"{type(exc).__name__}: {exc}"

    def _scan_once(self) -> None:
        candidates: list[Path] = []
        for pattern in ("*.out", "*.err"):
            candidates.extend(self.watch_dir.glob(pattern))
        # 已知文件即使本轮 glob 未命中也继续（文件可能被轮转），glob 结果按文件名去重
        known = set(self._offsets)
        seen: set[str] = set()
        for path in sorted(candidates, key=lambda p: p.name.lower()):
            key = path.name
            if key in seen:
                continue
            seen.add(key)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            offset = self._offsets.get(key)
            if offset is None:
                # 新文件从 0 开始：求解工作目录按 run 隔离，历史文件也应完整采集
                offset = 0
                self._offsets[key] = 0
                self._parsers[key] = BlockStreamParser()
            if size <= offset:
                continue
            try:
                with open(path, "rb") as handle:
                    handle.seek(offset)
                    raw = handle.read()
            except OSError:
                continue
            self._offsets[key] = offset + len(raw)
            text = raw.decode("utf-8", errors="replace")
            blocks = self._parsers[key].feed(text)
            with self._lock:
                self._files_bytes[key] = self._files_bytes.get(key, 0) + len(raw)
                self._last_activity_monotonic = time.monotonic()
            for block in blocks:
                self._classify_block(block, source_file=key)

    def _classify_block(self, block: dict, source_file: str) -> None:
        level = block.get("level")
        if level not in ("ERROR", "WARNING"):
            return

        text = block.get("text", "")
        patterns = self.error_patterns if level == "ERROR" else self.warning_patterns
        matched_code = None
        matched_config = None
        matched_text = None
        for code, config in patterns.items():
            found = re.search(config["pattern"], text, flags=re.IGNORECASE)
            if found:
                matched_code = code
                matched_config = config
                matched_text = found.group(0)
                break

        signature = f"{level}|{_normalize_for_signature(text)}"
        now = datetime.now().isoformat(timespec="seconds")

        with self._lock:
            if matched_code is None:
                bucket = self._unmatched[level]
                bucket["count"] += 1
                if len(bucket["samples"]) < _MAX_UNMATCHED_SAMPLES:
                    sample = {"source_file": source_file, "seen_at": now, "text": text[:1500]}
                    bucket["samples"].append(sample)
                    self._append_journal({"kind": "unmatched_sample", "level": level, **sample})
                return

            existing = self._events.get(signature)
            if existing is not None:
                existing["count"] += 1
                existing["last_seen"] = now
                return

            event = {
                "level": level,
                "code": matched_code,
                "title": matched_config.get("title", matched_code),
                "description": matched_config.get("description", ""),
                "suggestion": matched_config.get("suggestion", ""),
                "matched_text": matched_text,
                "count": 1,
                "first_seen": now,
                "last_seen": now,
                "source_file": source_file,
                "text": text[:2000],
            }
            self._events[signature] = event
            self._append_journal({"kind": "event", **event})

    def _append_journal(self, payload: dict) -> None:
        """必须在持有 self._lock 时调用。"""
        try:
            with open(self.journal_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass  # journal 是二级兜底，失败不影响内存证据

    # ───────────────────────────────
    # 查询接口
    # ───────────────────────────────

    def is_stalled(self) -> bool:
        if self.stall_timeout is None or self._started_monotonic is None:
            return False
        return (time.monotonic() - self._last_activity_monotonic) > self.stall_timeout

    def snapshot(self) -> dict:
        """运行中轮询用的轻量实时快照。"""
        with self._lock:
            events = sorted(self._events.values(), key=lambda e: e["first_seen"])
            recent = [
                {k: e.get(k) for k in ("level", "code", "title", "count", "first_seen")}
                for e in events[-5:]
            ]
            return {
                "run_id": self.run_id,
                "elapsed_s": round(time.monotonic() - self._started_monotonic, 1) if self._started_monotonic else 0.0,
                "files_watched": dict(self._files_bytes),
                "total_bytes_seen": sum(self._files_bytes.values()),
                "error_event_count": sum(e["count"] for e in events if e["level"] == "ERROR"),
                "warning_event_count": sum(e["count"] for e in events if e["level"] == "WARNING"),
                "stalled": self.is_stalled(),
                "watcher_error": self._watcher_error,
                "recent_events": recent,
            }

    # ───────────────────────────────
    # 终局证据
    # ───────────────────────────────

    def finalize(self, reason: str = "completed") -> dict:
        """停止跟随并产出完整证据包。成功/失败/超时/取消各路径共用。"""
        if self._finalized:
            with self._lock:
                return self._build_evidence(reason)
        self._finalized = True
        self.stop()
        # 冲刷残留半块
        for key, parser in list(self._parsers.items()):
            for block in parser.flush():
                self._classify_block(block, source_file=key)

        with self._lock:
            return self._build_evidence(reason)

    def _build_evidence(self, reason: str) -> dict:
        events = sorted(self._events.values(), key=lambda e: (e["level"], e["first_seen"]))
        error_events = [dict(e) for e in events if e["level"] == "ERROR"]
        warning_events = [dict(e) for e in events if e["level"] == "WARNING"]
        duration = (
            round(time.monotonic() - self._started_monotonic, 1)
            if self._started_monotonic
            else 0.0
        )

        evidence: dict[str, Any] = {
            "run_id": self.run_id,
            "watch_dir": str(self.watch_dir.resolve()),
            "reason": reason,
            "started_at": self._started_at,
            "finalized_at": datetime.now().isoformat(timespec="seconds"),
            "duration_s": duration,
            "files_watched": dict(self._files_bytes),
            "total_bytes_seen": sum(self._files_bytes.values()),
            "stalled": self.is_stalled(),
            "watcher_error": self._watcher_error,
            "error_events": error_events,
            "warning_events": warning_events,
            "matched_error_codes": sorted({e["code"] for e in error_events}),
            "matched_warning_codes": sorted({e["code"] for e in warning_events}),
            "suggestions": sorted(
                {e["suggestion"] for e in events if e.get("suggestion")}
            ),
            "unmatched": {
                level: {
                    "count": bucket["count"],
                    "samples": list(bucket["samples"]),
                }
                for level, bucket in self._unmatched.items()
            },
            "log_tail": self._read_tails(),
            "journal_path": str(self.journal_path) if self.journal_path.exists() else None,
        }
        return evidence

    def _read_tails(self) -> dict[str, str]:
        tails: dict[str, str] = {}
        for key in sorted(self._files_bytes):
            path = self.watch_dir / key
            try:
                with open(path, "rb") as handle:
                    handle.seek(0, 2)
                    size = handle.tell()
                    handle.seek(max(0, size - _TAIL_READ_BYTES))
                    raw = handle.read(_TAIL_READ_BYTES)
                lines = raw.decode("utf-8", errors="replace").splitlines()
                if len(lines) > self.tail_lines:
                    lines = lines[-self.tail_lines:]
                tails[key] = "\n".join(lines)
            except OSError as exc:
                tails[key] = f"<读取失败: {exc}>"
        return tails


def scan_directory_once(directory: str | Path, tail_lines: int = 30) -> dict:
    """对目录做一次静态块扫描（不做增量跟随）。

    用于 Mechanical 等求解输出目录事后才可知的场景：求解结束后
    对真实输出目录补扫一次，产出与 finalize 相同结构的事件部分。
    """
    directory = Path(directory)
    result: dict[str, Any] = {
        "scan_mode": "static_once",
        "directory": str(directory),
        "error_events": [],
        "warning_events": [],
        "unmatched": {"ERROR": {"count": 0, "samples": []}, "WARNING": {"count": 0, "samples": []}},
        "log_tail": {},
    }
    if not directory.exists():
        result["note"] = "目录不存在，无法扫描。"
        return result

    for pattern in ("*.out", "*.err"):
        for path in sorted(directory.glob(pattern), key=lambda p: p.name.lower()):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                result["log_tail"][path.name] = f"<读取失败: {exc}>"
                continue

            parser = BlockStreamParser()
            blocks = parser.feed(text) + parser.flush()
            for block in blocks:
                if block["level"] not in ("ERROR", "WARNING"):
                    continue
                level = block["level"]
                patterns = ERROR_PATTERNS if level == "ERROR" else WARNING_PATTERNS
                matched = None
                for code, config in patterns.items():
                    found = re.search(config["pattern"], block["text"], flags=re.IGNORECASE)
                    if found:
                        matched = (code, config, found.group(0))
                        break
                if matched is None:
                    bucket = result["unmatched"][level]
                    bucket["count"] += 1
                    if len(bucket["samples"]) < _MAX_UNMATCHED_SAMPLES:
                        bucket["samples"].append({"source_file": path.name, "text": block["text"][:1500]})
                    continue
                code, config, matched_text = matched
                events = result["error_events"] if level == "ERROR" else result["warning_events"]
                for event in events:
                    if event["code"] == code:
                        event["count"] += 1
                        break
                else:
                    events.append(
                        {
                            "level": level,
                            "code": code,
                            "title": config.get("title", code),
                            "description": config.get("description", ""),
                            "suggestion": config.get("suggestion", ""),
                            "matched_text": matched_text,
                            "count": 1,
                            "source_file": path.name,
                            "text": block["text"][:2000],
                        }
                    )

            lines = text.splitlines()
            result["log_tail"][path.name] = "\n".join(lines[-tail_lines:])
    return result


# ───────────────────────────────
# 自测：合成渐进写入，验证块解析 / 去重 / journal / stall / finalize
# ───────────────────────────────

if __name__ == "__main__":
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="solve_watcher_test_"))
    failures: list[str] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        status = "PASS" if condition else "FAIL"
        print(f"[{status}] {name}" + (f" — {detail}" if detail and not condition else ""))
        if not condition:
            failures.append(name)

    # 1) BlockStreamParser：半块不产出、空行终结、flush 收尾
    parser = BlockStreamParser()
    check("半块不产出", parser.feed("*** WARNING *** CP=1\nbody only half") == [])
    blocks = parser.feed("\n\nnext line\n")
    check("空行终结产出", len(blocks) == 1 and blocks[0]["level"] == "WARNING")
    blocks = parser.feed("*** ERROR *** CP=2\nsingular matrix\n")
    blocks += parser.flush()
    check("flush 收尾产出", len(blocks) == 1 and blocks[0]["level"] == "ERROR")

    # 2) 增量截断的头行不会被误丢
    parser2 = BlockStreamParser()
    check("截断头行缓冲", parser2.feed("output...\n*** WAR") == [])
    blocks = parser2.feed("NING *** CP=3\nchattering detected\n\n")
    check("跨段头行拼回", len(blocks) == 1 and "chattering" in blocks[0]["body"])

    # 3) 完整监视器流程
    watcher = SolverOutputWatcher(tmp, run_id="run_selftest", poll_interval=0.2, stall_timeout=1.0)
    watcher.start()
    log_file = tmp / "file0.out"
    log_file.write_text(
        "*** WARNING *** CP = 1.0 TIME = 10:00:01\n"
        "The initial penetration between contact pair 3 is 0.15.\n"
        "\n",
        encoding="utf-8",
    )
    time.sleep(0.6)
    with open(log_file, "a", encoding="utf-8") as handle:  # 同警告不同数字 → 应去重计数
        for i in range(3):
            handle.write(
                f"*** WARNING *** CP = {i + 2}.0 TIME = 10:00:0{i + 2}\n"
                f"The initial penetration between contact pair {i + 4} is {i + 1}.00.\n"
                "\n"
            )
            handle.flush()
    (tmp / "file0.err").write_text(
        "*** ERROR *** CP = 9.0\nA singular matrix was detected at node 55.\n\n",
        encoding="utf-8",
    )
    time.sleep(0.8)

    snap = watcher.snapshot()
    check("快照统计错误事件", snap["error_event_count"] == 1, str(snap))
    check("快照统计警告计数(去重)", snap["warning_event_count"] == 4, str(snap))

    time.sleep(1.3)  # 超过 stall_timeout
    check("静默检测生效", watcher.is_stalled())

    evidence = watcher.finalize(reason="selftest")
    codes = [e["code"] for e in evidence["error_events"]]
    warn = next((e for e in evidence["warning_events"] if e["code"] == "contact_initial_penetration"), None)
    check("错误事件匹配 singular_matrix", "singular_matrix" in codes, str(codes))
    check("警告去重计数=4", warn is not None and warn["count"] == 4, str(warn))
    check("警告带修正建议", bool(warn and warn["suggestion"]))
    check("log_tail 存在", "file0.out" in evidence["log_tail"] and "singular" in evidence["log_tail"].get("file0.err", ""))
    check("journal 已落盘", evidence["journal_path"] is not None and Path(evidence["journal_path"]).exists())
    check("stalled 标志进入证据", evidence["stalled"] is True)

    # 4) 静态补扫
    static = scan_directory_once(tmp)
    check("静态扫描命中错误", any(e["code"] == "singular_matrix" for e in static["error_events"]))

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if failures:
        print(f"自测失败 {len(failures)} 项: {failures}")
        raise SystemExit(1)
    print("solve_watcher 自测全部通过。")
