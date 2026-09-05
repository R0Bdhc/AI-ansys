import os
import subprocess
import sys
from pathlib import Path

from post_processor import PostProcessor
from simulation_templates import build_template, get_template_info, list_templates


class AnsysRunner:
    """封装 ANSYS / PyMAPDL 执行流程，集成模板仿真、后处理可视化与环境诊断。"""

    def __init__(self) -> None:
        self.default_workdir = Path("ansys_workspace")
        self.runtime_local_appdata = Path("runtime_data") / "localappdata"
        self.runtime_roaming_appdata = Path("runtime_data") / "appdata"
        self.runtime_pymapdl_user_data = self.runtime_local_appdata / "Ansys" / "ansys_mapdl_core"

        self.configured_mapdl_executable = self._optional_path("MAPDL_EXECUTABLE")
        self.ansys_dir = self._optional_path("ANSYS_DIR") or Path(
            os.getenv("ANSYS241_DIR", r"D:\ANSYS Inc\v241\ANSYS")
        )
        self.ansyslic_dir = Path(os.getenv("ANSYSLIC_DIR", r"D:\ANSYS Inc\Shared Files\Licensing"))
        self.awp_root = self._optional_path("AWP_ROOT") or Path(os.getenv("AWP_ROOT241", r"D:\ANSYS Inc\v241"))
        self.supported_input_suffixes = {".inp", ".dat", ".mac"}

        self.post_processor = PostProcessor(output_dir="reports")

    @staticmethod
    def _optional_path(variable_name: str) -> Path | None:
        value = os.getenv(variable_name, "").strip()
        return Path(value) if value else None

    # ───────────────────────────────
    # stdio 流保护（MCP 模式必需）
    # ───────────────────────────────

    @staticmethod
    def _stdio_guard(func):
        """装饰器：在工具调用期间将 sys.stdout 重定向到 sys.stderr，防止污染 JSON-RPC stdio 流。"""

        def wrapper(*args, **kwargs):
            original_stdout = sys.stdout
            try:
                sys.stdout = sys.stderr
                return func(*args, **kwargs)
            finally:
                sys.stdout = original_stdout

        return wrapper

    # ───────────────────────────────
    # 环境诊断增强
    # ───────────────────────────────

    @staticmethod
    def check_license_service() -> dict:
        """检查 ANSYS License Manager CVD 服务状态（Windows）。"""
        try:
            result = subprocess.run(
                ["sc", "query", "ANSYS, Inc. License Manager CVD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = result.stdout + result.stderr
            if "RUNNING" in output:
                return {"running": True, "message": "ANSYS License Manager CVD 服务正在运行。"}
            elif "STOPPED" in output:
                return {"running": False, "message": "ANSYS License Manager CVD 服务已停止。", "fix": "在 services.msc 中启动该服务。"}
            else:
                return {"running": False, "message": "无法确定许可证服务状态。", "detail": output[:500]}
        except Exception as exc:
            return {"running": False, "message": "检查许可证服务时出错。", "error": str(exc)}

    def get_environment_status(self) -> dict:
        self._prepare_pymapdl_runtime()

        try:
            from ansys.mapdl.core import launch_mapdl  # noqa: F401

            pymapdl_importable = True
            pymapdl_error = None
        except Exception as exc:
            pymapdl_importable = False
            pymapdl_error = str(exc)

        exec_file = self._find_mapdl_executable()
        license_status = self.check_license_service()
        viz_status = self.post_processor.check_visualization_env()

        status = {
            "pymapdl_importable": pymapdl_importable,
            "ansys_dir": str(self.ansys_dir),
            "ansys_dir_exists": self.ansys_dir.exists(),
            "ansyslic_dir": str(self.ansyslic_dir),
            "ansyslic_dir_exists": self.ansyslic_dir.exists(),
            "awp_root": str(self.awp_root),
            "awp_root_exists": self.awp_root.exists(),
            "configured_mapdl_executable": str(self.configured_mapdl_executable)
            if self.configured_mapdl_executable
            else None,
            "runtime_local_appdata": str(self.runtime_local_appdata.resolve()),
            "runtime_roaming_appdata": str(self.runtime_roaming_appdata.resolve()),
            "runtime_pymapdl_user_data": str(self.runtime_pymapdl_user_data.resolve()),
            "detected_mapdl_exec": str(exec_file) if exec_file else None,
            "detected_mapdl_exec_exists": exec_file is not None,
            "supported_input_suffixes": sorted(self.supported_input_suffixes),
            "license_service": license_status,
            "post_processing": viz_status,
            "message": self._build_status_message(
                pymapdl_importable=pymapdl_importable,
                exec_file=exec_file,
            ),
            "notes": [
                "MAPDL_EXECUTABLE 优先用于定位 MAPDL；ANSYS_DIR 和 AWP_ROOT 为目录级备用配置。",
                "ANSYS241_DIR 和 AWP_ROOT241 仍作为兼容旧配置的后备变量。",
                "ANSYSLIC_DIR 仅用于补充环境信息，本身通常不是许可证服务器地址。",
                "PyMAPDL 的运行时用户目录已重定向到工作区内的 runtime_data，避免系统目录写权限问题。",
                "当前接口支持 .inp、.dat、.mac 等 MAPDL 输入文件，不直接支持 .wbpj。",
                "后处理可视化依赖（PyVista、matplotlib、numpy）状态见 post_processing 字段。",
            ],
            "next_step": "可调用 /run-mapdl-input 执行真实 MAPDL 输入文件，或调用 /run-template-simulation 运行预定义模板。",
        }

        if pymapdl_error:
            status["pymapdl_error"] = pymapdl_error

        return status

    def get_demo_definition(self) -> dict:
        commands = self._build_demo_commands()
        exec_file = self._find_mapdl_executable()

        return {
            "success": True,
            "mode": "demo_definition",
            "description": "两节点拉杆静力分析示例，用于展示 Python 如何组织 ANSYS 调用。",
            "analysis_type": "static_structural",
            "element_type": "LINK180",
            "apdl_commands": commands,
            "detected_mapdl_exec": str(exec_file) if exec_file else None,
            "ansys_environment": {
                "ANSYS_DIR": str(self.ansys_dir),
                "ANSYSLIC_DIR": str(self.ansyslic_dir),
                "AWP_ROOT": str(self.awp_root),
                "MAPDL_EXECUTABLE": str(self.configured_mapdl_executable)
                if self.configured_mapdl_executable
                else None,
            },
            "notes": [
                "该接口默认仅返回演示命令，不真实启动 MAPDL。",
                "当前代码会优先使用 MAPDL_EXECUTABLE，再根据 ANSYS_DIR 和 AWP_ROOT 搜索 MAPDL.exe。",
                "接入真实工程时，建议优先传入 .inp、.dat 或 .mac 文件给 /run-mapdl-input。",
            ],
        }

    def run_demo(
        self,
        launch_mapdl: bool = False,
        working_directory: str | None = None,
        session_holder: dict | None = None,
    ) -> dict:
        """运行内置示例。session_holder 由异步任务层传入，launch 后写入 mapdl 句柄供超时强杀。"""
        resolved_workdir = Path(working_directory) if working_directory else self.default_workdir
        resolved_workdir.mkdir(parents=True, exist_ok=True)
        exec_file = self._find_mapdl_executable()

        if not launch_mapdl:
            return {
                "success": True,
                "mode": "preview_only",
                "message": "未启动 MAPDL，已返回最小 ANSYS 示例命令。",
                "working_directory": str(resolved_workdir.resolve()),
                "detected_mapdl_exec": str(exec_file) if exec_file else None,
                "apdl_commands": self._build_demo_commands(),
            }

        try:
            return self._run_with_commands(
                working_directory=resolved_workdir,
                exec_file=exec_file,
                commands=self._build_demo_commands(),
                source_name="internal_demo_commands",
                session_holder=session_holder,
            )
        except Exception as exc:
            return {
                "success": False,
                "mode": "mapdl_launch_failed",
                "message": "启动 MAPDL 失败，请检查 ANSYS 路径、许可证配置和相关环境变量。",
                "detail": str(exc),
                "working_directory": str(resolved_workdir.resolve()),
                "detected_mapdl_exec": str(exec_file) if exec_file else None,
                "apdl_commands": self._build_demo_commands(),
            }

    def run_input_file(
        self,
        input_file_path: str,
        working_directory: str | None = None,
        session_holder: dict | None = None,
    ) -> dict:
        input_path = Path(input_file_path)
        validation_error = self._validate_input_file(input_path)
        if validation_error:
            return validation_error

        resolved_workdir = Path(working_directory) if working_directory else self.default_workdir
        resolved_workdir.mkdir(parents=True, exist_ok=True)
        exec_file = self._find_mapdl_executable()

        try:
            return self._run_with_input_file(
                working_directory=resolved_workdir,
                exec_file=exec_file,
                input_path=input_path,
                session_holder=session_holder,
            )
        except Exception as exc:
            return {
                "success": False,
                "mode": "mapdl_input_failed",
                "message": "执行 MAPDL 输入文件失败。",
                "detail": str(exc),
                "input_file_path": str(input_path.resolve()),
                "working_directory": str(resolved_workdir.resolve()),
                "detected_mapdl_exec": str(exec_file) if exec_file else None,
                "candidate_log_files": self._collect_log_files(resolved_workdir),
            }

    @_stdio_guard
    def _run_with_input_file(
        self,
        working_directory: Path,
        exec_file: Path | None,
        input_path: Path,
        session_holder: dict | None = None,
    ) -> dict:
        self._prepare_pymapdl_runtime()

        from ansys.mapdl.core import launch_mapdl

        launch_kwargs = {
            "run_location": str(working_directory.resolve()),
            "override": True,
        }
        if exec_file is not None:
            launch_kwargs["exec_file"] = str(exec_file)

        mapdl = launch_mapdl(**launch_kwargs)
        if session_holder is not None:
            session_holder["mapdl"] = mapdl
        try:
            output_text = str(mapdl.input(str(input_path.resolve())))
            log_files = self._collect_log_files(working_directory)
            primary_log_path = self._select_primary_log_file(log_files)
            engineering_results = self._extract_engineering_results(mapdl)

            return {
                "success": True,
                "mode": "mapdl_input_executed",
                "message": "MAPDL 输入文件执行完成。",
                "input_file_path": str(input_path.resolve()),
                "working_directory": str(working_directory.resolve()),
                "used_exec_file": str(exec_file) if exec_file else None,
                "input_file_suffix": input_path.suffix.lower(),
                "mapdl_output_preview": output_text[:4000],
                "candidate_log_files": log_files,
                "primary_log_path": primary_log_path,
                "engineering_results": engineering_results,
            }
        finally:
            mapdl.exit()

    @_stdio_guard
    def _run_with_commands(
        self,
        working_directory: Path,
        exec_file: Path | None,
        commands: list[str],
        source_name: str,
        session_holder: dict | None = None,
    ) -> dict:
        self._prepare_pymapdl_runtime()

        from ansys.mapdl.core import launch_mapdl

        launch_kwargs = {
            "run_location": str(working_directory.resolve()),
            "override": True,
        }
        if exec_file is not None:
            launch_kwargs["exec_file"] = str(exec_file)

        mapdl = launch_mapdl(**launch_kwargs)
        if session_holder is not None:
            session_holder["mapdl"] = mapdl
        try:
            command_outputs: list[dict[str, str]] = []
            for command in commands:
                output_text = str(mapdl.run(command))
                command_outputs.append(
                    {
                        "command": command,
                        "output": output_text.strip(),
                    }
                )

            result_summary: dict[str, float] = {}
            if source_name == "internal_demo_commands":
                result_summary["node_2_ux"] = mapdl.get_value("NODE", 2, "U", "X")
            elif source_name == "template_cantilever":
                try:
                    result_summary["tip_uy"] = float(mapdl.parameters["TIP_UY"])
                except Exception:
                    pass
            log_files = self._collect_log_files(working_directory)
            engineering_results = self._extract_engineering_results(mapdl)

            return {
                "success": True,
                "mode": "mapdl_executed",
                "message": "MAPDL 示例执行完成。",
                "source_name": source_name,
                "working_directory": str(working_directory.resolve()),
                "used_exec_file": str(exec_file) if exec_file else None,
                "result_summary": result_summary,
                "executed_commands": commands,
                "command_outputs": command_outputs,
                "candidate_log_files": log_files,
                "primary_log_path": self._select_primary_log_file(log_files),
                "engineering_results": engineering_results,
            }
        finally:
            mapdl.exit()

    # ───────────────────────────────
    # 模板仿真
    # ───────────────────────────────

    def list_templates(self) -> dict:
        return {
            "success": True,
            "templates": list_templates(),
        }

    def get_template_info(self, template_type: str) -> dict:
        try:
            info = get_template_info(template_type)
            return {"success": True, "template": info}
        except ValueError as exc:
            return {"success": False, "message": str(exc)}

    def run_template_simulation(
        self,
        template_type: str,
        params: dict | None = None,
        working_directory: str | None = None,
        run_postprocess: bool = False,
        stress_curve_path: list[list[float]] | None = None,
        launch_mapdl: bool = False,
        session_holder: dict | None = None,
    ) -> dict:
        """运行预定义模板仿真，可选执行后处理可视化。"""
        try:
            commands = build_template(template_type, params)
        except ValueError as exc:
            return {"success": False, "message": str(exc)}

        resolved_workdir = Path(working_directory) if working_directory else self.default_workdir
        resolved_workdir.mkdir(parents=True, exist_ok=True)
        exec_file = self._find_mapdl_executable()

        preview = {
            "success": True,
            "mode": "preview_only",
            "template_type": template_type,
            "params": params,
            "working_directory": str(resolved_workdir.resolve()),
            "detected_mapdl_exec": str(exec_file) if exec_file else None,
            "apdl_commands": commands,
            "notes": [
                "当前为预览模式，未真实启动 MAPDL。",
                "如需真实执行，请传 launch_mapdl=true。",
            ],
        }

        if not launch_mapdl:
            return preview

        try:
            result = self._run_with_commands(
                working_directory=resolved_workdir,
                exec_file=exec_file,
                commands=commands,
                source_name=f"template_{template_type}",
                session_holder=session_holder,
            )
            result["template_type"] = template_type
            result["params"] = params

            if run_postprocess and result.get("success"):
                # 后处理需要保持 mapdl 连接，但 _run_with_commands 已退出。
                # 因此重新启动一个只读实例进行后处理（或修改流程）。
                # 简化方案：提示用户后处理需单独调用。
                result["postprocess_note"] = (
                    "求解已完成。后处理可视化需单独调用 /postprocess-visualization "
                    "并传入 working_directory 以加载结果文件。"
                )

            return result
        except Exception as exc:
            preview["mode"] = "mapdl_launch_failed"
            preview["message"] = "启动 MAPDL 失败。"
            preview["detail"] = str(exc)
            return preview

    def _prepare_pymapdl_runtime(self) -> None:
        self.runtime_local_appdata.mkdir(parents=True, exist_ok=True)
        self.runtime_roaming_appdata.mkdir(parents=True, exist_ok=True)
        (self.runtime_roaming_appdata / "Ansys").mkdir(parents=True, exist_ok=True)
        self.runtime_pymapdl_user_data.parent.mkdir(parents=True, exist_ok=True)

        os.environ["ANSYS_DIR"] = str(self.ansys_dir)
        os.environ["ANSYSLIC_DIR"] = str(self.ansyslic_dir)
        os.environ["AWP_ROOT"] = str(self.awp_root)
        os.environ["LOCALAPPDATA"] = str(self.runtime_local_appdata.resolve())
        os.environ["APPDATA"] = str(self.runtime_roaming_appdata.resolve())

        import platformdirs

        runtime_path = str(self.runtime_pymapdl_user_data.resolve())
        platformdirs.user_data_dir = lambda *args, **kwargs: runtime_path

    def _find_mapdl_executable(self) -> Path | None:
        if self.configured_mapdl_executable and self.configured_mapdl_executable.is_file():
            return self.configured_mapdl_executable

        ansys_directories = [self.ansys_dir, self.awp_root / "ANSYS"]
        for install_root in (Path(r"D:\Program Files (x86)"), Path(r"C:\Program Files"), Path(r"D:\ANSYS Inc")):
            ansys_directories.extend(install_root.glob("ANSYS Inc*/v*/ANSYS"))
            ansys_directories.extend(install_root.glob("v*/ANSYS"))

        checked_directories: set[Path] = set()
        for ansys_directory in ansys_directories:
            if ansys_directory in checked_directories:
                continue
            checked_directories.add(ansys_directory)
            executable_directory = ansys_directory / "bin" / "winx64"
            for pattern in ("MAPDL*.exe", "ANSYS*.exe"):
                for candidate in sorted(executable_directory.glob(pattern)):
                    if candidate.is_file():
                        return candidate

        return None

    def _validate_input_file(self, input_path: Path) -> dict | None:
        if not input_path.exists():
            return {
                "success": False,
                "mode": "invalid_input_file",
                "message": f"输入文件不存在：{input_path}",
            }

        suffix = input_path.suffix.lower()
        if suffix == ".wbpj":
            return {
                "success": False,
                "mode": "unsupported_workbench_project",
                "message": "当前接口不直接支持 .wbpj 工程文件。",
                "detail": "如果工程来自 Workbench，建议先导出 MAPDL 输入文件，例如 .inp 或命令流，再接入当前接口。",
                "input_file_path": str(input_path.resolve()),
            }

        if suffix not in self.supported_input_suffixes:
            return {
                "success": False,
                "mode": "unsupported_input_type",
                "message": f"当前接口暂不支持 {suffix or '无后缀'} 文件。",
                "detail": f"当前仅支持：{', '.join(sorted(self.supported_input_suffixes))}",
                "input_file_path": str(input_path.resolve()),
            }

        return None

    def _collect_log_files(self, working_directory: Path) -> list[str]:
        log_files: list[Path] = []
        for suffix in ("*.out", "*.log", "*.err"):
            log_files.extend(working_directory.glob(suffix))

        unique_files = sorted({path.resolve() for path in log_files}, key=lambda item: item.name.lower())
        return [str(path) for path in unique_files]

    def _select_primary_log_file(self, log_files: list[str]) -> str | None:
        if not log_files:
            return None

        existing_paths = [Path(item) for item in log_files if Path(item).exists()]
        if not existing_paths:
            return None

        ranked_paths = sorted(existing_paths, key=self._score_log_file, reverse=True)
        return str(ranked_paths[0])

    def _score_log_file(self, path: Path) -> tuple[int, int, int, float]:
        """优先选择正式输出，而不是隐藏或临时日志。"""
        name = path.name.lower()
        suffix = path.suffix.lower()
        size = path.stat().st_size if path.exists() else 0
        modified_at = path.stat().st_mtime if path.exists() else 0.0

        is_out = 1 if suffix == ".out" else 0
        is_non_temp = 0 if self._looks_like_temp_log(name) else 1
        is_non_empty = 1 if size > 0 else 0

        return (is_out, is_non_temp, is_non_empty, modified_at)

    @staticmethod
    def _looks_like_temp_log(file_name: str) -> bool:
        temp_markers = ("__tmp__", ".tmp", "scratch")
        return file_name.startswith(".") or any(marker in file_name for marker in temp_markers)

    def _build_status_message(self, pymapdl_importable: bool, exec_file: Path | None) -> str:
        if not pymapdl_importable:
            return "当前无法导入 PyMAPDL，暂时不能执行真实 ANSYS 示例。"
        if exec_file is None:
            return "PyMAPDL 已可用，但当前路径配置下未找到 MAPDL.exe。"
        return "PyMAPDL 已可用，并已检测到 MAPDL 可执行文件。"

    def _extract_engineering_results(self, mapdl) -> dict:
        """求解完成后提取位移、应力、频率等工程物理量。"""
        results: dict = {}

        try:
            mapdl.post1()
            mapdl.set("LAST")
            mapdl.allsel()
        except Exception:
            results["extraction_error"] = "无法进入 POST1 后处理，可能求解未成功。"
            return results

        # 位移
        displacement: dict = {}
        try:
            mapdl.nsort("U", "SUM")
            displacement["max_usum"] = mapdl.get_value("SORT", 0, "MAX")
            displacement["label_usum"] = "合位移 (USUM)"
        except Exception:
            pass
        try:
            mapdl.nsort("U", "X")
            displacement["max_ux"] = mapdl.get_value("SORT", 0, "MAX")
            displacement["label_ux"] = "X 向位移 (UX)"
            mapdl.nsort("U", "Y")
            displacement["max_uy"] = mapdl.get_value("SORT", 0, "MAX")
            displacement["label_uy"] = "Y 向位移 (UY)"
            mapdl.nsort("U", "Z")
            displacement["max_uz"] = mapdl.get_value("SORT", 0, "MAX")
            displacement["label_uz"] = "Z 向位移 (UZ)"
        except Exception:
            pass
        if displacement:
            results["displacement"] = displacement

        # 应力 — 尝试节点解
        stress: dict = {}
        try:
            mapdl.nsort("S", "EQV")
            stress["max_von_mises"] = mapdl.get_value("SORT", 0, "MAX")
            stress["label_von_mises"] = "Von Mises (SEQV)"
        except Exception:
            pass
        try:
            mapdl.nsort("S", "1")
            stress["max_s1"] = mapdl.get_value("SORT", 0, "MAX")
            stress["label_s1"] = "第一主应力 (S1)"
            mapdl.nsort("S", "3")
            stress["max_s3"] = mapdl.get_value("SORT", 0, "MAX")
            stress["label_s3"] = "第三主应力 (S3)"
        except Exception:
            pass
        try:
            mapdl.nsort("S", "X")
            stress["max_sx"] = mapdl.get_value("SORT", 0, "MAX")
            stress["label_sx"] = "X 向正应力 (SX)"
        except Exception:
            pass
        if stress:
            results["stress"] = stress

        # 支反力
        reaction: dict = {}
        try:
            reaction["fx"] = mapdl.get_value("FSUM", 0, "FX")
            reaction["fy"] = mapdl.get_value("FSUM", 0, "FY")
            reaction["fz"] = mapdl.get_value("FSUM", 0, "FZ")
            results["reaction_forces"] = reaction
        except Exception:
            pass

        # 模态频率
        frequencies = self._extract_frequencies(mapdl)
        if frequencies:
            results["frequency"] = {"modes": frequencies}

        return results

    def _extract_frequencies(self, mapdl) -> list[dict]:
        """尝试从结果文件中提取模态频率列表。"""
        try:
            raw = str(mapdl.set("LIST"))
            parsed = []
            for line in raw.split("\n"):
                parts = line.split()
                if len(parts) >= 2 and parts[0].isdigit():
                    try:
                        freq = float(parts[1])
                        parsed.append({"order": int(parts[0]), "frequency_hz": freq})
                    except ValueError:
                        continue
            return parsed[:20]
        except Exception:
            return []

    def _build_demo_commands(self) -> list[str]:
        return [
            "/CLEAR",
            "/PREP7",
            "ET,1,LINK180",
            "MP,EX,1,2.0E11",
            "MP,PRXY,1,0.3",
            "R,1,0.01",
            "N,1,0,0,0",
            "N,2,1,0,0",
            "TYPE,1",
            "REAL,1",
            "MAT,1",
            "E,1,2",
            "/SOLU",
            "ANTYPE,STATIC",
            "D,1,ALL,0",
            "F,2,FX,1000",
            "SOLVE",
            "FINISH",
            "/POST1",
            "SET,LAST",
        ]

    # ───────────────────────────────
    # 后处理：加载已有结果并可视化
    # ───────────────────────────────

    @_stdio_guard
    def postprocess_results(
        self,
        working_directory: str | None = None,
        stress_curve_path: list[list[float]] | None = None,
        basename: str = "post",
    ) -> dict:
        """启动 MAPDL 并加载指定工作目录的结果文件，执行后处理可视化。"""
        resolved_workdir = Path(working_directory) if working_directory else self.default_workdir
        if not resolved_workdir.exists():
            return {
                "success": False,
                "message": f"工作目录不存在：{resolved_workdir}",
            }

        exec_file = self._find_mapdl_executable()
        self._prepare_pymapdl_runtime()

        from ansys.mapdl.core import launch_mapdl

        launch_kwargs = {
            "run_location": str(resolved_workdir.resolve()),
            "override": True,
        }
        if exec_file is not None:
            launch_kwargs["exec_file"] = str(exec_file)

        try:
            mapdl = launch_mapdl(**launch_kwargs)
        except Exception as exc:
            return {
                "success": False,
                "message": "启动 MAPDL 进行后处理失败。",
                "detail": str(exc),
            }

        try:
            # 尝试读取结果文件
            try:
                mapdl.post1()
                mapdl.set("LAST")
                mapdl.allsel()
            except Exception as exc:
                return {
                    "success": False,
                    "message": "无法进入 POST1，可能结果文件不存在或求解未成功。",
                    "detail": str(exc),
                }

            # 执行工程结果提取
            engineering_results = self._extract_engineering_results(mapdl)

            # 执行可视化后处理
            post_result = self.post_processor.run_full_postprocess(
                mapdl,
                stress_curve_path=stress_curve_path,
                basename=basename,
            )

            return {
                "success": True,
                "mode": "postprocess_completed",
                "working_directory": str(resolved_workdir.resolve()),
                "engineering_results": engineering_results,
                "postprocess": post_result,
            }
        finally:
            mapdl.exit()
