"""
ansys_discovery.py
ANSYS 求解器发现与平台适配（跨版本 / 跨平台核心）。

设计约定：
- 版本无关：不假设特定版本号，探测链按版本号降序优先选最新安装；
- 平台分级：Windows 自动探测全支持；Linux 按官方安装布局探测 MAPDL
  （/usr/ansys_inc 等标准位置，best effort）；macOS 仅显式配置路径；
- 永不崩溃：所有探测返回结果 dict / None，任何平台状态接口都可用；
- 环境变量永远优先于自动探测，兼容旧版 ANSYS241_DIR / AWP_ROOT241。
"""

from __future__ import annotations

import os
import re
import string
import subprocess
import sys
from pathlib import Path
from typing import Any

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"

# Mechanical（PyMechanical 嵌入式模式）要求的最低版本
MIN_MECHANICAL_VERSION = 242

_VERSION_DIR_RE = re.compile(r"[vV](\d{3})")
_EXEC_FILENAME_RE = re.compile(r"v(\d{3})")


def infer_version(text: str | Path) -> int | None:
    """从路径/字符串中推断三位版本号（如 v252 → 252）。"""
    match = _VERSION_DIR_RE.search(str(text))
    return int(match.group(1)) if match else None


# ───────────────────────────────
# 标准安装根（按平台）
# ───────────────────────────────

def _windows_install_roots() -> list[Path]:
    roots: list[Path] = []
    for letter in string.ascii_uppercase:
        drive = Path(f"{letter}:\\")
        if not drive.exists():
            continue
        roots.extend(
            [
                drive / "Program Files",
                drive / "Program Files (x86)",
                drive,
            ]
        )
    return roots


def _unix_install_roots() -> list[Path]:
    roots = [
        Path("/usr/ansys_inc"),
        Path("/opt/ansys_inc"),
        Path("/ansys_inc"),
        Path.home() / "ansys_inc",
    ]
    return roots


def standard_install_roots() -> list[Path]:
    """可能包含 ANSYS Inc 安装目录的父级根列表。"""
    if IS_WINDOWS:
        return _windows_install_roots()
    return _unix_install_roots()


def _glob_ansys_install_dirs(roots: list[Path]) -> list[tuple[Path, int | None]]:
    """在根列表下 glob `ANSYS Inc*/v*` 与 `ansys_inc/v*` 形式的安装目录。"""
    found: dict[Path, int | None] = {}
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for install_dir in root.glob("ANSYS Inc*"):
                inc_root = root / "ansys_inc"
                _collect_versions(install_dir, found)
            inc_root = root / "ansys_inc"
            if inc_root.is_dir():
                _collect_versions(inc_root, found)
        except OSError:
            continue
    return sorted(found.items(), key=lambda item: (item[1] or 0), reverse=True)


def _collect_versions(install_parent: Path, found: dict[Path, int | None]) -> None:
    try:
        for version_dir in install_parent.glob("v*"):
            if not version_dir.is_dir():
                continue
            found[version_dir] = infer_version(version_dir.name)
    except OSError:
        pass


# ───────────────────────────────
# MAPDL 发现
# ───────────────────────────────

def _mapdl_binary_candidates(version_dir: Path) -> list[Path]:
    """单个版本目录下 MAPDL 可执行文件的候选路径。"""
    if IS_WINDOWS:
        bin_dir = version_dir / "ANSYS" / "bin" / "winx64"
        candidates: list[Path] = []
        for pattern in ("MAPDL*.exe", "ANSYS*.exe", "mapdl*.exe"):
            try:
                candidates.extend(sorted(bin_dir.glob(pattern)))
            except OSError:
                continue
        return [c for c in candidates if c.is_file()]

    bin_dir = version_dir / "ansys" / "bin"
    candidates = []
    for pattern in (f"ansys{version_dir.name[1:]}", "ansys", "mapdl", "MAPDL", "ANSYS*"):
        try:
            candidates.extend(sorted(bin_dir.glob(pattern)))
        except OSError:
            continue
    return [
        c
        for c in candidates
        if c.is_file() and (os.access(c, os.X_OK) or c.suffix.lower() == ".exe")
    ]


