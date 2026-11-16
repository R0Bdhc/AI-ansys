import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

if sys.version_info < (3, 11):
    raise RuntimeError(
        f"cae-agent 需要 Python 3.11+，当前为 {sys.version.split()[0]}。"
        "请升级 Python 后重试（见 README「环境要求」）。"
    )

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ansys_runner import AnsysRunner
from analysis_pipeline import analyze_execution, get_llm_analyzer
from folder_monitor import FolderMonitorManager
from job_manager import KIND_REGISTRY, RunJobManager
from log_parser import detect_errors, load_log_text
from mechanical_post_processor import MechanicalPostProcessor
from mechanical_runner import MechanicalRunner
from observability import get_events
from paths import PROJECT_ROOT, project_path


load_dotenv(PROJECT_ROOT / ".env")

app = FastAPI(
    title="cae-agent",
    description="基于 ANSYS 与 LLM 的最小可运行 CAE 辅助系统。",
    version="0.3.0",
)


class AnalyzeLogRequest(BaseModel):
    log_path: Optional[str] = Field(default=None, description="日志文件绝对路径。")
    log_text: Optional[str] = Field(default=None, description="直接传入的日志文本。")


class AnsysDemoRequest(BaseModel):
    launch_mapdl: bool = Field(
        default=False,
        description="是否真实启动 MAPDL。False 时仅返回演示命令。",
    )
    working_directory: Optional[str] = Field(
        default=None,
        description="MAPDL 工作目录。为空时默认使用项目内的 ansys_workspace。",
    )


class MapdlInputRequest(BaseModel):
    input_file_path: str = Field(description="MAPDL 输入文件绝对路径，例如 .inp、.dat、.mac。")
    working_directory: Optional[str] = Field(
        default=None,
        description="MAPDL 工作目录。为空时默认使用项目内的 ansys_workspace。",
    )
    analyze_after_run: bool = Field(
        default=True,
        description="执行完成后是否自动分析主日志文件。",
    )


class MechanicalBatchContactRequest(BaseModel):
    source_named_selection_prefix: str = Field(description="源面命名选择前缀，例如 NS_SRC_")
    target_named_selection_prefix: str = Field(description="目标面命名选择前缀，例如 NS_TGT_")
    contact_type: str = Field(default="Frictionless", description="接触类型，例如 Frictionless/Bonded")
    contact_name_prefix: str = Field(default="AUTO_CONTACT_", description="自动创建接触名称前缀")
    launch_mechanical: bool = Field(
        default=False,
        description="是否真实启动 242+ Mechanical 执行。False 时仅返回方案和脚本预览。",
    )
    working_directory: Optional[str] = Field(
        default=None,
        description="Mechanical 工作目录。为空时默认使用项目内的 mechanical_workspace。",
    )


class TemplateSimulationRequest(BaseModel):
    template_type: str = Field(description="模板类型：cantilever / plate_with_hole / viscoelastic_disk")
    params: Optional[dict] = Field(default=None, description="JSON 参数，覆盖模板默认值。")
    working_directory: Optional[str] = Field(default=None, description="MAPDL 工作目录。")
    launch_mapdl: bool = Field(default=False, description="是否真实启动 MAPDL。False 时仅返回 APDL 命令预览。")
    run_postprocess: bool = Field(default=False, description="求解完成后是否自动执行后处理可视化。")
    stress_curve_path: Optional[list[list[float]]] = Field(
        default=None,
        description="可选：应力曲线提取路径点列表，例如 [[0,0,0], [1,0,0]]。",
    )


class PostprocessRequest(BaseModel):
    working_directory: str = Field(description="包含结果文件的工作目录绝对路径。")
    stress_curve_path: Optional[list[list[float]]] = Field(
        default=None,
        description="可选：应力曲线提取路径点列表。",
    )
    basename: str = Field(default="post", description="输出文件前缀。")


class MechanicalScriptRequest(BaseModel):
    script: str = Field(description="在 Mechanical 中执行的 Python 脚本字符串。")
    context: str = Field(default="custom", description="脚本上下文标识。")
    launch_mechanical: bool = Field(
        default=False,
        description="是否真实启动 Mechanical。False 时仅返回预览。",
    )
    working_directory: Optional[str] = Field(
        default=None,
        description="Mechanical 工作目录。",
    )


class MechanicalExtractRequest(BaseModel):
    working_directory: str = Field(description="Mechanical 工作目录绝对路径。")
    result_types: Optional[list[str]] = Field(
        default=None,
        description="结果类型列表，例如 [\"stress\", \"displacement\", \"frequency\"。",
    )


