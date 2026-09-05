# cae-agent

面向 ANSYS 场景的 LLM 智能辅助 CAE 系统：用 FastAPI 串联 **求解器自动化（PyMAPDL / PyMechanical）+ 日志错误检测 + LLM 诊断 + Markdown 报告 + 后处理可视化**，形成从"提交仿真"到"拿到带图报告"的闭环。

## 核心特性

- **求解器自动化**：封装 PyMAPDL 执行 `.inp/.dat/.mac` 输入文件与内置示例；封装 PyMechanical（242+）执行脚本、批量创建接触对
- **参数化仿真模板**：内置悬臂梁 / 带孔板 / 粘弹性圆盘 3 个 MAPDL 模板和悬臂梁 / 模态分析 2 个 Mechanical 模板，JSON 参数即可覆盖几何、材料、网格、载荷
- **两阶段安全设计**：所有执行端点默认仅预览生成的 APDL / Mechanical 脚本，显式传 `launch_*=true` 才真实启动求解器
- **智能日志诊断**：正则检测常见求解错误（奇异矩阵、不收敛、接触穿透、许可证等），调用 LLM 生成原因分析与修改建议；无 API Key 时自动回退本地规则分析
- **流式诊断证据**：`SolverOutputWatcher` 求解期间实时跟随工作目录的 `*.out/*.err`，块级捕获 WARNING/ERROR、去重计数、JSONL 落盘——失败与超时场景证据依然完整可返回
- **异步任务 API**：`POST /runs` 提交即返回 run_id，轮询获取状态、实时证据与诊断报告；支持超时强杀与手动取消
- **运行监控仪表盘**：内置 Web 界面（`/dashboard`），可视化 LLM 接口输入/响应、日志错误检测流、任务实时证据、环境状态与报告列表
- **后处理可视化**：PyVista 离屏绘制应力 / 位移云图，matplotlib 沿路径提取应力曲线；Mechanical 侧可导出云图 PNG 与结果数据
- **报告自动生成**：检测结果、LLM 分析、工程结果与可视化图片统一拼装为 Markdown 报告，按时间戳落盘 `reports/`
- **MCP 服务器**：提供 `ansys-local` MCP，可在 Claude Code 等 Agent 中直接调用 MAPDL / Mechanical / 日志分析能力
- **知识沉淀**：`knowledge_bridge.py` 可将仿真经验与报告摘要推送至 Obsidian 知识库

## 架构总览

```
main.py                 FastAPI 入口（26 个端点，路由 + 模块串联，无业务逻辑）
├─ 分析链路
│  ├─ log_parser.py         日志读取 + 正则错误/警告模式库 + 诊断块解析
│  ├─ analysis_pipeline.py  统一诊断链路（检测→证据合并→LLM→报告），LLM 单例
│  ├─ llm_analyzer.py       多提供商 LLM 分析 + 本地规则回退 + 观测事件记录
│  └─ report_generator.py   Markdown 报告拼装与落盘（支持嵌入图片 / 证据章节）
├─ MAPDL 求解链路
│  ├─ ansys_runner.py       PyMAPDL 生命周期管理、环境诊断、输入文件执行、模板调度
│  ├─ simulation_templates.py  参数化模板 → APDL 命令生成（悬臂梁/带孔板/粘弹性盘）
│  └─ post_processor.py     PyVista 离屏云图 + matplotlib 应力曲线 + stdio 保护
├─ Mechanical 求解链路
│  ├─ mechanical_runner.py  PyMechanical 脚本执行、批量接触、模板、图片导出
│  └─ mechanical_post_processor.py  Mechanical 云图导出 / 结果提取脚本生成
├─ 异步任务与观测
│  ├─ solve_watcher.py      流式证据监视器（跨进程文件跟随 + 块解析 + 去重计数）
│  ├─ job_manager.py        异步任务管理（监督者线程、超时强杀、取消、状态持久化）
│  └─ observability.py      运行事件环形缓冲 + JSONL 落盘（仪表盘数据源）
└─ 知识沉淀
   └─ knowledge_bridge.py   工程经验 / 报告摘要推送 Obsidian 知识库

static/dashboard.html    运行监控仪表盘（单文件原生 JS，/dashboard 托管）
```

