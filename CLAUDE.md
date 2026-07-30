# CLAUDE.md — cae-agent

面向 ANSYS 场景的最小可运行 CAE 智能辅助系统。

## 架构概览

```
main.py          FastAPI 入口，13+ 个 REST 端点，组装层
├─ log_parser.py      日志解析 + 正则错误检测（4 类关键词）
├─ llm_analyzer.py    DeepSeek LLM 分析 + 本地规则回退
├─ report_generator.py Markdown 报告生成（支持嵌入可视化图片）
├─ ansys_runner.py    PyMAPDL 封装（.inp/.dat/.mac + 模板仿真 + 后处理）
├─ mechanical_runner.py PyMechanical 242+ 批量接触
├─ simulation_templates.py  预定义仿真模板（悬臂梁 / 带孔板 / 粘弹性盘）
└─ post_processor.py  PyVista 离屏云图 + matplotlib 应力曲线 + stdio 保护
```

核心链路：`日志 → 错误检测 → LLM分析 → Markdown报告`

扩展链路：`模板参数 → APDL生成 → MAPDL求解 → 后处理可视化 → Markdown嵌入`

## 常用命令

```bash
# 启动服务
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 仅安装核心依赖
pip install -r requirements.txt

# 可选：安装 Mechanical 支持
pip install -r requirements-mechanical.txt

# 测试日志分析
curl -X POST http://127.0.0.1:8000/analyze-log \
  -H "Content-Type: application/json" \
  -d '{"log_path": "D:\\ansysagent\\sample_logs\\demo_solver.out"}'
```

## 关键约定

- **两阶段设计**：所有执行端点默认 preview 模式，需显式传 `launch_*=true` 才真实启动求解器
- **运行时目录重定向**：PyMAPDL/PyMechanical 的 `LOCALAPPDATA` 被重定向到 `runtime_data/`，避免 C 盘权限问题
- **LLM 回退**：无 API Key 时自动降级到本地规则分析（覆盖奇异矩阵、不收敛、接触穿透三类）
- **环境变量**：统一由 `.env` 管理，通过 `python-dotenv` 加载
- **日志文件优先级**：`.out > .log > .err`，过滤隐藏文件和临时文件
- **Windows 路径**：默认 ANSYS 安装路径在 `D:\ANSYS Inc\v241\`

## 模块职责边界

| 模块 | 职责 | 禁止 |
|------|------|------|
| `main.py` | 路由、请求校验、模块串联 | 不写业务逻辑 |
| `log_parser.py` | 正则匹配 + 日志截取 | 不调用外部服务 |
| `llm_analyzer.py` | LLM 调用 + 回退规则 | 不读写文件 |
| `report_generator.py` | Markdown 拼装 + 落盘 | 不分析、不调用 API |
| `ansys_runner.py` | MAPDL 生命周期管理 + 模板仿真 + 后处理调度 + 环境诊断 | 不分析日志 |
| `mechanical_runner.py` | Mechanical 批量接触 | 不处理 MAPDL |
| `simulation_templates.py` | 预定义模板 APDL 命令生成 | 不调用求解器 |
| `post_processor.py` | PyVista 云图 + matplotlib 曲线 + stdio 保护 | 不管理 MAPDL 生命周期 |

## 扩展错误检测

在 `log_parser.py` 的 `ERROR_PATTERNS` 字典中添加：
```python
"new_error": {
    "pattern": r"your\s+regex\s+pattern",
    "title": "错误中文标题",
    "description": "该错误的工程含义。",
}
```

## 环境要求

- Python 3.11+
- Windows + ANSYS 241+（PyMAPDL 真实执行需要）
- ANSYS 242+（PyMechanical 批量接触需要）
- LLM API Key（可选，无 Key 时回退本地规则）

## LLM 多提供商支持

`llm_analyzer.py` 现已支持任意 OpenAI 兼容接口的 LLM 提供商：

| 提供商 | provider ID | 默认 base_url | 默认 model |
|--------|-------------|---------------|------------|
| DeepSeek | `deepseek` | `https://api.deepseek.com` | `deepseek-v4-pro` |
| Kimi (Moonshot) | `kimi` | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| Claude (Anthropic) | `claude` | `https://api.anthropic.com/v1` | `claude-sonnet-4-20250514` |
| OpenAI | `openai` | `https://api.openai.com/v1` | `gpt-4o` |
| Local (Ollama/vLLM) | `local` | `http://localhost:11434/v1` | `qwen2.5` |
| Custom | `custom` | 需手动配置 | 需手动配置 |