class MechanicalImageRequest(BaseModel):
    working_directory: str = Field(description="Mechanical 工作目录绝对路径。")
    object_name: str = Field(default="Equivalent Stress", description="结果对象名称，例如 Equivalent Stress / Total Deformation。")
    image_type: str = Field(default="stress", description="图片类型：stress / displacement / deformation。")
    basename: str = Field(default="mechanical", description="输出文件前缀。")


class MechanicalTemplateRequest(BaseModel):
    template_type: str = Field(description="模板类型：cantilever_beam / modal_analysis。")
    params: Optional[dict] = Field(default=None, description="JSON 参数，覆盖模板默认值。")
    working_directory: Optional[str] = Field(default=None, description="Mechanical 工作目录。")
    launch_mechanical: bool = Field(default=False, description="是否真实启动 Mechanical。False 时仅返回脚本预览。")
    run_postprocess: bool = Field(default=False, description="求解完成后是否自动执行后处理可视化。")


class RunJobRequest(BaseModel):
    kind: str = Field(
        description="任务类型：mapdl_input / mapdl_demo / mapdl_template / mechanical_script / mechanical_template / mechanical_contact_batch。"
    )
    params: dict = Field(
        default_factory=dict,
        description="任务参数，字段与对应同步端点请求体一致（如 mapdl_input 用 input_file_path；mapdl_template 用 template_type + template_params）。",
    )
    timeout_seconds: Optional[float] = Field(
        default=None,
        gt=0,
        le=86400,
        description="可选超时；超时将强杀求解会话，并返回已采集的流式证据与诊断。",
    )


class CreateMonitorRequest(BaseModel):
    path: str = Field(description="要监听的项目目录绝对路径。")
    interval: float = Field(default=5.0, gt=0, le=3600, description="轮询间隔（秒），默认 5s。")
    depth: int = Field(default=3, ge=0, le=10, description="递归扫描深度，0 为仅当前目录层。")
    auto_analyze: bool = Field(
        default=False,
        description="自动分析开关：文件稳定且发现错误时自动调用 LLM 诊断（默认关，防成本失控）。",
    )


class ToggleAutoAnalyzeRequest(BaseModel):
    enabled: bool = Field(description="是否开启自动分析。")


class MonitorAnalyzeRequest(BaseModel):
    monitor_id: str = Field(description="监听器 ID。")
    file: str = Field(description="监听内文件的相对路径。")


class LlmConfigRequest(BaseModel):
    api_key: Optional[str] = Field(default=None, description="API Key；留空表示保持现有配置不变。")
    provider: Optional[str] = Field(default=None, description="提供商：deepseek / kimi / claude / openai / local / custom。")
    model: Optional[str] = Field(default=None, description="模型名；切换 provider 时留空则使用该 provider 预设。")
    base_url: Optional[str] = Field(default=None, description="OpenAI 兼容接口地址；切换 provider 时留空则使用预设。")


class MonitorPauseRequest(BaseModel):
    paused: bool = Field(description="true=暂停监听，false=恢复监听。")


llm_analyzer = get_llm_analyzer()
ansys_runner = AnsysRunner()
mechanical_runner = MechanicalRunner()
mechanical_post_processor = MechanicalPostProcessor(output_dir=project_path("reports"))
job_manager = RunJobManager(
    ansys_runner=ansys_runner,
    mechanical_runner=mechanical_runner,
    llm_analyzer=llm_analyzer,
)
monitor_manager = FolderMonitorManager()
monitor_manager.bind_llm_analyzer(llm_analyzer)

# 仪表盘 overview 缓存：避免每次轮询都触发文件系统扫描与许可证服务查询
_OVERVIEW_CACHE_TTL = 10.0
_overview_cache: dict = {"data": None, "at": 0.0}


@app.get("/")
def root() -> dict:
    return {
        "project": "cae-agent",
        "message": "服务已启动，可访问 /docs 查看接口文档。",
        "stage": "可执行 MVP：MAPDL 执行 + 日志分析 + 报告生成",
    }


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm": llm_analyzer.get_status(),
        "notes": {
            "configured": "是否已配置可用的 LLM API Key。",
            "reachable": "是否能从当前环境成功连通外部 LLM 服务。",
            "checked_at": "最近一次连通性检查的 Unix 时间戳；未检查时为 null。",
        },
    }


