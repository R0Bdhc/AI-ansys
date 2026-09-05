# Graph Report - .  (2026-08-05)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 299 nodes · 714 edges · 11 communities (10 shown, 1 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 19 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `9c7a823c`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10

## God Nodes (most connected - your core abstractions)
1. `AnsysRunner` - 37 edges
2. `MechanicalRunner` - 23 edges
3. `LLMAnalyzer` - 21 edges
4. `LifecycleError` - 15 edges
5. `sync_projects()` - 15 edges
6. `LifecycleError` - 15 edges
7. `sync_projects()` - 15 edges
8. `PostProcessor` - 14 edges
9. `collection_root()` - 13 edges
10. `main()` - 13 edges

## Surprising Connections (you probably didn't know these)
- `AnsysRunner` --uses--> `PostProcessor`  [INFERRED]
  ansys_runner.py → post_processor.py
- `AnalyzeLogRequest` --uses--> `AnsysRunner`  [INFERRED]
  main.py → ansys_runner.py
- `AnsysDemoRequest` --uses--> `AnsysRunner`  [INFERRED]
  main.py → ansys_runner.py
- `MapdlInputRequest` --uses--> `AnsysRunner`  [INFERRED]
  main.py → ansys_runner.py
- `MechanicalBatchContactRequest` --uses--> `AnsysRunner`  [INFERRED]
  main.py → ansys_runner.py

## Import Cycles
- None detected.

## Communities (11 total, 1 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.15
Nodes (46): add_knowledge(), agent_block(), all_skill_names(), build_parser(), collection_root(), copy_managed_tree(), extract_section(), file_hash() (+38 more)

### Community 1 - "Community 1"
Cohesion: 0.15
Nodes (46): add_knowledge(), agent_block(), all_skill_names(), build_parser(), collection_root(), copy_managed_tree(), extract_section(), file_hash() (+38 more)

### Community 2 - "Community 2"
Cohesion: 0.10
Nodes (40): BaseModel, get, push_experience(), push_report_summary(), Path, 将单条工程经验写入 Obsidian 知识库。 Args: title: 经验标题（用于文件名和文档标题） content: Markdown 格式的经验内容…, 将已有的 Markdown 报告摘要纳入知识库。 Args: report_path: 原始报告文件路径（如…, _build_snippet() (+32 more)

### Community 3 - "Community 3"
Cohesion: 0.14
Nodes (9): AnsysRunner, Path, _stdio_guard, 封装 ANSYS / PyMAPDL 执行流程，集成模板仿真、后处理可视化与环境诊断。, 运行预定义模板仿真，可选执行后处理可视化。, 装饰器：在工具调用期间将 sys.stdout 重定向到 sys.stderr，防止污染 JSON-RPC stdio 流。, 求解完成后提取位移、应力、频率等工程物理量。, 检查 ANSYS License Manager CVD 服务状态（Windows）。 (+1 more)

### Community 4 - "Community 4"
Cohesion: 0.11
Nodes (14): MechanicalRunner, Path, 执行基于 Named Selection 的批量接触创建。, 在 242+ Mechanical 中执行批量接触脚本。, 生成在 Mechanical 中执行的批量接触脚本。, 准备 PyMechanical 运行环境，避免系统目录写权限问题。, 返回 PyMechanical 242+ 能力的环境状态。, 检查当前环境是否能导入 PyMechanical。 (+6 more)

### Community 5 - "Community 5"
Cohesion: 0.13
Nodes (15): build_template(), CantileverBeamParams, CantileverBeamTemplate, get_template_info(), list_templates(), PlateWithHoleParams, PlateWithHoleTemplate, Any (+7 more)

### Community 6 - "Community 6"
Cohesion: 0.13
Nodes (17): PostProcessor, Any, Path, _stdio_guard, post_processor.py 后处理可视化与应力曲线提取模块。 依赖： pip install pyvista ansys-tools-…, 沿指定几何路径提取 Von Mises 应力，绘制曲线并导出 JSON 数据。 Args: mapdl: PyMAPDL 实例（已求解完成）…, 一键执行：应力云图 + 位移云图 + 可选应力曲线。, 封装 PyMAPDL 后处理可视化与数据提取流程。 (+9 more)

### Community 7 - "Community 7"
Cohesion: 0.13
Nodes (10): LLMAnalyzer, LLMConfig, _provider_display_name(), Any, llm_analyzer.py 多提供商 LLM 分析模块，支持 DeepSeek、Kimi、Claude、OpenAI、本地模型及任意 OpenAI…, 返回当前解析后的配置（隐藏 API Key）。, 返回 LLM 当前是否已配置以及是否可连通。, 负责 LLM 分析，支持多提供商切换，并在失败时回退到本地规则分析。 (+2 more)

### Community 8 - "Community 8"
Cohesion: 0.15
Nodes (13): ANSYS241_DIR, ANSYSLIC_DIR, AWP_ROOT241, DEEPSEEK_API_KEY, DEEPSEEK_MODEL, PYTHONPATH, npx, python (+5 more)

### Community 9 - "Community 9"
Cohesion: 0.53
Nodes (5): expected_tip_displacement(), main(), Path, Run and validate the cantilever template against a real MAPDL host., write_result()

## Knowledge Gaps
- **9 isolated node(s):** `@anthropic/mcp-server-filesystem`, `deepseek-mcp-server`, `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, `python` (+4 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AnsysRunner` connect `Community 3` to `Community 9`, `Community 2`, `Community 5`, `Community 6`?**
  _High betweenness centrality (0.172) - this node is a cross-community bridge._
- **Why does `MechanicalRunner` connect `Community 4` to `Community 2`?**
  _High betweenness centrality (0.103) - this node is a cross-community bridge._
- **Why does `PostProcessor` connect `Community 6` to `Community 3`, `Community 5`?**
  _High betweenness centrality (0.087) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `AnsysRunner` (e.g. with `PostProcessor` and `AnalyzeLogRequest`) actually correct?**
  _`AnsysRunner` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `MechanicalRunner` (e.g. with `AnalyzeLogRequest` and `AnsysDemoRequest`) actually correct?**
  _`MechanicalRunner` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `LLMAnalyzer` (e.g. with `AnalyzeLogRequest` and `AnsysDemoRequest`) actually correct?**
  _`LLMAnalyzer` has 6 INFERRED edges - model-reasoned connections that need verification._
- **What connects `@anthropic/mcp-server-filesystem`, `deepseek-mcp-server`, `DEEPSEEK_API_KEY` to the rest of the system?**
  _9 weakly-connected nodes found - possible documentation gaps or missing edges._