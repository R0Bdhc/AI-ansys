# 部署指南（跨机器）

本指南面向把 cae-agent 部署到一台新机器的完整流程。平台能力差异见 [README 平台支持矩阵](README.md#平台支持矩阵)。

## 1. 快速开始（5 步）

```bash
# 1) 安装 Python 3.11+（服务启动时强制校验）
# 2) 获取代码（仓库名 AI-ansys：clone 或解压发布包）
git clone https://github.com/R0Bdhc/AI-ansys.git
cd AI-ansys

# 3) 安装核心依赖（无 ANSYS 的机器也可安装，求解功能自动降级）
pip install -r requirements.txt
# 可选：Mechanical 242+ 支持
pip install -r requirements-mechanical.txt
# 可选：MCP 集成 / scripts Word 报告
pip install -r requirements-mcp.txt -r requirements-scripts.txt

# 4) 环境自检
python scripts/check_env.py

# 5) 启动服务
# Windows: start.bat    （Linux/macOS: ./start.sh）
# 或手动: python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

启动后访问：

- Swagger 接口文档：`http://127.0.0.1:8000/docs`
- 运行监控仪表盘：`http://127.0.0.1:8000/dashboard`

## 2. 前置条件

| 项 | 必需性 | 说明 |
|----|--------|------|
| Python 3.11+ | 必需 | main.py 启动时强制校验 |
| pip 核心依赖 | 必需 | requirements.txt |
| ANSYS 安装 | 可选 | 无 ANSYS 时日志诊断/仪表盘/监听/任务全部可用；求解器自动发现支持全版本（Windows 各盘符、Linux 标准位置），也可用 `MAPDL_EXECUTABLE` 显式指定 |
| LLM API Key | 可选 | 无 Key 时诊断自动回退本地规则；可启动后用仪表盘"配置 Key"按钮运行时注入，或写入 `.env`（从 `.env.example` 复制） |
| Node.js (npx) | 可选 | 仅 MCP 的 filesystem/deepseek 服务器需要 |
| ANSYS 许可证 | 求解时 | 真实求解需要；状态可在 `/mapdl-status` 查看 |

## 3. 环境自检

`python scripts/check_env.py` 会依次检查：

1. Python 版本（≥3.11）
2. 核心依赖导入（fastapi/uvicorn/openai/ansys-mapdl-core/pyvista 等）
3. 可选依赖（ansys-mechanical-core / mcp / python-docx，缺失仅提示）
4. 项目数据目录可写（runtime_data / reports / ansys_workspace）
5. ANSYS 求解器自动发现结果（版本与路径）
6. `.env` 与 LLM 配置状态

退出码 0 = 可以启动；非 0 = 按输出修复后重试。

## 4. 数据目录（全部在项目内，跨机器可移植）

| 目录 | 用途 |
|------|------|
| `runtime_data/` | 求解器运行时重定向目录、证据 journal（evidence/）、任务状态（jobs/）、监听配置（monitors.json）、观测事件（observability/） |
| `reports/` | Markdown 诊断报告与可视化 PNG |
| `ansys_workspace/`、`mechanical_workspace/` | 求解工作目录 |
| `knowledge_vault/` | knowledge_bridge 推送的工程经验（可用 `OBSIDIAN_VAULT_ROOT` 指向外部 Obsidian 库） |

以上目录均已列入 `.gitignore`，升级代码（git pull / 解压覆盖）不会影响运行数据。所有路径经 `paths.py` 锚定项目根——**从任意工作目录启动服务，数据都落在项目内**。

## 5. 常见问题（部署现场）

**Q1：`/run-*` 求解端点报 `Permission denied: .__tmp__.inp`？**
残留的 ANSYS.exe 求解器子进程锁住了工作目录（快速连续提交时常见）。处理：结束残留的 `ANSYS.exe`/`MAPDL.exe` 进程、运行工作目录中的 `cleanup-ansys-*.bat`，或为任务指定独立 `working_directory`。失败响应的 `hint` 字段会给出同样提示。

**Q2：`/mapdl-status` 显示未找到 MAPDL？**
按优先级检查：① `MAPDL_EXECUTABLE` 显式路径是否有效；② `ANSYS_DIR`/`AWP_ROOT` 是否指向正确；③ 安装位置是否在标准扫描范围外（此时必须显式指定）。`discovery_notes` 字段会列出探测过程。

**Q3：中文 Windows 下许可证状态显示"无法确定"？**
`sc query` 输出为本地编码（GBK），已做容错；若服务状态名与默认不同（自定义安装），属正常降级，不影响求解。

**Q4：LLM 连通失败？**
仪表盘"配置 Key"→ 填 Key → 保存并测试连通。注意运行时配置仅本次运行生效，持久化请写 `.env`。假 Key/断网时诊断自动回退本地规则，服务不中断。

**Q5：MCP 服务器（filesystem/deepseek）启动失败？**
需要 Node.js；Windows 下若 npx 启动失败，把 `.mcp.json` 中 `command` 改为 `cmd`、`args` 前加 `/c`。`ansys-local` 在无 ANSYS 机器上启动失败不影响其他服务器。

**Q6：端口被占用？**
`set PORT=8080`（Windows）或 `PORT=8080 ./start.sh` 后再运行启动脚本，或手动 `--port` 指定。

## 6. 升级与卸载

- **升级**：备份 `runtime_data/`（如需保留监听配置与任务历史）→ 覆盖代码 → `pip install -r requirements.txt`（依赖变化时）→ 重启
- **卸载**：删除项目目录即可；全部运行数据都在项目内，无系统残留（求解器运行时目录已重定向至项目内）