@app.get("/mapdl-status")
def mapdl_status() -> dict:
    return ansys_runner.get_environment_status()


@app.get("/ansys-demo")
def get_ansys_demo() -> dict:
    return ansys_runner.get_demo_definition()


@app.get("/mechanical-status")
def mechanical_status() -> dict:
    return mechanical_runner.get_environment_status()


@app.get("/mechanical-capabilities")
def mechanical_capabilities() -> dict:
    return mechanical_runner.get_capability_definition()


@app.post("/mechanical-contact-batch-plan")
def mechanical_contact_batch_plan(request: MechanicalBatchContactRequest) -> dict:
    return mechanical_runner.preview_batch_contact_plan(
        source_named_selection_prefix=request.source_named_selection_prefix,
        target_named_selection_prefix=request.target_named_selection_prefix,
        contact_type=request.contact_type,
        contact_name_prefix=request.contact_name_prefix,
    )


@app.post("/mechanical-contact-batch-execute")
def mechanical_contact_batch_execute(request: MechanicalBatchContactRequest) -> dict:
    return mechanical_runner.execute_batch_contacts_by_named_selection(
        source_named_selection_prefix=request.source_named_selection_prefix,
        target_named_selection_prefix=request.target_named_selection_prefix,
        contact_type=request.contact_type,
        contact_name_prefix=request.contact_name_prefix,
        launch_mechanical=request.launch_mechanical,
        working_directory=request.working_directory,
    )


@app.post("/mechanical-run-script")
def mechanical_run_script(request: MechanicalScriptRequest) -> dict:
    result = mechanical_runner.run_python_script(
        script=request.script,
        context=request.context,
        launch_mechanical=request.launch_mechanical,
        working_directory=request.working_directory,
    )

    if not result.get("success") or not request.launch_mechanical:
        return result

    # 自动串联 LLM 分析 + 报告生成链路
    _attach_mechanical_analysis(result)
    return result


@app.post("/mechanical-extract-results")
def mechanical_extract_results(request: MechanicalExtractRequest) -> dict:
    # 构造结果提取脚本并执行
    script = mechanical_post_processor.build_result_extraction_script(request.result_types)
    exec_result = mechanical_runner.run_python_script(
        script=script,
        context="result_extraction",
        launch_mechanical=True,
        working_directory=request.working_directory,
    )

    if not exec_result.get("success"):
        return exec_result

    extracted = mechanical_runner.extract_mechanical_results(
        script_result=exec_result,
        result_types=request.result_types,
    )
    exec_result["extracted_results"] = extracted
    return exec_result


@app.post("/mechanical-export-image")
def mechanical_export_image(request: MechanicalImageRequest) -> dict:
    image_path = str(project_path("reports") / f"{request.basename}_{request.image_type}.png")

    if request.image_type == "stress":
        script = mechanical_post_processor.build_stress_export_script(image_path)
    elif request.image_type in ("displacement", "deformation"):
        script = mechanical_post_processor.build_displacement_export_script(image_path)
    else:
        return {
            "success": False,
            "error": f"不支持的 image_type：{request.image_type}。支持：stress / displacement / deformation。",
        }

    return mechanical_runner.export_mechanical_image(
        mechanical_exec=None,
        script=script,
        image_path=image_path,
        context=request.image_type,
    )


@app.post("/mechanical-run-template")
def mechanical_run_template(request: MechanicalTemplateRequest) -> dict:
    if request.template_type == "cantilever_beam":
        script = mechanical_runner._build_cantilever_beam_script(request.params)
    elif request.template_type == "modal_analysis":
        script = mechanical_runner._build_modal_analysis_script(request.params)
    else:
        return {
            "success": False,
            "error": f"未知模板类型：{request.template_type}。可用：cantilever_beam / modal_analysis。",
        }

    result = mechanical_runner.run_python_script(
        script=script,
        context=f"template_{request.template_type}",
        launch_mechanical=request.launch_mechanical,
        working_directory=request.working_directory,
    )

    if not result.get("success") or not request.launch_mechanical:
        return result

    # 自动串联 LLM 分析 + 报告生成
    _attach_mechanical_analysis(result)

    # 如果请求了后处理，执行可视化
    if request.run_postprocess:
        post_result = mechanical_post_processor.run_full_postprocess(
            runner=mechanical_runner,
            working_directory=request.working_directory,
            basename=request.template_type,
        )
        result["postprocess"] = post_result

        # 将图片路径传入报告
        image_paths = [
            plot.get("image_path")
            for plot in post_result.get("plots", [])
            if plot.get("success") and plot.get("image_path")
        ]
        if image_paths and "analysis" in result:
            # 重新生成报告，包含图片
            _regenerate_report_with_images(result, image_paths)

    return result