### 配置方式（优先级从高到低）

```env
# 方式 1：推荐 — 统一变量（切换提供商时只需改 provider）
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-pro

# 方式 2：兼容旧版 — DEEPSEEK_* / OPENAI_* 变量
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
```

当同时存在方式 1 和方式 2 时，**LLM_* 优先级更高**。

### 常用配置示例

**Kimi (Moonshot)**：
```env
LLM_PROVIDER=kimi
LLM_API_KEY=sk-你的-moonshot-key
```

**本地 Ollama**：
```env
LLM_PROVIDER=local
LLM_API_KEY=ollama  # Ollama 可填任意值
LLM_MODEL=llama3.1
```

**Claude (通过中转/兼容接口)**：
```env
LLM_PROVIDER=claude
LLM_API_KEY=sk-你的-key
```

**自定义兼容接口**：
```env
LLM_PROVIDER=custom
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://your-custom-endpoint.com/v1
LLM_MODEL=your-model-name
```

### 运行时切换

`/health` 端点会返回当前生效的 `provider`、`model` 以及 `supported_providers` 列表，方便在界面或日志中确认当前使用的 LLM。

## MCP 服务器

本项目注册了 3 个 MCP 服务器（配置见 `.mcp.json`）：

| MCP Server | 工具 | 用途 |
|-----------|------|------|
| `ansys-local` | `mapdl_status`, `mapdl_execute`, `mapdl_demo`, `mechanical_status`, `mechanical_batch_contact`, `run_template_simulation`, `postprocess_visualization` | PyMAPDL/PyMechanical 执行、模板仿真、后处理可视化 |
| `deepseek` | `chat_completion`, `completion`, `get_user_balance` | DeepSeek V4 LLM 分析（与 llm_analyzer.py 共用 API Key） |
| `filesystem` | 文件读写 (MCP 标准) | 安全访问工作目录：sample_inputs, sample_logs, ansys_workspace, reports |

**何时使用 MCP vs REST API:**
- MCP: 当用户直接在 Claude Code 对话中操作，MCP 工具更直接（Claude → Python 模块，无 HTTP 中转）
- REST API: 当外部系统/脚本需要调用，或需要 FastAPI 的 OpenAPI 文档和类型校验

## 预定义仿真模板

`simulation_templates.py` 提供 3 种参数化模板：

| 模板类型 | 描述 | 网格策略 | 分析类型 |
|---------|------|---------|---------|
| `cantilever` | 悬臂梁弯曲 | 映射六面体 (SOLID185) | 静力 |
| `plate_with_hole` | 带孔平板应力集中 | 自由四面体，孔边加密 | 静力 |
| `viscoelastic_disk` | 粘弹性圆盘压缩 | 映射六面体 | 瞬态 |

所有模板支持 JSON 参数覆盖，例如：
```json
{
  "template_type": "cantilever",
  "params": {"length": 1.5, "force_y": -2000.0, "mesh_size": 0.02},
  "launch_mapdl": true
}
```

## 后处理可视化

`post_processor.py` 提供（均使用离屏渲染，无需显示服务器）：

- **应力云图**：PyVista 绘制 Von Mises 应力云图，保存为 PNG
- **位移云图**：PyVista 绘制合位移云图，保存为 PNG
- **应力曲线**：沿几何路径提取应力值，matplotlib 绘制曲线，导出 PNG + JSON
- **stdio 保护**：在 MCP stdio 模式下自动重定向 `sys.stdout → sys.stderr`，防止 JSON-RPC 污染