def _env_mapdl_roots() -> list[tuple[Path, int | None]]:
    """从环境变量收集候选根：显式目录优先，兼容旧版变量名。"""
    candidates: dict[Path, int | None] = {}
    for var in ("ANSYS_DIR", "MAPDL_DIR"):
        value = os.getenv(var, "").strip()
        if value:
            candidates[Path(value)] = infer_version(value)
    for name, value in os.environ.items():
        upper = name.upper()
        if upper.startswith("AWP_ROOT") and value.strip():
            candidates[Path(value.strip())] = infer_version(name) or infer_version(value)
        elif upper.startswith("ANSYS") and upper.endswith("_DIR") and value.strip():
            candidates[Path(value.strip())] = infer_version(name) or infer_version(value)
    return sorted(candidates.items(), key=lambda item: (item[1] or 0), reverse=True)


def discover_mapdl() -> dict[str, Any]:
    """发现 MAPDL 可执行文件。

    返回：{exec_path, version, source, all_versions, searched}
    - source: explicit_env / env_dir / env_root / standard_install / not_found
    - exec_path: Path 或 None
    """
    searched_notes: list[str] = []

    explicit = os.getenv("MAPDL_EXECUTABLE", "").strip()
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return {
                "exec_path": path,
                "version": infer_version(path),
                "source": "explicit_env",
                "all_versions": [],
                "searched": [f"MAPDL_EXECUTABLE={explicit}"],
            }
        searched_notes.append(f"MAPDL_EXECUTABLE 指向的路径不存在：{explicit}")

    # 显式目录（ANSYS_DIR 类）：直接在其 bin 下找
    for env_dir, version in _env_mapdl_roots():
        direct = _mapdl_binary_candidates(env_dir) if (env_dir / "bin").is_dir() or IS_WINDOWS else []
        # env_dir 可能是 ANSYS/bin 层级而非 v* 层级
        if not direct:
            direct = _mapdl_binary_candidates_from_any_bin(env_dir)
        if direct:
            return {
                "exec_path": direct[0],
                "version": version or infer_version(env_dir),
                "source": "env_dir",
                "all_versions": [],
                "searched": searched_notes + [f"环境变量目录：{env_dir}"],
            }
        searched_notes.append(f"环境变量目录未见 MAPDL 可执行文件：{env_dir}")

    # 标准安装位置：v* 目录逐个找，版本降序
    install_dirs = _glob_ansys_install_dirs(standard_install_roots())
    all_versions = sorted({v for _, v in install_dirs if v}, reverse=True)
    for version_dir, version in install_dirs:
        for candidate in _mapdl_binary_candidates(version_dir):
            return {
                "exec_path": candidate,
                "version": version,
                "source": "standard_install",
                "all_versions": all_versions,
                "searched": searched_notes,
            }

    return {
        "exec_path": None,
        "version": None,
        "source": "not_found",
        "all_versions": all_versions,
        "searched": searched_notes,
    }


def _mapdl_binary_candidates_from_any_bin(env_dir: Path) -> list[Path]:
    """环境变量目录结构未知时，向下两层找 bin 目录里的可执行文件。"""
    if IS_WINDOWS:
        patterns = ("MAPDL*.exe", "ANSYS*.exe", "mapdl*.exe")
        suffix_ok = lambda p: p.suffix.lower() == ".exe"  # noqa: E731
    else:
        patterns = ("ansys*", "mapdl*", "MAPDL*")
        suffix_ok = lambda p: True  # noqa: E731

    scan_dirs: list[Path] = []
    if env_dir.name.lower() == "bin":
        scan_dirs.append(env_dir)
    else:
        try:
            scan_dirs.extend(d for d in env_dir.glob("*/bin") if d.is_dir())
            if (env_dir / "bin").is_dir():
                scan_dirs.append(env_dir / "bin")
        except OSError:
            pass

    for scan_dir in scan_dirs:
        for pattern in patterns:
            try:
                for candidate in sorted(scan_dir.glob(pattern)):
                    if candidate.is_file() and (suffix_ok(candidate) or os.access(candidate, os.X_OK)):
                        return [candidate]
            except OSError:
                continue
    return []