两条核心链路：

```
诊断链路：日志(.out/.log/.err) → 错误检测 → LLM 分析(可回退) → Markdown 报告
仿真链路：模板参数/APDL → MAPDL|Mechanical 求解 → 流式证据采集 + 日志诊断 + 后处理云图 → 带图报告
```

## 目录结构

```text
AI-ansys/
├─ main.py                    # FastAPI 入口
├─ log_parser.py              # 日志解析 + 错误/警告模式库 + 诊断块解析
├─ llm_analyzer.py            # LLM 分析 + 本地回退 + 观测事件
├─ analysis_pipeline.py       # 统一诊断链路（检测→证据合并→LLM→报告）
├─ report_generator.py        # Markdown 报告生成（含证据章节）
├─ ansys_runner.py            # PyMAPDL 封装
├─ simulation_templates.py    # MAPDL 参数化仿真模板
├─ post_processor.py          # PyVista/matplotlib 后处理可视化
├─ mechanical_runner.py       # PyMechanical 封装
├─ mechanical_post_processor.py  # Mechanical 后处理脚本生成
├─ solve_watcher.py           # 流式证据监视器（含自测）
├─ folder_monitor.py          # 被动项目监听（有界递归/稳定触发/静默退避，含自测）
├─ job_manager.py             # 异步任务管理（超时/取消/持久化）
├─ observability.py           # 运行事件缓冲与落盘
├─ knowledge_bridge.py        # Obsidian 知识库桥接
├─ static/dashboard.html      # 运行监控仪表盘页面
├─ .env.example               # 环境变量模板
├─ .mcp.json                  # MCP 服务器配置（filesystem / deepseek / ansys-local）
├─ requirements.txt           # 核心依赖
├─ requirements-mechanical.txt# Mechanical 可选依赖
├─ .claude/mcp-servers/       # ansys-local MCP 服务器实现
├─ scripts/                   # 悬臂梁基准验证与报告生成脚本
├─ skills/                    # 项目托管 Skills（见 AGENTS.md）
├─ docs/                      # 真机验证记录等文档
├─ sample_inputs/             # 示例输入文件（.inp 等）
├─ sample_logs/               # 示例求解日志
├─ reports/                   # 报告与可视化输出目录
└─ runtime_data/              # 求解器运行时目录 / 证据 journal / 任务状态
```

## 环境要求

- Python 3.11+
- Windows + ANSYS 241+（PyMAPDL 真实求解需要；仅预览 / 日志分析无需 ANSYS）
- ANSYS 242+（PyMechanical 批量接触与模板需要，可选）
- LLM API Key（可选，无 Key 时回退本地规则分析）

## 安装

```bash
# 核心依赖（FastAPI + PyMAPDL + 可视化）
pip install -r requirements.txt

# 可选：Mechanical 242+ 支持
pip install -r requirements-mechanical.txt
```

核心依赖：`fastapi`、`uvicorn`、`openai`（用于调用任意 OpenAI 兼容 LLM）、`ansys-mapdl-core`、`python-dotenv`、`pyvista`、`matplotlib`、`numpy`、`ansys-tools-visualization-interface`。

## 配置

复制 `.env.example` 为 `.env`，按需修改。

### LLM 配置（支持多提供商）

```env
# 提供商：deepseek | kimi | claude | openai | local | custom
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-xxxxxxxx
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-pro
```

| 提供商 | LLM_PROVIDER | 默认接口地址 | 默认模型 |
|--------|-------------|-------------|---------|
| DeepSeek | `deepseek` | `https://api.deepseek.com` | `deepseek-v4-pro` |
| Kimi (Moonshot) | `kimi` | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| Claude | `claude` | 需兼容接口 | `claude-sonnet-4-20250514` |
| OpenAI | `openai` | `https://api.openai.com/v1` | `gpt-4o` |
| 本地模型 (Ollama/vLLM) | `local` | `http://localhost:11434/v1` | `qwen2.5` |
| 自定义 | `custom` | 需手动填写 | 需手动填写 |

