"""
llm_analyzer.py
多提供商 LLM 分析模块，支持 DeepSeek、Kimi、Claude、OpenAI、本地模型及任意 OpenAI 兼容接口。

支持的提供商（LLM_PROVIDER）：
    deepseek  - DeepSeek 官方 API
    kimi      - Moonshot AI (Kimi)
    claude    - Anthropic Claude（通过 OpenAI 兼容接口或中转）
    openai    - OpenAI 官方 API
    local     - 本地 Ollama / vLLM / lmstudio 等（OpenAI 兼容）
    custom    - 自定义 OpenAI 兼容接口

环境变量优先级：
    LLM_API_KEY > DEEPSEEK_API_KEY / OPENAI_API_KEY
    LLM_BASE_URL > DEEPSEEK_BASE_URL
    LLM_MODEL > DEEPSEEK_MODEL
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from observability import record_llm_call


# ───────────────────────────────
# 提供商预设配置
# ───────────────────────────────

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-pro",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
    },
    "claude": {
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-4-20250514",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
    },
    "local": {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5",
    },
    "custom": {
        "base_url": "",
        "model": "",
    },
}


@dataclass
class LLMConfig:
    """解析后的 LLM 配置。"""

    provider: str
    api_key: str
    base_url: str
    model: str

    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)


class LLMAnalyzer:
    """负责 LLM 分析，支持多提供商切换，并在失败时回退到本地规则分析。"""

    def __init__(self) -> None:
        self.config = self._resolve_config()
        self.client = self._create_client() if self.config.is_configured() else None
        self._health_cache_ttl_seconds = 300
        self._last_health_check_at = 0.0
        self._last_health_status: dict[str, Any] | None = None

    # ───────────────────────────────
    # 配置解析
    # ───────────────────────────────

    @staticmethod
    def _resolve_config() -> LLMConfig:
        """解析 LLM 配置，优先使用新版 LLM_* 变量，兼容旧版 DEEPSEEK_* / OPENAI_* 变量。"""
        provider = os.getenv("LLM_PROVIDER", "").strip().lower()

        # 如果没有显式指定 provider，根据旧版变量推断
        if not provider:
            if os.getenv("DEEPSEEK_API_KEY"):
                provider = "deepseek"
            elif os.getenv("OPENAI_API_KEY"):
                provider = "openai"
            else:
                provider = "deepseek"  # 默认保持向后兼容

        preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["custom"])

        # 优先级：LLM_* > provider 预设默认值 > 旧版变量（旧版变量仅在未指定 LLM_PROVIDER 时生效）
        api_key = (
            os.getenv("LLM_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )

        # base_url：显式 LLM_BASE_URL > provider 预设 > 旧版兜底
        base_url = os.getenv("LLM_BASE_URL", "")
        if not base_url:
            base_url = preset["base_url"]
        if not base_url:
            base_url = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("OPENAI_BASE_URL") or ""

        # model：显式 LLM_MODEL > provider 预设 > 旧版兜底
        model = os.getenv("LLM_MODEL", "")
        if not model:
            model = preset["model"]
        if not model:
            model = os.getenv("DEEPSEEK_MODEL") or os.getenv("OPENAI_MODEL") or ""

        return LLMConfig(provider=provider, api_key=api_key, base_url=base_url, model=model)

    @staticmethod
    def list_supported_providers() -> list[dict[str, str]]:
        """返回所有支持的提供商列表。"""
        return [
            {"id": key, "name": _provider_display_name(key), "default_model": val["model"]}
            for key, val in PROVIDER_PRESETS.items()
        ]

    def _create_client(self) -> OpenAI | None:
        """根据配置创建 OpenAI 兼容客户端。"""
        try:
            return OpenAI(api_key=self.config.api_key, base_url=self.config.base_url)
        except Exception:
            return None

    def update_config(
        self,
        api_key: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """运行时更新 LLM 配置（仅内存生效，重启后回到 .env 配置）。

        切换 provider 且未显式给 model/base_url 时，回落到该 provider 的预设默认值。
        返回 get_config() 轻量结果；连通性由调用方通过 get_status(force_refresh=True) 验证。
        """
        if provider:
            provider = provider.strip().lower()
            if provider not in PROVIDER_PRESETS:
                raise ValueError(f"不支持的提供商：{provider}。可用：{sorted(PROVIDER_PRESETS)}")
            self.config.provider = provider
            preset = PROVIDER_PRESETS[provider]
            if not model or not str(model).strip():
                self.config.model = preset["model"]
            if not base_url or not str(base_url).strip():
                if preset["base_url"]:
                    self.config.base_url = preset["base_url"]
        if base_url is not None and str(base_url).strip():
            self.config.base_url = str(base_url).strip()
        if model is not None and str(model).strip():
            self.config.model = str(model).strip()
        if api_key is not None and str(api_key).strip():
            self.config.api_key = str(api_key).strip()

        # 同步进程环境变量，保持后续重新解析路径一致
        os.environ["LLM_PROVIDER"] = self.config.provider
        os.environ["LLM_API_KEY"] = self.config.api_key
        os.environ["LLM_BASE_URL"] = self.config.base_url
        os.environ["LLM_MODEL"] = self.config.model

        self.client = self._create_client() if self.config.is_configured() else None
        self._last_health_status = None
        self._last_health_check_at = 0.0
        return self.get_config()

    # ───────────────────────────────
    # 状态查询
    # ───────────────────────────────

    def is_available(self) -> bool:
        return self.client is not None

    def get_config(self) -> dict[str, Any]:
        """返回当前解析后的配置（隐藏 API Key）。"""
        return {
            "provider": self.config.provider,
            "base_url": self.config.base_url,
            "model": self.config.model,
            "api_key_configured": bool(self.config.api_key),
            "fully_configured": self.config.is_configured(),
        }

    def get_status(self, force_refresh: bool = False) -> dict[str, Any]:
        """返回 LLM 当前是否已配置以及是否可连通。"""
        if self.client is None:
            return {
                "configured": False,
                "provider": self.config.provider,
                "model": self.config.model,
                "base_url": self.config.base_url,
                "reachable": False,
                "checked_at": None,
                "message": "未配置 LLM API Key，系统将使用本地规则分析。",
                "supported_providers": self.list_supported_providers(),
            }

        now = time.time()
        if (
            not force_refresh
            and self._last_health_status is not None
            and now - self._last_health_check_at < self._health_cache_ttl_seconds
        ):
            return self._last_health_status

        status: dict[str, Any] = {
            "configured": True,
            "provider": self.config.provider,
            "model": self.config.model,
            "base_url": self.config.base_url,
            "reachable": False,
            "checked_at": int(now),
            "supported_providers": self.list_supported_providers(),
        }

        try:
            self.client.models.list()
            status["reachable"] = True
            status["message"] = f"{self.config.provider} 已配置，且当前可正常连通。"
        except Exception as exc:
            status["error"] = str(exc)
            status["message"] = (
                f"{self.config.provider} 已配置，但当前不可连通，系统将回退到本地规则分析。"
            )

        self._last_health_check_at = now
        self._last_health_status = status
        return status

    # ───────────────────────────────
    # 分析入口
    # ───────────────────────────────

    def analyze(self, source_name: str, log_text: str, detected_errors: list[dict]) -> dict:
        """分析入口：执行诊断并记录观测事件（仪表盘 LLM 面板数据源）。"""
        started = time.monotonic()
        result = self._analyze_impl(source_name, log_text, detected_errors)
        latency_ms = (time.monotonic() - started) * 1000
        try:
            record_llm_call(
                source_name=source_name,
                mode=result.get("mode", "unknown"),
                model=result.get("model") or (self.config.model if self.client else None),
                provider=self.config.provider,
                detected_error_count=len(detected_errors),
                prompt=(
                    self._build_prompt(source_name, log_text, detected_errors)
                    if detected_errors
                    else None
                ),
                response=result.get("raw_analysis"),
                latency_ms=latency_ms,
                llm_error=result.get("llm_error"),
            )
        except Exception:
            pass  # 观测失败不影响分析结果
        return result

    def _analyze_impl(self, source_name: str, log_text: str, detected_errors: list[dict]) -> dict:
        if not detected_errors:
            return {
                "mode": "rule_based",
                "summary": "日志中未检测到预设错误关键词。",
                "possible_causes": ["当前规则库中未发现明显异常。"],
                "suggestions": ["建议继续扩展错误规则，或人工检查完整日志上下文。"],
            }

        if self.client is None:
            return self._fallback_analysis(detected_errors)

        try:
            result = self._analyze_with_llm(source_name, log_text, detected_errors)
            now = time.time()
            self._last_health_check_at = now
            self._last_health_status = {
                "configured": True,
                "provider": self.config.provider,
                "model": self.config.model,
                "base_url": self.config.base_url,
                "reachable": True,
                "checked_at": int(now),
                "message": f"最近一次 {self.config.provider} 调用成功。",
            }
            return result
        except Exception as exc:
            fallback_result = self._fallback_analysis(detected_errors)
            fallback_result["mode"] = "fallback_after_llm_error"
            fallback_result["llm_error"] = str(exc)

            now = time.time()
            self._last_health_check_at = now
            self._last_health_status = {
                "configured": True,
                "provider": self.config.provider,
                "model": self.config.model,
                "base_url": self.config.base_url,
                "reachable": False,
                "checked_at": int(now),
                "message": f"最近一次 {self.config.provider} 调用失败，系统已回退到本地规则分析。",
                "error": str(exc),
            }
            return fallback_result

    def _analyze_with_llm(self, source_name: str, log_text: str, detected_errors: list[dict]) -> dict:
        prompt = self._build_prompt(source_name, log_text, detected_errors)
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=[{"role": "user", "content": prompt}],
        )
        text_result = (response.choices[0].message.content or "").strip()

        return {
            "mode": self.config.provider,
            "model": self.config.model,
            "summary": f"已使用 {self.config.provider} ({self.config.model}) 生成错误分析。",
            "raw_analysis": text_result,
            "possible_causes": [],
            "suggestions": [],
        }

    # ───────────────────────────────
    # Prompt 构建
    # ───────────────────────────────

    def _build_prompt(self, source_name: str, log_text: str, detected_errors: list[dict]) -> str:
        error_lines = []
        for item in detected_errors:
            error_lines.append(
                f"- 错误代码：{item['error_code']}\n"
                f"  标题：{item['title']}\n"
                f"  描述：{item['description']}\n"
                f"  日志片段：{item['snippet']}"
            )

        joined_errors = "\n".join(error_lines)
        truncated_log_text = log_text[:4000]

        return f"""
