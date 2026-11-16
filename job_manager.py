"""
job_manager.py
异步求解任务管理：提交即返回 run_id，轮询获取状态、结果与流式证据。

执行模型：
- 管理器线程池中的 worker 充当"监督者"，真实求解调用放在嵌套 daemon 线程；
- 监督者 join(timeout) 等待求解线程，超时经 session_holder 拿到求解器会话
  调 .exit() 强杀，任务标记 timeout——证据由独立的 solve_watcher 持有，照常返回；
- 每个任务配一个 SolverOutputWatcher 跟随工作目录的 *.out/*.err，
  采集全场 WARNING/ERROR 事件（去重计数）+ 日志尾部快照，JSONL 落盘二级兜底；
- 成功与失败/超时都走 analysis_pipeline：失败场景用证据事件 + 日志尾部驱动诊断，
  完成"失败 → 自诊断 → 修正重试"的闭环输入。
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from analysis_pipeline import analyze_execution
from observability import record_solve_run
from paths import project_path
from solve_watcher import SolverOutputWatcher, scan_directory_once
from log_parser import load_log_text

_JOBS_DIR = project_path("runtime_data", "jobs")
_DEFAULT_MAX_WORKERS = 2
_KILL_GRACE_SECONDS = 15.0

_TERMINAL_STATUSES = {"completed", "failed", "timeout", "cancelled"}

# kind → 默认工作目录（params.working_directory 优先）
KIND_REGISTRY: dict[str, str] = {
    "mapdl_input": "ansys_workspace",
    "mapdl_demo": "ansys_workspace",
    "mapdl_template": "ansys_workspace",
    "mechanical_script": "mechanical_workspace",
    "mechanical_template": "mechanical_workspace",
    "mechanical_contact_batch": "mechanical_workspace",
}

_INTERNAL_FIELDS = ("_cancel_requested", "_session_holder", "_solver_thread")


class RunJobManager:
    """异步求解任务管理器。由 main.py 注入 runner 与 llm_analyzer 单例。"""

    def __init__(self, ansys_runner, mechanical_runner, llm_analyzer) -> None:
        self.ansys_runner = ansys_runner
        self.mechanical_runner = mechanical_runner
        self.llm_analyzer = llm_analyzer

        try:
            max_workers = max(1, int(os.getenv("CAE_JOB_MAX_WORKERS", _DEFAULT_MAX_WORKERS)))
        except ValueError:
            max_workers = _DEFAULT_MAX_WORKERS

        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="job-supervisor")
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()
        _JOBS_DIR.mkdir(parents=True, exist_ok=True)

    # ───────────────────────────────
    # 公开接口
    # ───────────────────────────────

    def submit(self, kind: str, params: dict | None = None, timeout_seconds: float | None = None) -> str:
        """提交任务，立即返回 run_id。kind 必须在 KIND_REGISTRY 中。"""
        if kind not in KIND_REGISTRY:
            raise ValueError(f"未知任务类型：{kind}。可用：{sorted(KIND_REGISTRY)}")

        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        job = {
            "run_id": run_id,
            "kind": kind,
            "params": dict(params or {}),
            "timeout_seconds": timeout_seconds,
            "status": "pending",
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
            "started_at": None,
            "finished_at": None,
            "duration_s": None,
            "message": "任务已提交，等待执行。",
            "result": None,
            "evidence": None,
            # 以下为内部字段，public_view 时剔除
            "_cancel_requested": False,
            "_session_holder": None,
            "_solver_thread": None,
        }
        with self._lock:
            self._jobs[run_id] = job
        self._persist(job)
        record_solve_run(run_id, kind, "pending", "任务已提交。")
        self._executor.submit(self._supervise, job)
        return run_id

    def get_job(self, run_id: str, live_evidence: bool = False) -> dict | None:
        with self._lock:
            job = self._jobs.get(run_id)
            if job is None:
                return None
            view = self._public_view(job)
        if live_evidence and job["status"] == "running" and job.get("_watcher") is not None:
            try:
                view["live_evidence"] = job["_watcher"].snapshot()
            except Exception:
                pass
        return view

    def list_jobs(self, limit: int = 50) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j["submitted_at"], reverse=True)
            return [self._slim_view(job) for job in jobs[:limit]]

    def cancel(self, run_id: str) -> dict | None:
        """请求取消任务。运行中立即强杀求解会话；pending 由监督者开始时短路。"""
        with self._lock:
            job = self._jobs.get(run_id)
            if job is None:
                return None
            if job["status"] in _TERMINAL_STATUSES:
                return self._public_view(job)
            job["_cancel_requested"] = True
            holder = job.get("_session_holder")
            solver_thread = job.get("_solver_thread")
            was_running = job["status"] == "running"

        if was_running:
            self._kill_session(holder)
            if solver_thread is not None:
                solver_thread.join(timeout=_KILL_GRACE_SECONDS)
            # 监督者可能恰好同时收尾；_try_finish 保证终态只落一次
            self._try_finish(job, status="cancelled", message="任务已被手动取消。")
        else:
            self._try_finish(job, status="cancelled", message="任务在开始执行前被取消。")
        return self._public_view(job)

    # ───────────────────────────────
    # 监督执行
    # ───────────────────────────────

    def _supervise(self, job: dict) -> None:
        if job.get("_cancel_requested"):
            self._try_finish(job, status="cancelled", message="任务在开始执行前被取消。")
            return

        kind = job["kind"]
        params = job["params"]

        watch_dir = Path(params.get("working_directory") or project_path(KIND_REGISTRY.get(kind, "ansys_workspace")))
        try:
            watch_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        watcher = SolverOutputWatcher(watch_dir, run_id=job["run_id"])
        job["_watcher"] = watcher
        watcher.start()

        holder: dict = {}
        job["_session_holder"] = holder

        result_holder: dict = {}

        def _solver_call() -> None:
            try:
                result_holder["result"] = self._dispatch(kind, params, holder)
            except Exception as exc:
                result_holder["error"] = f"{type(exc).__name__}: {exc}"

        self._update(job, status="running", message="求解器启动中。", started_at=datetime.now().isoformat(timespec="seconds"))
        record_solve_run(job["run_id"], kind, "running", "求解器启动中。")

        solver_thread = threading.Thread(target=_solver_call, name=f"solver-{job['run_id']}", daemon=True)
        job["_solver_thread"] = solver_thread
        solver_thread.start()

        timeout = job.get("timeout_seconds")
        if timeout:
            solver_thread.join(timeout=float(timeout))
        else:
            solver_thread.join()

        if solver_thread.is_alive():
            # 超时：强杀求解会话；证据由 watcher 独立持有，照常产出
            self._kill_session(holder)
            solver_thread.join(timeout=_KILL_GRACE_SECONDS)
            result = {
                "success": False,
                "mode": "execution_timeout",
                "message": f"求解超过 {timeout}s 未完成，已强制终止会话。",
                "timeout_seconds": timeout,
                "kind": kind,
                "working_directory": str(watch_dir.resolve()),
            }
            if solver_thread.is_alive():
                result["note"] = "求解线程未在宽限期内退出，已放弃等待（daemon 线程不会阻塞服务）。"
            self._finish_job(job, result=result, watcher=watcher, finalize_reason="timeout", status="timeout")
            return

        if "error" in result_holder:
            result = {
                "success": False,
                "mode": "solver_crashed",
                "message": "求解调用抛出未处理异常。",
                "detail": result_holder["error"],
                "kind": kind,
                "working_directory": str(watch_dir.resolve()),
            }
            self._finish_job(job, result=result, watcher=watcher, finalize_reason="failed", status="failed")
            return

        result = result_holder.get("result") or {
            "success": False,
            "mode": "empty_result",
            "message": "求解调用返回空结果。",
        }
        status = "completed" if result.get("success") else "failed"
        self._finish_job(
            job,
            result=result,
            watcher=watcher,
            finalize_reason="completed" if status == "completed" else "failed",
            status=status,
        )

    def _dispatch(self, kind: str, params: dict, holder: dict) -> dict:
        """按 kind 调用对应 runner 方法（阻塞，运行在求解线程）。"""
        if kind == "mapdl_input":
            return self.ansys_runner.run_input_file(
                input_file_path=params["input_file_path"],
                working_directory=params.get("working_directory"),
                session_holder=holder,
            )
        if kind == "mapdl_demo":
            return self.ansys_runner.run_demo(
                launch_mapdl=True,
                working_directory=params.get("working_directory"),
                session_holder=holder,
            )
        if kind == "mapdl_template":
            return self.ansys_runner.run_template_simulation(
                template_type=params["template_type"],
                params=params.get("template_params"),
                working_directory=params.get("working_directory"),
                launch_mapdl=True,
                session_holder=holder,
            )
        if kind == "mechanical_script":
            return self.mechanical_runner.run_python_script(
                script=params["script"],
                context=params.get("context", "job"),
                launch_mechanical=True,
                working_directory=params.get("working_directory"),
                session_holder=holder,
            )
        if kind == "mechanical_template":
            return self.mechanical_runner.run_python_script(
                script=self._build_mechanical_template_script(params),
                context=f"job_template_{params.get('template_type', 'unknown')}",
                launch_mechanical=True,
                working_directory=params.get("working_directory"),
                session_holder=holder,
            )
        if kind == "mechanical_contact_batch":
            return self.mechanical_runner.execute_batch_contacts_by_named_selection(
                source_named_selection_prefix=params["source_named_selection_prefix"],
                target_named_selection_prefix=params["target_named_selection_prefix"],
                contact_type=params.get("contact_type", "Frictionless"),
                contact_name_prefix=params.get("contact_name_prefix", "AUTO_CONTACT_"),
                launch_mechanical=True,
                working_directory=params.get("working_directory"),
                session_holder=holder,
            )
        raise ValueError(f"未知任务类型：{kind}")

    def _build_mechanical_template_script(self, params: dict) -> str:
        template_type = params.get("template_type")
        template_params = params.get("template_params")
        if template_type == "cantilever_beam":
            return self.mechanical_runner._build_cantilever_beam_script(template_params)
        if template_type == "modal_analysis":
            return self.mechanical_runner._build_modal_analysis_script(template_params)
        raise ValueError(f"未知 Mechanical 模板类型：{template_type}。可用：cantilever_beam / modal_analysis")

    # ───────────────────────────────
    # 收尾：证据 + 分析 + 持久化
    # ───────────────────────────────

    def _finish_job(self, job: dict, result: dict, watcher: SolverOutputWatcher, finalize_reason: str, status: str) -> None:
        evidence = watcher.finalize(reason=finalize_reason)
        result["evidence"] = evidence

        # Mechanical 尽力而为：若探测到真实输出目录且与监视目录不同、且监视目录未见输出，
        # 事后对真实目录做一次静态补扫
        detected_dir = (job.get("_session_holder") or {}).get("detected_working_dir")
        if (
            detected_dir
            and Path(detected_dir).resolve() != Path(evidence.get("watch_dir", ".")).resolve()
            and evidence.get("total_bytes_seen", 0) == 0
        ):
            late_scan = scan_directory_once(detected_dir)
            late_scan["scan_mode"] = "late_static_pass"
            late_scan["note"] = "调用方 working_directory 未见求解输出，已按探测到的 Mechanical 工作目录补扫。"
            evidence["late_static_pass"] = late_scan

        # 成功与失败都出分析：失败场景用证据 + 日志尾部驱动 LLM 诊断（自修正闭环的输入）
        analysis = self._build_analysis(job, result, evidence)
        if analysis is not None:
            result["analysis"] = analysis

        message = result.get("message", "")
        self._try_finish(
            job,
            status=status,
            message=message,
            result=result,
            evidence=evidence,
            extra_events=(
                len(evidence.get("error_events") or []),
                sum(e.get("count", 1) for e in evidence.get("warning_events") or []),
            ),
        )

    def _build_analysis(self, job: dict, result: dict, evidence: dict) -> dict | None:
        try:
            primary_log_path = result.get("primary_log_path")
            log_text = ""
            if primary_log_path and Path(primary_log_path).exists():
                log_text = load_log_text(primary_log_path)
            elif evidence.get("log_tail"):
                log_text = "\n".join(evidence["log_tail"].values())

            return analyze_execution(
                source_name=primary_log_path or job["run_id"],
                log_text=log_text,
                evidence=evidence,
                engineering_results=result.get("engineering_results"),
                llm_analyzer=self.llm_analyzer,
            )
        except Exception as exc:
            return {"success": False, "message": f"诊断分析链路失败：{exc}"}

    # ───────────────────────────────
    # 会话强杀与状态管理
    # ───────────────────────────────

    @staticmethod
    def _kill_session(holder: dict | None) -> None:
        if not holder:
            return
        for key in ("mapdl", "mechanical"):
            session = holder.get(key)
            if session is None:
                continue
            try:
                session.exit()
            except Exception:
                pass  # 会话可能已自行退出

    def _update(self, job: dict, **fields) -> None:
        with self._lock:
            job.update(fields)
        self._persist(job)

    def _try_finish(self, job: dict, status: str, message: str, result: dict | None = None,
                    evidence: dict | None = None, extra_events: tuple | None = None) -> bool:
        """落终态；若任务已处于终态（如取消与完成竞争）则拒绝重复写入。"""
        finished_at = datetime.now().isoformat(timespec="seconds")
        duration = None
        started = job.get("started_at")
        if started:
            try:
                duration = round((datetime.now() - datetime.fromisoformat(started)).total_seconds(), 1)
            except ValueError:
                duration = None

        with self._lock:
            if job["status"] in _TERMINAL_STATUSES:
                return False
            job.update(
                {
                    "status": status,
                    "message": message,
                    "finished_at": finished_at,
                    "duration_s": duration,
                }
            )
            if result is not None:
                job["result"] = result
            if evidence is not None:
                job["evidence"] = evidence
            view = self._public_view(job)
        self._persist(job)

        extra: dict = {}
        if extra_events is not None:
            error_count, warning_count = extra_events
            extra = {"error_events": error_count, "warning_events": warning_count}
            report_path = ((result or {}).get("analysis") or {}).get("report_path")
            if report_path:
                extra["report_path"] = report_path
        record_solve_run(job["run_id"], job["kind"], status, message, extra=extra)
        return True

    def _persist(self, job: dict) -> None:
        try:
            with self._lock:
                view = self._public_view(job)
            path = _JOBS_DIR / f"{job['run_id']}.json"
            path.write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass  # 状态持久化失败不阻塞任务执行

    def _public_view(self, job: dict) -> dict:
        return {key: value for key, value in job.items() if key not in _INTERNAL_FIELDS and not key.startswith("_")}

    def _slim_view(self, job: dict) -> dict:
        """列表用轻量视图：不携带完整 result/evidence（详情走 get_job）。"""
        view = {
            "run_id": job["run_id"],
            "kind": job["kind"],
            "status": job["status"],
            "submitted_at": job.get("submitted_at"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "duration_s": job.get("duration_s"),
            "timeout_seconds": job.get("timeout_seconds"),
            "message": job.get("message"),
        }
        evidence = job.get("evidence")
        if evidence:
            view["evidence_summary"] = {
                "error_events": len(evidence.get("error_events") or []),
                "warning_event_count": sum(e.get("count", 1) for e in evidence.get("warning_events") or []),
                "matched_error_codes": evidence.get("matched_error_codes") or [],
                "stalled": bool(evidence.get("stalled")),
                "total_bytes_seen": evidence.get("total_bytes_seen", 0),
            }
        result = job.get("result")
        if result:
            view["result_mode"] = result.get("mode")
            report_path = (result.get("analysis") or {}).get("report_path")
            if report_path:
                view["report_path"] = report_path
        return view