兼容旧版 `DEEPSEEK_*` / `OPENAI_*` 变量；同时存在时 `LLM_*` 优先。所有 Key 留空时系统仍可运行，LLM 分析回退到本地规则模式（覆盖奇异矩阵、不收敛、接触穿透三类）。

### ANSYS 路径配置

```env
ANSYS241_DIR=D:\ANSYS Inc\v241\ANSYS     # 优先定位 MAPDL.exe
AWP_ROOT241=D:\ANSYS Inc\v241            # 安装根目录备用定位
ANSYSLIC_DIR=D:\ANSYS Inc\Shared Files\Licensing
MECHANICAL_EXEC=                          # 242+ 自动探测失败时手动指定
MAPDL_EXECUTABLE=                         # MAPDL 可执行文件手动指定
```

PyMAPDL / PyMechanical 的运行期用户目录会自动重定向到项目内 `runtime_data/`，避免 `C:\Users\...\AppData\Local` 无写权限导致导入失败。

## 启动服务

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- `http://127.0.0.1:8000/docs` — Swagger 接口文档
- `http://127.0.0.1:8000/health` — 健康检查（LLM 配置与连通性）
- `http://127.0.0.1:8000/dashboard` — 运行监控仪表盘

## REST API 一览

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/` | 服务信息 |
| GET | `/health` | 健康检查（LLM 状态，5 分钟缓存） |
| GET | `/mapdl-status` | PyMAPDL 环境诊断（可执行文件、许可证服务、后处理依赖） |
| GET | `/ansys-demo` | 内置 APDL 示例预览（不启动求解器） |
| POST | `/run-ansys-demo` | 运行内置 LINK180 拉杆示例 |
| POST | `/run-mapdl-input` | 执行 `.inp/.dat/.mac`，自动收集日志并可选串联诊断 |
| GET | `/templates` | 列出 MAPDL 仿真模板 |
| GET | `/templates/{template_type}` | 模板详情与默认参数 |
| POST | `/run-template-simulation` | 参数化模板仿真（悬臂梁 / 带孔板 / 粘弹性盘） |
| POST | `/postprocess-visualization` | 对已有结果文件生成云图 / 应力曲线 |
| POST | `/analyze-log` | 分析日志文件或文本 → 错误检测 + LLM + 报告 |
| POST | `/runs` | 提交异步求解任务（6 种 kind），立即返回 run_id |
| GET | `/runs` | 列出最近任务（轻量视图） |
| GET | `/runs/{run_id}` | 任务详情：状态、结果、流式证据、诊断报告；运行中含实时快照 |
| POST | `/runs/{run_id}/cancel` | 取消任务（强杀求解会话，证据照常返回） |
| POST | `/monitors` | 创建项目监听 `{path, interval?, depth?, auto_analyze?}` |
| GET | `/monitors` | 监听列表（文件数/事件计数/退避状态） |
| DELETE | `/monitors/{monitor_id}` | 停止并移除监听 |
| POST | `/monitors/{monitor_id}/auto-analyze` | 切换自动分析开关 |
| POST | `/monitors/{monitor_id}/pause` | 暂停/恢复监听（暂停期间不扫描不触发，配置保留） |
| POST | `/monitor-analyze` | 人工触发：对监听文件执行 LLM 诊断 |
| GET | `/fs/browse` | 只读目录浏览（子目录 + 求解日志计数），供前端选择项目 |
| POST | `/llm/config` | 运行时更新 LLM 配置（Key/提供商/模型/地址；仅内存生效） |
| POST | `/llm/test` | LLM 连通性强刷测试 |
| GET | `/dashboard` | 运行监控仪表盘页面 |
| GET | `/dashboard/api/all` | 仪表盘聚合轮询：状态 + 增量事件 + 任务 + 监听 + 报告 |
| GET | `/reports/{filename}` | 查看 reports 目录中的报告文件 |
| GET | `/mechanical-status` | PyMechanical 环境诊断 |
| GET | `/mechanical-capabilities` | Mechanical 能力说明 |
| POST | `/mechanical-contact-batch-plan` | 批量接触方案预览（Named Selection 前缀配对） |
| POST | `/mechanical-contact-batch-execute` | 真实执行批量接触（需 242+） |
| POST | `/mechanical-run-script` | 在 Mechanical 中执行自定义 Python 脚本 |
| POST | `/mechanical-extract-results` | 提取应力 / 位移 / 模态频率等结果数据 |
| POST | `/mechanical-export-image` | 导出应力 / 位移云图 PNG |
| POST | `/mechanical-run-template` | Mechanical 模板仿真（cantilever_beam / modal_analysis） |

### 常用示例

**日志诊断**（支持文件路径或直接传文本）：

```bash
curl -X POST http://127.0.0.1:8000/analyze-log \
  -H "Content-Type: application/json" \
  -d '{"log_path": "D:\\Projects\\AI-ansys\\sample_logs\\demo_solver.out"}'