你是一名 ANSYS 结构、非线性与 Mechanical 分析专家，精通 MAPDL APDL 命令流和 Mechanical Workbench 仿真流程。
请根据日志帮助工程师定位问题，并提供可操作的修改建议。
请使用中文输出，并严格按下面格式回答：
1. 问题概述
2. 可能原因
3. 修改建议
4. 建议优先排查顺序

日志来源：{source_name}

已检测错误：
{joined_errors}

日志全文片段：
{truncated_log_text}
""".strip()

    # ───────────────────────────────
    # 本地规则回退
    # ───────────────────────────────

    def _fallback_analysis(self, detected_errors: list[dict]) -> dict:
        possible_causes: list[str] = []
        suggestions: list[str] = []

        error_codes = {item["error_code"] for item in detected_errors}

        if "singular_matrix" in error_codes:
            possible_causes.append("模型约束不足，存在刚体位移自由度。")
            possible_causes.append("单元连接不连续，或关键部位出现悬空节点。")
            suggestions.append("优先检查边界条件、耦合关系和接触连接是否完整。")
            suggestions.append("检查模型是否存在未约束的部件或失效单元。")

        if "convergence_failed" in error_codes:
            possible_causes.append("非线性过强，当前载荷步或子步设置过大。")
            possible_causes.append("材料参数、接触参数或初始状态设置不合理。")
            suggestions.append("减小载荷步长，增加子步数，必要时启用自动时间步。")
            suggestions.append("检查接触刚度、摩擦参数和材料本构输入是否稳定。")

        if "contact_penetration" in error_codes:
            possible_causes.append("接触初始闭合状态不合理，或接触刚度设置偏弱。")
            possible_causes.append("接触面网格过粗，导致接触搜索与法向响应不稳定。")
            suggestions.append("检查初始接触状态、法向刚度和接触算法设置。")
            suggestions.append("局部加密接触区网格，并检查接触/目标面方向。")

        # ── Mechanical 专用规则 ──
        if "mechanical_solver_failed" in error_codes:
            possible_causes.append("Mechanical 模型设置存在矛盾，如约束与载荷冲突、材料参数不合理。")
            possible_causes.append("网格质量过低，存在扭曲单元或长宽比过大单元。")
            suggestions.append("检查边界条件和载荷定义是否完整且不自相矛盾。")
            suggestions.append("重新划分网格，检查单元质量（Jacobian、长宽比）。")

        if "mechanical_contact_not_converged" in error_codes:
            possible_causes.append("Mechanical 接触法向刚度因子（FKN）设置不合理。")
            possible_causes.append("接触初始状态为 Far/Open，或 Pinball 半径过小导致搜索失败。")
            suggestions.append("调整接触刚度因子（弯曲主导建议 0.1~0.5，调试穿透可从 0.01 开始）。")
            suggestions.append("检查接触初始状态，必要时调整 Pinball 半径或启用接触稳定化。")

        if "mechanical_mesh_failed" in error_codes:
            possible_causes.append("几何存在缺陷（短边、缝隙、非流形边）。")
            possible_causes.append("全局或局部网格尺寸设置冲突，导致无法生成单元。")
            suggestions.append("修复几何缺陷，使用 SpaceClaim 或 DesignModeler 清理模型。")
            suggestions.append("放宽局部加密尺寸，或改用 Patch Conforming / Patch Independent 方法。")

        if "mechanical_large_deformation" in error_codes:
            possible_causes.append("未启用大变形效应，但当前变形量已超出小变形假设。")
            possible_causes.append("载荷过大或材料刚度设置过低，导致结构失稳。")
            suggestions.append("在 Analysis Settings 中启用 Large Deflection。")
            suggestions.append("减小载荷步长，检查材料参数和约束是否足够。")

        if "mechanical_rigid_body_motion" in error_codes:
            possible_causes.append("Mechanical 约束不足，存在未约束的自由度。")
            possible_causes.append("接触对设置不完整，导致部件间缺少传力路径。")
            suggestions.append("检查所有部件是否都有足够的边界约束。")
            suggestions.append("检查接触定义是否覆盖所有相邻部件的界面。")

        return {
            "mode": "rule_based",
            "summary": "未启用 LLM，已使用本地规则生成基础分析。",
            "possible_causes": self._deduplicate(possible_causes),
            "suggestions": self._deduplicate(suggestions),
        }

    @staticmethod
    def _deduplicate(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result


def _provider_display_name(provider_id: str) -> str:
    mapping = {
        "deepseek": "DeepSeek",
        "kimi": "Kimi (Moonshot)",
        "claude": "Claude (Anthropic)",
        "openai": "OpenAI",
        "local": "Local / Ollama / vLLM",
        "custom": "Custom OpenAI-compatible",
    }
    return mapping.get(provider_id, provider_id)