## 环境诊断增强

`/mapdl-status` 现在额外返回：
- `license_service`: ANSYS License Manager CVD 服务运行状态
- `post_processing`: PyVista / matplotlib / numpy / ansys-tools-visualization-interface 导入状态

## Skills 目录

### `.claude/skills/` — CAE 领域 Skills

| Skill | 描述 | 触发方式 |
|-------|------|---------|
| `check-ansys-env` | 检查 LLM + PyMAPDL + PyMechanical 完整环境 | `/check-ansys-env` |
| `run-log-analysis` | 分析 ANSYS 求解日志，检测错误 + LLM 诊断 + 报告 | `/run-log-analysis` |
| `run-mapdl-input` | 执行 .inp/.dat/.mac 输入文件并可选自动分析 | `/run-mapdl-input` |
| `batch-contact` | 按 Named Selection 前缀批量创建接触对（242+） | `/batch-contact` |
| `git-workflow` | Git 提交/推送/PR 全流程自动化 + 程序化流水线 | `/git-workflow` |

### `.reasonix/skills/` — 通用/元 Skills（来自 obsidian_stack 融合）

| Skill | 描述 | 触发方式 |
|-------|------|---------|
| `skill-generator` | 读取 Fable5 知识库，自动生成专业 Skill | `/skill-generator` |
| `meeting-notes-organizer` | 会议对话 → 结构化 Markdown 笔记 | `/meeting-notes-organizer` |

## 知识库 (knowledge-base/)

知识库内容按项目颜色分类，详见 [INDEX.md](knowledge-base/INDEX.md) 和 [项目颜色注册表](knowledge-base/projects/project-registry.md)。Obsidian 笔记功能总结见 [obsidian-note-system.md](knowledge-base/obsidian-note-system.md)。

```
.claude/
├── skills/                       🎯 CAE 领域 + 通用 Skills（6 个）
├── workflows/                    🔧 程序化工作流（git-workflow.js）
knowledge-base/
├── INDEX.md                     🔍 颜色分类全景索引
├── obsidian-note-system.md      📝 Obsidian 笔记系统功能总览
├── projects/
│   └── project-registry.md      🎨 项目颜色注册表（5 项目 → 色值映射）
├── prompts/fable5/              ⚪ Fable5 提示词工程模板（跨项目通用）
│   ├── fable5-modules.md        10 大行为模块拆解 (M1-M9)
│   └── fable5-full-prompt.md    完整系统提示词参考
├── templates/
│   └── skill-template.md        Skill 构造模板 (M0-M10, 含项目颜色 M0)
├── domain-knowledge/            🔵 CAE 领域知识积累
│   └── contact-analysis-best-practices.md
└── skills-output/               生成的 Skill 备份（按项目颜色标记）
```

**项目颜色速查：** 🔵 `cae-agent` | 🟢 `reasonix` | 🟣 `obsidian-stack` | 🟠 `ansys-tools` | ⚪ `fable5`

`book/v241/` 目录存放 ANSYS v241 官方 PDF 手册（100+ 本），可通过 Read 工具直接查阅。

## 工具使用指引

- 读取 ANSYS 手册 → `Read` 工具读取 `book/v241/` 中的 PDF（20 页/次）
- 执行 MAPDL → `mcp__ansys-local__mapdl_execute` 或 `POST /run-mapdl-input`
- LLM 分析日志 → `mcp__deepseek__chat_completion` 或 `POST /analyze-log`
- 文件操作 → `mcp__filesystem__*` 或 `Read`/`Write`/`Edit` 工具
- 启动服务 → `bash("uvicorn main:app --reload --host 0.0.0.0 --port 8000")`
- 生成新 Skill → `/skill-generator` 读取知识库自动生成