def _attach_mechanical_analysis(result: dict) -> None:
    """为 Mechanical 执行结果附加 LLM 分析 + Markdown 报告。"""
    # Mechanical 目前没有标准日志文件，使用 execution_result 作为分析源
    execution_result = result.get("execution_result", {})
    raw_text = json.dumps(execution_result, ensure_ascii=False, indent=2)
    result["analysis"] = analyze_execution(
        source_name=result.get("context", "mechanical"),
        log_text=raw_text,
        engineering_results=mechanical_runner.extract_mechanical_results(script_result=result),
        llm_analyzer=llm_analyzer,
    )


def _regenerate_report_with_images(result: dict, image_paths: list[str]) -> None:
    """重新生成报告，嵌入后处理图片。"""
    analysis = result.get("analysis", {})
    if not analysis:
        return

    markdown_content = build_markdown_report(
        source_name=result.get("context", "mechanical"),
        detected_errors=analysis.get("detected_errors", []),
        llm_result=analysis.get("llm_result", {}),
        engineering_results=mechanical_runner.extract_mechanical_results(script_result=result),
        image_paths=image_paths,
    )
    report_path = save_markdown_report(markdown_content)
    result["analysis"]["report_path"] = str(report_path)
    result["analysis"]["markdown_preview"] = markdown_content


@app.get("/templates")
def list_templates() -> dict:
    return ansys_runner.list_templates()


@app.get("/templates/{template_type}")
def get_template_info(template_type: str) -> dict:
    return ansys_runner.get_template_info(template_type)


@app.post("/run-template-simulation")
def run_template_simulation(request: TemplateSimulationRequest) -> dict:
    result = ansys_runner.run_template_simulation(
        template_type=request.template_type,
        params=request.params,
        working_directory=request.working_directory,
        launch_mapdl=request.launch_mapdl,
        run_postprocess=request.run_postprocess,
        stress_curve_path=request.stress_curve_path,
    )

    if not result.get("success"):
        return result

    if not request.launch_mapdl:
        return result

    # 自动串联日志分析链路
    primary_log_path = result.get("primary_log_path")
    if primary_log_path:
        result["analysis"] = analyze_execution(
            source_name=primary_log_path,
            log_text=load_log_text(primary_log_path),
            engineering_results=result.get("engineering_results"),
            llm_analyzer=llm_analyzer,
        )

    # 如果请求了后处理但模板执行未内嵌（当前架构下后处理需单独调用），给出提示
    if request.run_postprocess and "postprocess_note" not in result:
        result["postprocess_note"] = (
            "后处理可视化已请求。由于 MAPDL 会话在求解后已关闭，"
            "请调用 POST /postprocess-visualization 并传入 working_directory 以加载结果文件进行可视化。"
        )

    return result


@app.post("/postprocess-visualization")
def postprocess_visualization(request: PostprocessRequest) -> dict:
    return ansys_runner.postprocess_results(
        working_directory=request.working_directory,
        stress_curve_path=request.stress_curve_path,
        basename=request.basename,
    )


@app.post("/run-ansys-demo")
def run_ansys_demo(request: AnsysDemoRequest) -> dict:
    return ansys_runner.run_demo(
        launch_mapdl=request.launch_mapdl,
        working_directory=request.working_directory,
    )


@app.post("/run-mapdl-input")
def run_mapdl_input(request: MapdlInputRequest) -> dict:
    result = ansys_runner.run_input_file(
        input_file_path=request.input_file_path,
        working_directory=request.working_directory,
    )

    if not result.get("success"):
        return result

    if not request.analyze_after_run:
        return result

    primary_log_path = result.get("primary_log_path")
    if not primary_log_path:
        result["analysis"] = {
            "success": False,
            "message": "执行已完成，但未找到可分析的主日志文件。",
        }
        return result

    result["analysis"] = analyze_execution(
        source_name=primary_log_path,
        log_text=load_log_text(primary_log_path),
        engineering_results=result.get("engineering_results"),
        llm_analyzer=llm_analyzer,
    )
    return result