# ───────────────────────────────
# Mechanical 发现
# ───────────────────────────────

def _mechanical_binary_candidates(version_dir: Path) -> list[Path]:
    """单个版本目录下 Mechanical 启动器的候选路径。

    Windows: v*/aisol/bin/winx64/AnsysWBU.exe
    Linux/macOS: v*/aisol/bin/*64*/ 下名称含 WBU 的可执行文件（不假设精确文件名）
    """
    aisol_bin = version_dir / "aisol" / "bin"
    candidates: list[Path] = []
    try:
        if IS_WINDOWS:
            candidates.extend(sorted(aisol_bin.glob("winx64/AnsysWBU.exe")))
        else:
            for bin_dir in aisol_bin.glob("*64*"):
                if not bin_dir.is_dir():
                    continue
                for candidate in sorted(bin_dir.glob("*WBU*")):
                    if candidate.is_file() and (
                        os.access(candidate, os.X_OK) or candidate.suffix.lower() == ".exe"
                    ):
                        candidates.append(candidate)
    except OSError:
        pass
    return candidates


def discover_mechanical() -> dict[str, Any]:
    """发现 242+ Mechanical 启动器。返回结构与 discover_mapdl 一致。"""
    explicit = os.getenv("MECHANICAL_EXEC", "").strip()
    if explicit:
        path = Path(explicit)
        if path.exists():
            return {
                "exec_path": path,
                "version": infer_version(path),
                "source": "explicit_env",
                "all_versions": [],
                "searched": [f"MECHANICAL_EXEC={explicit}"],
            }

    # 环境变量根（AWP_ROOT*）
    for env_root, version in _env_mapdl_roots():
        version = version or infer_version(env_root)
        candidates = _mechanical_binary_candidates(env_root)
        if not candidates:
            # env_root 可能直接是 vXXX 目录或其上层
            try:
                for sub in sorted(env_root.glob("v*")):
                    candidates.extend(_mechanical_binary_candidates(sub))
            except OSError:
                pass
        if candidates:
            return {
                "exec_path": candidates[0],
                "version": version or infer_version(candidates[0]),
                "source": "env_root",
                "all_versions": [],
                "searched": [],
            }

    # 标准安装位置
    install_dirs = _glob_ansys_install_dirs(standard_install_roots())
    all_versions = sorted({v for _, v in install_dirs if v}, reverse=True)
    for version_dir, version in install_dirs:
        candidates = _mechanical_binary_candidates(version_dir)
        if candidates:
            return {
                "exec_path": candidates[0],
                "version": version,
                "source": "standard_install",
                "all_versions": all_versions,
                "searched": [],
            }

    return {
        "exec_path": None,
        "version": None,
        "source": "not_found",
        "all_versions": all_versions,
        "searched": [],
    }


# ───────────────────────────────
# 许可证状态（跨平台，永不抛异常）
# ───────────────────────────────

_LICENSE_PROCESS_HINTS = ("ansyscl", "lmgrd", "ansysli", "ansys license")


def check_license_status() -> dict[str, Any]:
    """检查 ANSYS 许可服务/守护进程状态。"""
    if IS_WINDOWS:
        return _check_license_windows()
    return _check_license_unix()