```

**执行 MAPDL 输入文件**（求解后自动收集日志并生成诊断报告）：

```bash
curl -X POST http://127.0.0.1:8000/run-mapdl-input \
  -H "Content-Type: application/json" \
  -d '{
    "input_file_path": "D:\\Projects\\AI-ansys\\sample_inputs\\bar_example.inp",
    "analyze_after_run": true
  }'
```

**参数化模板仿真**（先预览 APDL，确认后真实求解）：

```bash
# 第一步：预览生成的 APDL 命令
curl -X POST http://127.0.0.1:8000/run-template-simulation \
  -H "Content-Type: application/json" \
  -d '{"template_type": "cantilever", "params": {"length": 1.5, "force_y": -2000.0}}'

# 第二步：真实求解
curl -X POST http://127.0.0.1:8000/run-template-simulation \
  -H "Content-Type: application/json" \
  -d '{"template_type": "cantilever", "launch_mapdl": true, "run_postprocess": true}'
```

**批量接触预览**（`NS_SRC_BOLT_01` + `NS_TGT_BOLT_01` → `AUTO_CONTACT_BOLT_01`）：

```bash
curl -X POST http://127.0.0.1:8000/mechanical-contact-batch-plan \
  -H "Content-Type: application/json" \
  -d '{"source_named_selection_prefix": "NS_SRC_", "target_named_selection_prefix": "NS_TGT_"}'
```

**异步任务**（提交后轮询，运行中可在 `/dashboard` 看实时证据）：

```bash
# 提交：立即返回 run_id
curl -X POST http://127.0.0.1:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"kind": "mapdl_input", "params": {"input_file_path": "D:\\Projects\\AI-ansys\\sample_inputs\\bar_example.inp"}, "timeout_seconds": 600}'