@app.post("/analyze-log")
def analyze_log(request: AnalyzeLogRequest) -> dict:
    if not request.log_path and not request.log_text:
        raise HTTPException(status_code=400, detail="请提供 log_path 或 log_text。")

    if request.log_path:
        log_file = Path(request.log_path)
        if not log_file.exists():
            raise HTTPException(status_code=400, detail=f"日志文件不存在：{log_file}")
        log_text = load_log_text(log_file)
        source_name = str(log_file)
    else:
        log_text = request.log_text or ""
        source_name = "direct_input.log"

    detected_errors = detect_errors(log_text)
    return analyze_execution(
        source_name=source_name,
        log_text=log_text,
        detected_errors=detected_errors,
        llm_analyzer=llm_analyzer,
    )


# ═══════════════════════════════
# 异步任务 API（流式证据 + 超时/取消）
# ═══════════════════════════════

@app.post("/runs", status_code=202)
def submit_run(request: RunJobRequest) -> dict:
    """提交异步求解任务，立即返回 run_id；轮询 GET /runs/{run_id} 获取状态与证据。"""
    try:
        run_id = job_manager.submit(
            kind=request.kind,
            params=request.params,
            timeout_seconds=request.timeout_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "run_id": run_id,
        "kind": request.kind,
        "status": "pending",
        "poll_url": f"/runs/{run_id}",
        "message": "任务已提交。轮询 poll_url 获取状态、结果与流式证据。",
    }


@app.get("/runs")
def list_runs(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    """列出最近的异步任务（新→旧）。"""
    runs = job_manager.list_jobs(limit=limit)
    return {"count": len(runs), "runs": runs}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    """查询单个任务；运行中附带 live_evidence 实时证据快照。"""
    job = job_manager.get_job(run_id, live_evidence=True)
    if job is None:
        raise HTTPException(status_code=404, detail=f"任务不存在：{run_id}")
    return job


@app.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> dict:
    """取消任务：运行中立即强杀求解会话，证据照常返回。"""
    job = job_manager.cancel(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"任务不存在：{run_id}")
    return job


# ═══════════════════════════════
# 项目监听（被动文件夹监视，分级实时）
# ═══════════════════════════════

@app.post("/monitors", status_code=201)
def create_monitor(request: CreateMonitorRequest) -> dict:
    """创建项目目录监听：有界递归跟踪求解日志，稳定触发、静默退避。"""
    target = Path(request.path)
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"路径不存在或不是目录：{request.path}")

    monitor = monitor_manager.create(
        path=request.path,
        interval=request.interval,
        depth=request.depth,
        auto_analyze=request.auto_analyze,
    )
    return {"monitor": monitor.view(), "message": "监听已创建并开始运行。"}


@app.get("/monitors")
def list_monitors() -> dict:
    monitors = monitor_manager.list_views()
    return {"count": len(monitors), "monitors": monitors}


@app.delete("/monitors/{monitor_id}")
def delete_monitor(monitor_id: str) -> dict:
    if not monitor_manager.remove(monitor_id):
        raise HTTPException(status_code=404, detail=f"监听不存在：{monitor_id}")
    return {"success": True, "message": f"监听已移除：{monitor_id}"}


@app.post("/monitors/{monitor_id}/auto-analyze")
def toggle_monitor_auto_analyze(monitor_id: str, request: ToggleAutoAnalyzeRequest) -> dict:
    """切换监听器的自动分析开关（开启后文件稳定且发现错误时自动调用 LLM）。"""
    if not monitor_manager.set_auto_analyze(monitor_id, request.enabled):
        raise HTTPException(status_code=404, detail=f"监听不存在：{monitor_id}")
    monitor = monitor_manager.get(monitor_id)
    return {"success": True, "monitor": monitor.view()}


@app.post("/monitors/{monitor_id}/pause")
def pause_monitor(monitor_id: str, request: MonitorPauseRequest) -> dict:
    """暂停/恢复监听：暂停期间不扫描不触发，配置保留，可即时恢复。"""
    if not monitor_manager.set_paused(monitor_id, request.paused):
        raise HTTPException(status_code=404, detail=f"监听不存在：{monitor_id}")
    monitor = monitor_manager.get(monitor_id)
    return {"success": True, "monitor": monitor.view()}


@app.post("/llm/config")
def update_llm_config(request: LlmConfigRequest) -> dict:
    """运行时更新 LLM 配置（API Key / 提供商 / 模型 / 接口地址）。

    仅内存生效：重启后回到 .env 配置。保存后可通过 /llm/test 验证连通。
    """
    try:
        config = llm_analyzer.update_config(
            api_key=request.api_key,
            provider=request.provider,
            model=request.model,
            base_url=request.base_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "success": True,
        "config": config,
        "message": "LLM 配置已更新（仅本次运行生效，重启后回到 .env 配置）。可通过“测试连通”验证。",
    }