def _check_license_windows() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["sc", "query", "ANSYS, Inc. License Manager CVD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        output = result.stdout + result.stderr
        # encoding+errors 保证 reader 线程在中文 Windows（GBK 输出）下不崩溃，ASCII 状态字保留
        if "RUNNING" in output:
            return {"running": True, "message": "ANSYS License Manager CVD 服务正在运行。"}
        if "STOPPED" in output:
            return {
                "running": False,
                "message": "ANSYS License Manager CVD 服务已停止。",
                "fix": "在 services.msc 中启动该服务。",
            }
        return {"running": False, "message": "无法确定许可证服务状态。", "detail": output[:500]}
    except Exception as exc:
        return {"running": False, "message": "检查许可证服务时出错。", "error": str(exc)}


def _check_license_unix() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["ps", "-e", "-o", "comm="],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        processes = result.stdout.lower().split()
        matched = [hint for hint in _LICENSE_PROCESS_HINTS if any(hint in p for p in processes)]
        if matched:
            return {
                "running": True,
                "message": f"检测到许可证相关进程：{', '.join(sorted(set(matched)))}。",
            }
        return {
            "running": False,
            "message": "未检测到 ANSYS 许可证进程（ansyscl/lmgrd/ansysli）。",
        }
    except Exception as exc:
        return {"running": False, "message": "检查许可证进程时出错。", "error": str(exc)}


# ───────────────────────────────
# 运行时目录重定向（平台感知）
# ───────────────────────────────

def prepare_runtime_dirs(runtime_root: Path) -> None:
    """把求解器 Python 库的运行期用户目录重定向到项目内 runtime_data。

    Windows: 改写 LOCALAPPDATA / APPDATA（本机异常权限场景的原有行为）。
    Linux/macOS: 改写 XDG_CACHE_HOME / XDG_DATA_HOME / XDG_CONFIG_HOME。
    两个平台都 monkeypatch platformdirs / appdirs 兜底。
    """
    runtime_root = runtime_root.resolve()
    local_dir = runtime_root / "localappdata"
    roaming_dir = runtime_root / "appdata"
    local_dir.mkdir(parents=True, exist_ok=True)
    roaming_dir.mkdir(parents=True, exist_ok=True)
    (roaming_dir / "Ansys").mkdir(parents=True, exist_ok=True)

    if IS_WINDOWS:
        os.environ["LOCALAPPDATA"] = str(local_dir)
        os.environ["APPDATA"] = str(roaming_dir)
    else:
        os.environ["XDG_CACHE_HOME"] = str(local_dir / "cache")
        os.environ["XDG_DATA_HOME"] = str(local_dir / "data")
        os.environ["XDG_CONFIG_HOME"] = str(local_dir / "config")
        (local_dir / "cache").mkdir(parents=True, exist_ok=True)
        (local_dir / "data").mkdir(parents=True, exist_ok=True)
        (local_dir / "config").mkdir(parents=True, exist_ok=True)

    try:
        import platformdirs

        def _patched_platformdirs(*args, **kwargs) -> str:
            appname = kwargs.get("appname", "app")
            appauthor = kwargs.get("appauthor")
            if appauthor == "Ansys":
                return str(local_dir / "Ansys" / appname)
            return str(local_dir / appname)

        platformdirs.user_data_dir = _patched_platformdirs
    except ImportError:
        pass

    try:
        import appdirs

        def _patched_appdirs(*args, **kwargs) -> str:
            appname = kwargs.get("appname", "app")
            appauthor = kwargs.get("appauthor")
            if appauthor == "Ansys":
                return str(local_dir / "Ansys" / appname)
            return str(local_dir / appname)

        appdirs.user_data_dir = _patched_appdirs
    except ImportError:
        pass


def platform_label() -> str:
    """当前平台标识（状态接口展示用）。"""
    if IS_WINDOWS:
        return "windows"
    if IS_LINUX:
        return "linux"
    if IS_MACOS:
        return "macos"
    return sys.platform
