# CLAUDE.md — cae-agent

面向 ANSYS 场景的最小可运行 CAE 智能辅助系统。

## 架构概览

```
main.py          FastAPI 入口，35 个 REST 端点，组装层
├─ paths.py          项目根锚定（所有文件系统默认路径的唯一来源，禁止相对 CWD）
├─ ansys_discovery.py  求解器发现（跨版本 v* glob + 跨平台 Windows/Linux/macOS）
├─ log_parser.py      日志解析 + 错误/警告正则模式库 + 诊断块解析
├─ analysis_pipeline.py  统一诊断链路（检测→证据合并→LLM→报告），LLM 单例
├─ llm_analyzer.py    多提供商 LLM 分析 + 本地规则回退 + 观测事件记录
├─ report_generator.py Markdown 报告生成（支持嵌入可视化图片与证据章节）
├─ ansys_runner.py    PyMAPDL 封装（.inp/.dat/.mac + 模板仿真 + 后处理）
├─ mechanical_runner.py PyMechanical（版本下限 242+，批量接触 / 脚本 / 模板 / 图片导出）
├─ mechanical_post_processor.py  Mechanical 云图导出与结果提取脚本生成
├─ simulation_templates.py  预定义仿真模板（悬臂梁 / 带孔板 / 粘弹性盘）
├─ post_processor.py  PyVista 离屏云图 + matplotlib 应力曲线 + stdio 保护
├─ solve_watcher.py   流式证据监视器（跨进程文件跟随 + 块解析 + 去重计数）
├─ folder_monitor.py  被动项目监听（有界递归 + 稳定触发 + 静默退避）
├─ job_manager.py     异步任务管理（监督者线程、超时强杀、取消、状态持久化）
├─ observability.py   运行事件环形缓冲 + JSONL 落盘（仪表盘数据源）
└─ knowledge_bridge.py  工程经验 / 报告摘要推送 Obsidian 知识库
```

核心链路：`日志 → 错误检测 → LLM分析 → Markdown报告`

扩展链路：`模板参数 → APDL生成 → MAPDL求解 → 流式证据采集 + 后处理可视化 → Markdown嵌入`

## 常用命令

```bash
# 启动服务
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 仅安装核心依赖
pip install -r requirements.txt

# 可选：安装 Mechanical 支持
pip install -r requirements-mechanical.txt

# 测试日志分析（路径用 clone 后的绝对路径，Windows 建议正斜杠）
curl -X POST http://127.0.0.1:8000/analyze-log \
  -H "Content-Type: application/json" \
  -d '{"log_path": "<项目根>/sample_logs/demo_solver.out"}'
```

## 关键约定

- **跨机器路径**：所有文件系统默认路径经 `paths.project_path()` 锚定项目根，禁止相对 CWD 与硬编码盘符；机器专属配置走环境变量（`.env`）
- **跨版本探测**：求解器发现一律走 `ansys_discovery`（v* 目录 glob，版本降序取最新）；Mechanical 按 `MIN_MECHANICAL_VERSION=242` 下限判断而非白名单；新增平台支持先改 discovery
- **平台分级**：Windows 全功能；Linux MAPDL 标准位置探测（best effort）；macOS 日志分析模式（求解需显式路径）；平台分支只允许出现在 ansys_discovery 内
- **两阶段设计**：所有执行端点默认 preview 模式，需显式传 `launch_*=true` 才真实启动求解器
- **LLM 回退**：无 API Key 时自动降级到本地规则分析（覆盖奇异矩阵、不收敛、接触穿透三类）
- **环境变量**：统一由项目根 `.env` 管理（`load_dotenv(PROJECT_ROOT/".env")`）
- **日志文件优先级**：`.out > .log > .err`，过滤隐藏文件和临时文件

## 证据协议（solve_watcher / job_manager）

