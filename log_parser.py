import re
from pathlib import Path


# 中文说明：
# 这里维护一个最小错误模式表。
# 后续你可以持续扩展，比如增加：
# element distortion、time step too small、license error 等。
# suggestion 是错误反馈协议的一部分：命中模式时随证据一起返回给 LLM，
# 让模型无需 CAE 专业知识即可定向修正参数并重试。
ERROR_PATTERNS = {
    "singular_matrix": {
        "pattern": r"singular\s+matrix",
        "title": "刚度矩阵奇异",
        "description": "通常表示模型存在刚体位移、约束不足、单元失效或连接异常。",
        "suggestion": "检查约束是否充分（消除刚体自由度）、单元连接是否正常；可先降低接触刚度或补充弱弹簧，再复查边界条件。",
    },
    "convergence_failed": {
        "pattern": r"convergence\s+failed",
        "title": "非线性迭代不收敛",
        "description": "通常与接触、材料非线性、加载步长过大或初始状态不合理有关。",
        "suggestion": "减小时间步长/增大子步数（NSUBST）、开启自动时间步（AUTOTS,ON）与线性搜索，检查接触定义与初始间隙。",
    },
    "contact_penetration": {
        "pattern": r"contact\s+penetration",
        "title": "接触穿透",
        "description": "通常与接触刚度、初始间隙、网格质量或接触定义设置有关。",
        "suggestion": "降低接触法向刚度（FKN）、检查初始穿透量与几何间隙，必要时启用接触调整（CNOA）或局部加密网格。",
    },
    "license_error": {
        "pattern": r"license manager error|ansysli exited|checkout failed",
        "title": "许可证错误",
        "description": "通常表示许可证服务不可达、许可证不足，或许可证端口文件/环境配置异常。",
        "suggestion": "检查 ANSYS 许可服务（ansyscl/ansysli）是否运行、ANSYSLIC_DIR 与端口配置是否正确、防火墙是否放行。",
    },
    # ── Mechanical 专用错误 ──
    "mechanical_solver_failed": {
        "pattern": r"Solver\s+failed|Solution\s+failed|求解失败",
        "title": "Mechanical 求解失败",
        "description": "Mechanical 求解器未能完成计算，可能与模型设置、边界条件或材料参数有关。",
        "suggestion": "查看求解器输出中第一个异常（WARNING/ERROR）定位根因，检查边界条件、载荷与单位制一致性。",
    },
    "mechanical_contact_not_converged": {
        "pattern": r"Contact\s+region.*not\s+converged|接触.*不收敛|Contact\s+chatter",
        "title": "接触区域不收敛",
        "description": "Mechanical 接触迭代未能收敛，建议检查接触刚度、法向行为和初始间隙设置。",
        "suggestion": "调整接触刚度与积分点数量、消除初始过盈，或改用对称接触并增加稳定性阻尼。",
    },
    "mechanical_mesh_failed": {
        "pattern": r"Mesh\s+failed|网格.*失败|Meshing\s+failed",
        "title": "网格划分失败",
        "description": "Mechanical 网格生成器失败，可能由于几何缺陷、尺寸冲突或过度复杂的拓扑。",
        "suggestion": "清理几何缺陷（碎面、短边、小特征），放宽冲突的局部尺寸定义，或对复杂区域做切分后分块划分。",
    },
    "mechanical_large_deformation": {
        "pattern": r"Large\s+deformation|大变形|excessive\s+deformation",
        "title": "大变形问题",
        "description": "检测到过度变形，可能需要启用大变形效应、调整加载步长或检查材料/边界条件。",
        "suggestion": "开启大变形效应（NLGEOM,ON）、细分加载步，并核对材料曲线是否覆盖实际应变范围。",
    },
    "mechanical_rigid_body_motion": {
        "pattern": r"rigid\s+body\s+motion|刚体位移|insufficient\s+constraints",
        "title": "刚体位移",
        "description": "约束不足导致模型存在刚体自由度，检查边界条件和接触连接是否完整。",
        "suggestion": "补全约束消除刚体自由度，检查缺失的接触对，或临时添加弱弹簧辅助收敛。",
    },
}