@app.post("/monitor-analyze")
def monitor_analyze(request: MonitorAnalyzeRequest) -> dict:
    """人工触发：对监听内指定文件执行 LLM 诊断分析。"""
    return monitor_manager.run_analysis(monitor_id=request.monitor_id, rel_key=request.file, force=True)


@app.get("/fs/browse")
def fs_browse(path: Optional[str] = Query(default=None)) -> dict:
    """只读目录浏览：列出子目录（含各级 .out/.err 计数）与常见日志/输入文件，供前端选择项目。"""
    if path:
        target = Path(path)
    else:
        target = PROJECT_ROOT

    if not target.exists():
        raise HTTPException(status_code=400, detail=f"路径不存在：{target}")
    if not target.is_dir():
        target = target.parent

    relevant_suffixes = {".out", ".err", ".log", ".md", ".txt", ".inp", ".dat", ".mac"}
    directories: list[dict] = []
    files: list[dict] = []
    try:
        children = sorted(target.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"无法读取目录：{exc}")

    for child in children[:500]:
        try:
            if child.is_dir():
                solver_count = sum(1 for _ in child.glob("*.out")) + sum(1 for _ in child.glob("*.err"))
                directories.append(
                    {"name": child.name, "path": str(child), "solver_files": solver_count}
                )
            elif child.suffix.lower() in relevant_suffixes:
                files.append(
                    {"name": child.name, "path": str(child), "size_bytes": child.stat().st_size}
                )
        except OSError:
            continue

    parent = str(target.parent) if target.parent != target else None
    return {
        "path": str(target),
        "parent": parent,
        "directories": directories,
        "files": files,
    }


@app.post("/llm/test")
def llm_test() -> dict:
    """LLM 连通性强刷测试（忽略健康缓存）。"""
    return llm_analyzer.get_status(force_refresh=True)


# ═══════════════════════════════
# 运行监控仪表盘
# ═══════════════════════════════

DASHBOARD_FILE = PROJECT_ROOT / "static" / "dashboard.html"


@app.get("/dashboard")
def dashboard() -> FileResponse:
    if not DASHBOARD_FILE.exists():
        raise HTTPException(status_code=404, detail="仪表盘页面缺失：static/dashboard.html")
    return FileResponse(DASHBOARD_FILE, media_type="text/html")


@app.get("/dashboard/api/all")
def dashboard_all(since_events: int = Query(default=0, ge=0)) -> dict:
    """仪表盘聚合轮询端点：overview + 增量事件 + 任务列表 + 报告列表。"""
    jobs = job_manager.list_jobs(limit=50)
    overview = _get_cached_overview()
    return {
        "overview": {**overview, "job_summary": _job_summary(jobs)},
        "events": get_events(since_id=since_events, limit=100),
        "jobs": jobs,
        "monitors": monitor_manager.list_views(),
        "reports": _list_reports(),
        "server_time": datetime.now().isoformat(timespec="seconds"),
    }


def _get_cached_overview() -> dict:
    """overview 带缓存：环境探测涉及文件系统扫描与许可证子进程，不宜每轮询都执行。"""
    now = time.monotonic()
    if _overview_cache["data"] is None or now - _overview_cache["at"] > _OVERVIEW_CACHE_TTL:
        _overview_cache["data"] = {
            "llm": llm_analyzer.get_status(),
            "mapdl": ansys_runner.get_environment_status(),
            "mechanical": mechanical_runner.get_environment_status(),
        }
        _overview_cache["at"] = now
    return _overview_cache["data"]


def _job_summary(jobs: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for job in jobs:
        counts[job["status"]] = counts.get(job["status"], 0) + 1
    return {"total": len(jobs), "by_status": counts}


def _list_reports(limit: int = 50) -> list[dict]:
    reports_dir = project_path("reports")
    if not reports_dir.exists():
        return []
    items: list[dict] = []
    for path in reports_dir.iterdir():
        if not path.is_file():
            continue
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            }
        )
    items.sort(key=lambda item: item["modified_at"], reverse=True)
    return items[:limit]


@app.get("/reports/{filename}")
def get_report_file(filename: str) -> FileResponse:
    """查看/下载 reports 目录中的报告文件（仅允许纯文件名，防路径穿越）。"""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名。")
    path = project_path("reports") / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"报告文件不存在：{filename}")
    return FileResponse(path)