- **证据宿主解耦**：证据由跨进程文件跟随的 watcher + JSONL 落盘（`runtime_data/evidence/{run_id}.jsonl`）持有，与求解器返回值无关——超时/被杀场景证据照常返回
- **事件流 + 尾部快照并存**：`error_events/warning_events`（为什么死）与 `log_tail`（死在哪）同时进入证据包与报告
- **块级捕获 + 签名去重**：`*** WARNING/ERROR ***` 块头行首可能有缩进、换行为 `\r\n`（解析层已归一化）；同签名跨 substep 重复只计数，未归类块保留前 3 条样本
- **失败也出分析**：job 成功与失败/超时都跑 `analysis_pipeline`，失败场景用证据 + 日志尾部驱动 LLM 诊断
- **模式库驱动建议**：`ERROR_PATTERNS`/`WARNING_PATTERNS` 每条可带 `suggestion` 字段，命中即随证据返回给 LLM（自修正协议）
- **观测事件**：`llm_analyzer.analyze` 的包装方法统一记录 prompt/响应预览到 `observability`；仪表盘 `/dashboard/api/all` 增量拉取
- **分级实时**：活动 job 用 1s watcher；被动项目监听（`folder_monitor`）默认 5s + 静默退避（10 分钟无变化间隔翻倍至 60s 上限）+ 稳定触发（文件 10s 无增长或出现 ROUTINE COMPLETED 才标记可分析）——读取便宜、LLM 调用才贵，不追求高频率裸轮询
- **监听 LLM 触发**：人工优先（面板按钮 → `/monitor-analyze`），`auto_analyze` 开关默认关；稳定触发且发现错误才自动分析
- **运行时 LLM 配置**：`LLMAnalyzer.update_config()` 仅改内存与进程环境变量，不写 `.env`；Key 不回显，留空表示保持不变，重启后回到 `.env` 配置
- **监听暂停**：`FolderMonitor.set_paused` 只置标志（线程存活、不扫描不触发），暂停状态随 `monitors.json` 持久化

## 异步任务 API

- `POST /runs`（kind: mapdl_input/mapdl_demo/mapdl_template/mechanical_script/mechanical_template/mechanical_contact_batch）→ 202 返回 run_id
- `GET /runs/{run_id}` 全量详情（运行中含 `live_evidence` 实时快照）；`GET /runs` 轻量列表；`POST /runs/{run_id}/cancel` 取消
- 执行模型：ThreadPoolExecutor 监督者 + 嵌套求解 daemon 线程；超时经 `session_holder` 强杀会话；终态只落一次（`_try_finish` 防竞争）
- 任务状态持久化 `runtime_data/jobs/{run_id}.json`；并发上限 `CAE_JOB_MAX_WORKERS`（默认 2）
- 同步端点与 MCP 行为不变（session_holder 默认 None）

## 模块职责边界

| 模块 | 职责 | 禁止 |
|------|------|------|
| `main.py` | 路由、请求校验、模块串联 | 不写业务逻辑 |
| `paths.py` | 项目根锚定辅助 | 不含业务逻辑 |
| `ansys_discovery.py` | 跨版本/跨平台求解器发现 + 许可证 + 运行时目录 | 不启动求解器、不做分析 |
| `log_parser.py` | 正则匹配 + 日志截取 + 诊断块解析 | 不调用外部服务 |
| `llm_analyzer.py` | LLM 调用 + 回退规则 + 观测记录 | 不读写文件 |
| `analysis_pipeline.py` | 统一分析链路编排 + LLM 单例 | 不管理求解器 |
| `report_generator.py` | Markdown 拼装 + 落盘 | 不分析、不调用 API |
| `ansys_runner.py` | MAPDL 生命周期管理 + 模板仿真 + 后处理调度 + 环境诊断 | 不分析日志 |
| `mechanical_runner.py` | Mechanical 批量接触 + 会话句柄暴露 | 不处理 MAPDL |
| `mechanical_post_processor.py` | Mechanical 云图脚本生成 + 结果提取 | 不启动 Mechanical 会话 |
| `simulation_templates.py` | 预定义模板 APDL 命令生成 | 不调用求解器 |
| `post_processor.py` | PyVista 云图 + matplotlib 曲线 + stdio 保护 | 不管理 MAPDL 生命周期 |
| `solve_watcher.py` | 只读跟随日志文件 + 模式分类 + 证据落盘 | 不管理求解器生命周期 |
| `folder_monitor.py` | 项目目录监听 + 错误事件 + 稳定触发回调 | 不直接调用 LLM（经 Manager 回调） |
| `job_manager.py` | 任务调度 + 超时/取消 + 证据收尾 | 不实现求解逻辑 |
| `observability.py` | 事件缓冲 + 落盘 + 语义化记录函数 | 不做业务判断 |
| `knowledge_bridge.py` | 知识库推送桥接（Obsidian） | 不做分析判断 |

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