# 中文说明：
# 警告模式表（流式证据监视器使用）。WARNING 大部分是无害噪音，
# 但部分警告是最终 ERROR 的根因（如初始穿透预示接触不收敛）。
# 只有命中此表的警告才会进入证据事件；未命中的只计数不占上下文。
WARNING_PATTERNS = {
    "contact_initial_penetration": {
        "pattern": r"initial\s+penetration",
        "title": "接触初始穿透",
        "description": "接触对存在初始穿透，可能预示后续接触收敛困难。",
        "suggestion": "检查几何间隙与过盈量，必要时启用接触调整（CNOA/IGA）或降低初始穿透。",
    },
    "contact_chattering": {
        "pattern": r"chattering",
        "title": "接触颤振",
        "description": "接触状态在分离/贴合间反复切换，常见于刚度不匹配或法向力不足。",
        "suggestion": "增大法向接触刚度、检查接触面法向方向，或增加接触积分点。",
    },
    "element_distortion": {
        "pattern": r"distorted|distortion",
        "title": "单元畸变",
        "description": "单元在大变形下过度扭曲，可能影响结果精度甚至导致不收敛。",
        "suggestion": "细化变形剧烈区域的网格、检查材料参数与加载步长，必要时开启大变形并减小增量。",
    },
    "small_pivot": {
        "pattern": r"\bpivot\b",
        "title": "矩阵主元警告",
        "description": "主元接近零通常意味着模型欠约束或存在刚体位移，是不收敛的常见前兆。",
        "suggestion": "检查是否漏加约束、接触是否缺失；对欠约束方向补充位移约束或弱弹簧。",
    },
    "convergence_diverging": {
        "pattern": r"diverg",
        "title": "收敛发散趋势",
        "description": "残差呈单调发散，当前步长或加载增量过大。",
        "suggestion": "减小时间步长/增大子步数，检查是否有突变加载或接触初始状态异常。",
    },
    "time_step_cutback": {
        "pattern": r"bisect|cut\s?-?back|time\s+step\s+(is\s+)?reduced",
        "title": "时间步自动削减",
        "description": "求解器已自动二分/削减时间步，说明当前增量下收敛困难。",
        "suggestion": "关注削减发生的位置（接触建立阶段/材料屈服阶段），针对性细化该阶段步长。",
    },
    "hourglass_energy": {
        "pattern": r"hourglass",
        "title": "沙漏能警告",
        "description": "缩减积分单元出现沙漏模式，能量占比过高会污染结果。",
        "suggestion": "开启沙漏控制、加密网格或改用全积分单元。",
    },
    "negative_eigenvalue": {
        "pattern": r"negative\s+eigenvalue",
        "title": "负特征值",
        "description": "切线刚度出现负值，常见于材料软化、屈曲前兆或接触状态突变。",
        "suggestion": "检查材料定义与接触状态，考虑弧长法（ARCLEN）或减小增量步。",
    },
}


# MAPDL 诊断块头行，例如：
# *** WARNING ***                           CP =      12.4   TIME = 10:32:01
# 真实求解输出中块头行首可能带缩进空格（.__tmp__.out / .err 常见），需容忍。
_BLOCK_HEADER = re.compile(r"^[ \t]*\*\*\*\s*(ERROR|WARNING|NOTE)\s*\*\*\*.*$", re.MULTILINE)


def load_log_text(log_path: str | Path) -> str:
    """读取日志文件内容。"""
    path = Path(log_path)
    return path.read_text(encoding="utf-8", errors="replace")


def parse_diagnostic_blocks(log_text: str) -> list[dict]:
    """一次性解析文本中的 MAPDL 诊断块（WARNING/ERROR/NOTE）。

    块 = 头行 + 正文，正文延续到空行分隔或下一个块头为止。
    返回元素结构：{"level", "header", "body", "text"}。
    流式场景请使用 solve_watcher.BlockStreamParser（增量、半块不产出）。
    """
    blocks: list[dict] = []
    if not log_text:
        return blocks

    # Windows 文本（\r\n）统一归一化为 \n，保证空行终结判定可靠
    log_text = log_text.replace("\r\n", "\n").replace("\r", "\n")

    matches = list(_BLOCK_HEADER.finditer(log_text))
    for i, match in enumerate(matches):
        body_start = match.end()
        next_start = matches[i + 1].start() if i + 1 < len(matches) else len(log_text)
        segment = log_text[body_start:next_start]
        blank = segment.find("\n\n")
        if blank != -1:
            body_end = body_start + blank
        else:
            body_end = next_start
        body = log_text[body_start:body_end].strip()
        blocks.append(
            {
                "level": match.group(1).upper(),
                "header": match.group(0).strip(),
                "body": body,
                "text": (match.group(0).strip() + "\n" + body).strip(),
            }
        )
    return blocks


def _build_snippet(log_text: str, start_index: int, window: int = 120) -> str:
    """截取错误附近的日志片段，方便后续分析。"""
    snippet_start = max(0, start_index - window)
    snippet_end = min(len(log_text), start_index + window)
    return log_text[snippet_start:snippet_end].strip()


def detect_errors(log_text: str, patterns: dict | None = None) -> list[dict]:
    """检测日志中的已知错误。

    Args:
        log_text: 日志全文。
        patterns: 模式表，默认 ERROR_PATTERNS；可传入 WARNING_PATTERNS 等复用同一匹配逻辑。
    """
    patterns = patterns or ERROR_PATTERNS
    detected: list[dict] = []

    # 中文说明：
    # 使用忽略大小写的正则匹配，尽量兼容不同软件输出格式。
    for error_code, config in patterns.items():
        matches = list(re.finditer(config["pattern"], log_text, flags=re.IGNORECASE))

        for match in matches:
            item = {
                "error_code": error_code,
                "title": config["title"],
                "description": config["description"],
                "matched_text": match.group(0),
                "snippet": _build_snippet(log_text, match.start()),
            }
            if config.get("suggestion"):
                item["suggestion"] = config["suggestion"]
            detected.append(item)

    return detected