# 轮询：状态、结果、流式证据（事件表 + 日志尾部 + journal 路径）与诊断报告
curl http://127.0.0.1:8000/runs/{run_id}
```

## 运行监控仪表盘

启动服务后访问 [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard)：

- **状态卡片**：LLM 配置与连通性、MAPDL 环境（可执行文件/许可证/后处理依赖）、Mechanical 环境、任务统计；LLM 卡片支持**一键连通测试**、**配置 Key**（运行时更新提供商/模型/接口地址/API Key，仅本次运行生效）与**选文件发起 LLM 分析**（浏览对话框选择文件，就地展示错误列表、分析摘要与报告链接）
- **项目监听面板**：选择项目目录（支持服务端目录浏览）后添加监听，服务自动有界递归跟踪求解日志；面板展示各监听的文件数、错误/警告事件、未归类统计，可切换"发现错误自动 LLM 分析"开关（默认关）
- **求解任务面板**：任务列表与状态徽章，展开可见参数、证据事件表（代码/次数/建议）、日志尾部快照；运行中任务显示实时采集进度并支持取消
- **LLM 接口调用流**：每次分析的来源、模式（LLM/规则/回退）、延迟，可展开 Prompt 输入与响应原文
- **日志读取与错误检测流**：来源、命中错误代码、监听发现的诊断块（`monitor_event`），可跳转诊断报告
- **报告列表**：`reports/` 目录文件，在线查看

仪表盘数据由 `observability.py` 事件流驱动（环形缓冲 + JSONL 落盘，进程重启后历史可回放），默认 5s 轮询可调。

## 项目监听与实时性分级

监听流程的实时性按场景分级，**不追求无差别的高频率轮询**：

| 场景 | 频率 | 说明 |
|------|------|------|
| 活动 job 求解中 | 1s | 求解生命周期内、目录小，高实时有价值（`solve_watcher`） |
| 被动项目监听 | 5s 可配 | 人看面板与触发式 LLM 均无感知差异（`folder_monitor`） |
| 监听静默退避 | 最长 60s | 目录 10 分钟无变化自动拉长间隔，有活动立即恢复 |

读取本身便宜，**昂贵的动作是 LLM 调用**——因此监听采用**稳定触发**：文件停止增长 10s（或出现 `ROUTINE COMPLETED` 终止标记）才标记"可分析"，避免对半截日志反复分析。发现错误后：

- 默认**人工触发**：监听卡片/LLM 卡片的"分析日志"按钮选文件分析
- 可选**自动开关**：每个监听独立开启，文件稳定且发现错误时自动调 LLM 并生成报告（报告路径进事件流）
- 支持**暂停/恢复**：暂停期间不扫描不触发，配置与持久化保留，可即时恢复

监听配置持久化到 `runtime_data/monitors.json`（含暂停状态），服务重启后自动恢复。

## 异步任务与流式证据

| 任务类型 | kind | 参数 |
|---------|------|------|
| 执行 MAPDL 输入文件 | `mapdl_input` | `input_file_path`，可选 `working_directory` |
| 运行 MAPDL 示例 | `mapdl_demo` | 可选 `working_directory` |
| MAPDL 模板仿真 | `mapdl_template` | `template_type` + `template_params` |
| 执行 Mechanical 脚本 | `mechanical_script` | `script`，可选 `context`/`working_directory` |
| Mechanical 模板 | `mechanical_template` | `template_type` + `template_params` |
| Mechanical 批量接触 | `mechanical_contact_batch` | `source_named_selection_prefix` 等 |

机制要点：

- 提交即返回 run_id；求解运行在独立线程，监督者执行 `timeout_seconds` 超时强杀（复用会话句柄），取消走同一路径
- 求解期间 `SolverOutputWatcher` 跨进程跟随工作目录日志：块级捕获 `*** WARNING/ERROR ***`、按签名去重计数、未归类块保留样本，全部事件实时落盘 `runtime_data/evidence/{run_id}.jsonl`
- **失败与超时同样产出证据与 LLM 诊断**（用证据事件 + 日志尾部驱动），构成"失败 → 自诊断 → 修正重试"闭环的输入
- 任务状态持久化到 `runtime_data/jobs/{run_id}.json`；并发上限由 `CAE_JOB_MAX_WORKERS` 控制（默认 2）
- 已知限制：Mechanical 的求解输出目录由 PyMechanical 内部决定，监视器监视调用方目录并在无输出时按探测到的实际目录事后补扫

## 预定义仿真模板

MAPDL 模板（`simulation_templates.py`）：

| 模板类型 | 描述 | 网格策略 | 分析类型 |
|---------|------|---------|---------|
| `cantilever` | 悬臂梁弯曲，端部集中力 | 映射六面体 (SOLID185) | 静力 |
| `plate_with_hole` | 带孔平板应力集中，孔边加密 | 自由四面体 | 静力 |
| `viscoelastic_disk` | 粘弹性圆盘压缩（Prony 剪切松弛） | 映射六面体 | 瞬态 |

Mechanical 模板（`mechanical_runner.py` 内置）：`cantilever_beam`（悬臂梁静力）、`modal_analysis`（模态分析）。

所有模板的几何、材料、网格、载荷参数均可通过 `params` JSON 覆盖，默认参数可通过 `GET /templates/{template_type}` 查看。

## 后处理可视化

- **MAPDL 侧**（`post_processor.py`）：PyVista 离屏绘制 Von Mises 应力云图与合位移云图；沿几何路径采样应力并用 matplotlib 绘制曲线，导出 PNG + JSON；内置 stdio 保护，可在 MCP stdio 模式下安全调用
- **Mechanical 侧**（`mechanical_post_processor.py`）：生成 Mechanical 脚本导出 Equivalent Stress / Total Deformation 云图（1920×1080 PNG），并提取各结果对象的最大 / 最小值与模态频率

## MCP 服务器

`.mcp.json` 注册 3 个 MCP 服务器：

| MCP Server | 主要工具 | 用途 |
|-----------|---------|------|
| `ansys-local` | `mapdl_status` / `mapdl_execute` / `mapdl_demo` / `mechanical_status` / `mechanical_batch_contact` / `mechanical_run_script` / `mechanical_extract_results` / `mechanical_export_image` / `mechanical_diagnose` / `log_analyze` / `health_check` | 在 Agent 对话中直接执行 MAPDL / Mechanical / 日志诊断（实现见 `.claude/mcp-servers/ansys-mcp/`） |
| `deepseek` | `chat_completion` 等 | LLM 交互式诊断，与 `llm_analyzer.py` 共用 API Key |
| `filesystem` | MCP 标准文件读写 | 安全访问 `sample_inputs` / `sample_logs` / `reports` / `runtime_data` 等工作目录 |

选择建议：Agent 对话内操作用 MCP（无 HTTP 中转）；外部系统 / 脚本集成用 REST API（有 OpenAPI 文档与类型校验）。

## Skills

`skills/` 目录托管项目 Skills（CAE 领域 + 工程/审计流程），由 `AGENTS.md` 管理生命周期，包括 `check-ansys-env`（环境自检）、`run-log-analysis`（日志诊断）、`run-mapdl-input`（输入文件执行）、`batch-contact`（批量接触）、`git-workflow`、`pre-push-review` 等。使用方式与维护约定见 [AGENTS.md](AGENTS.md)。

## 扩展指南

**新增错误检测模式**：在 `log_parser.py` 的 `ERROR_PATTERNS` 字典中添加正则模式、中文标题与工程描述，诊断链路和报告自动生效。

**新增仿真模板**：在 `simulation_templates.py` 中实现参数 dataclass + `build_apdl()` 方法，并注册到 `TEMPLATE_REGISTRY`，`/templates` 系列端点自动暴露。

**模块职责边界**（详见 [CLAUDE.md](CLAUDE.md)）：`main.py` 只做路由与串联；`log_parser` 不调外部服务；`llm_analyzer` 不读写文件；`report_generator` 只拼装落盘；runner 层管理求解器生命周期但不分析日志。

## 验证与测试

- 示例日志：`sample_logs/demo_solver.out`，示例输入：`sample_inputs/bar_example.inp`
- 悬臂梁基准验证脚本：`scripts/validate_cantilever.py`、`scripts/generate_cantilever_report.py`、`scripts/generate_mechanical_report.py`
- 真机验证记录：[docs/real-host-cantilever-validation.md](docs/real-host-cantilever-validation.md)

## 后续路线

1. 扩展错误检测关键词库（疲劳、屈曲、单位不一致等）
2. 接入更多求解类型（热分析、屈曲、谐响应）
3. Mechanical 按面几何特征（圆柱面、平面）自动创建 Named Selections
4. 报告导出 Word / PDF 格式
5. 前端可视化界面

## 参考

- PyMAPDL 文档：https://mapdl.docs.pyansys.com/
- PyMechanical 文档：https://mechanical.docs.pyansys.com/
- DeepSeek API 文档：https://platform.deepseek.com/api-docs
- PyVista 文档：https://docs.pyvista.org/