- Python 3.11+（`main.py` 启动时强制校验）
- 任意操作系统：Windows / Linux / macOS（平台能力差异见 README「平台支持矩阵」）
- ANSYS 安装（可选）：MAPDL 版本不限（自动发现最新版）用于真实求解；PyMechanical 需 242+（批量接触 / 脚本 / 模板）。未安装时除求解端点外全部可用
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
| `ansys-local` | `mapdl_status`, `mapdl_execute`, `mapdl_demo`, `mechanical_status`, `mechanical_batch_contact`, `mechanical_run_script`, `mechanical_extract_results`, `mechanical_export_image`, `mechanical_diagnose`, `log_analyze`, `health_check` | PyMAPDL / PyMechanical 执行、批量接触、结果提取、云图导出、日志诊断（实现见 `.claude/mcp-servers/ansys-mcp/server.py`） |
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

## Skills（`skills/` 目录）

项目 Skills 存放在 `skills/`（13 个），生命周期由 [AGENTS.md](AGENTS.md) 约定：结构、哈希与提交状态在 pre-push 时经 `.skills/skill_lifecycle.py verify-project` 校验。入口索引见 [skills/INDEX.md](skills/INDEX.md)。

| Skill | 用途 |
|-------|------|
| `knowledge-driven-skill-sync` | Skill 知识同步与生命周期管理 |
| `check-ansys-env` | LLM + PyMAPDL + PyMechanical 环境自检 |
| `run-log-analysis` | 求解日志错误检测 + LLM 诊断 + 报告 |
| `run-mapdl-input` | 执行 .inp/.dat/.mac 并可选串联分析 |
| `batch-contact` | 按 Named Selection 前缀批量建接触对（242+） |
| `meeting-notes-organizer` | 会议对话 → 结构化 Markdown 笔记 |
| `code-debugger` | 结构化缺陷定位与最小修复 |
| `git-workflow` | 提交 / 推送 / PR 流程 |
| `pre-push-review` | 推送前只读评审门禁 |
| `pull-audit` | 拉取 / 同步前的变更审计 |
| `cross-agent-audit` | 跨 Agent 产出交叉审计 |
| `skill-creator-fable5` | 按 Fable5 结构生成新 Skill |
| `fable5-code-principle` | Fable5 代码原则检查 |

> 各 SKILL.md 中引用的 `references/knowledge.md` 由 `python .skills/skill_lifecycle.py pull-knowledge --skill <name>` 按需生成：仓库里只有 `knowledge-driven-skill-sync` 自带该文件，其余出现属正常生成结果。

## 知识库与本地资料

仓库内 `knowledge-base/` 只保留可公开的通用知识：

```
knowledge-base/
└── domain-knowledge/
    ├── contact-analysis-best-practices.md   # 接触算法 / 刚度 / 排查清单
    └── code-architecture-graphify.md        # Graphify 代码架构图谱分析
```

以下资料仅存在于维护者本机工作区（已列入 `.gitignore`，不随仓库发布）：`knowledge-base/INDEX.md`、`knowledge-base/obsidian-note-system.md`、`knowledge-base/projects/`（项目颜色注册表）、`knowledge-base/prompts/fable5/`、`knowledge-base/templates/`、`knowledge-base/skills-output/`、`book/v241/`（ANSYS 官方 PDF 手册）。引用这些路径前请先确认本机存在。

## 工具使用指引

- 读取 ANSYS 手册 → 本机 `book/v241/`（未入库）的 PDF 用 Read 工具分页读取
- 执行 MAPDL → `mcp__ansys-local__mapdl_execute` 或 `POST /run-mapdl-input`
- LLM 分析日志 → `mcp__deepseek__chat_completion` 或 `POST /analyze-log`
- 文件操作 → `mcp__filesystem__*` 或 `Read`/`Write`/`Edit` 工具
- 启动服务 → `python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000`
- 生成新 Skill → `skill-creator-fable5` 按 Fable5 结构生成
