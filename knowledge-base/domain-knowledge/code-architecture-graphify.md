# AI-ansys 代码架构图谱分析 (Graphify)

> 🔵 `cae-agent` | 生成工具: `graphify` (v0.9.33) | 模式: `--code-only` | 日期: 2026-08-05
> 关联分析: [[obsidian-note-system]]（本机笔记，未入库） | 关联文档: [CLAUDE.md](../../CLAUDE.md)

---

## 执行摘要

使用 `graphify extract . --code-only` 对 `AI-ansys` 进行纯代码 AST 提取，生成知识图谱。

| 指标 | 数值 |
|------|------|
| 代码文件数 | 19 |
| 跳过非代码 | 40 (37 docs + 3 images) |
| 图谱节点 | **299** |
| 图谱边 | **714** |
| 社区数 | **11** (1 个薄弱社区被省略) |
| 提取质量 | 97% EXTRACTED, 3% INFERRED, 0% AMBIGUOUS |
| 导入循环 | **无** ✅ |
| API 成本 | **0** (纯本地 AST) |

---

## 一、社区 ↔ 模块职责映射表

将 Graphify 自动发现的 11 个社区与 [CLAUDE.md](../../CLAUDE.md) 中**手动维护**的模块职责表进行对比：

| 社区 | 核心节点 | 对应 CLAUDE.md 模块 | 职责匹配度 |
|------|---------|---------------------|-----------|
| **Community 2** | `main()`, `AnalyzeLogRequest`, `MapdlInputRequest`, `BaseModel` | `main.py` | ✅ 完全匹配 |
| **Community 3** | `AnsysRunner`, `_stdio_guard` | `ansys_runner.py` | ✅ 完全匹配 |
| **Community 4** | `MechanicalRunner` | `mechanical_runner.py` | ✅ 完全匹配 |
| **Community 5** | `build_template()`, `CantileverBeamTemplate` | `simulation_templates.py` | ✅ 完全匹配 |
| **Community 6** | `PostProcessor` | `post_processor.py` | ✅ 完全匹配 |
| **Community 7** | `LLMAnalyzer`, `LLMConfig` | `llm_analyzer.py` | ✅ 完全匹配 |
| **Community 8** | `.mcp.json`, `DEEPSEEK_API_KEY`, `filesystem` | (配置层，无独立模块) | ⚠️ 代码外配置，手动文档已覆盖 |
| **Community 9** | `expected_tip_displacement()`, `main()` | `scripts/validate_cantilever.py` | ⚠️ 脚本文档未在 CLAUDE.md 中显式列出 |
| **Community 10** | `pre-push`, `pre-push script` | `.githooks/pre-push` | ⚠️ 钩子逻辑未在 CLAUDE.md 中显式列出 |
| **Community 0 / 1** | `skill_lifecycle`, `sync_projects()` | `.skills/skill_lifecycle.py` | ❌ **重复代码警报** |

**结论**: Graphify 的自动社区划分与人工编写的模块边界**高度一致**（6/11 完全匹配），验证了 CLAUDE.md 架构概览的准确性。

---

## 二、God Nodes (架构核心抽象)

按连接度排序的 Top 10 节点，即系统的**架构枢纽**：

| 排名 | 节点 | 连接数 | 文件 | 角色 |
|------|------|--------|------|------|
| 1 | `AnsysRunner` | 37 | `ansys_runner.py` | PyMAPDL 执行生命周期中枢 |
| 2 | `MechanicalRunner` | 23 | `mechanical_runner.py` | PyMechanical 批量接触中枢 |
| 3 | `LLMAnalyzer` | 21 | `llm_analyzer.py` | LLM 多提供商分析中枢 |
| 4 | `LifecycleError` | 15 | `skill_lifecycle.py` | Skill 生命周期异常 |
| 5 | `sync_projects()` | 15 | `skill_lifecycle.py` | 跨项目同步逻辑 |
| 6 | `PostProcessor` | 14 | `post_processor.py` | 后处理可视化中枢 |
| 7 | `collection_root()` | 13 | `skill_lifecycle.py` | Skill 集合根目录解析 |
| 8 | `main()` | 13 | `skill_lifecycle.py` | Skill CLI 入口 |

**关键洞察**: `AnsysRunner` 的连接数是 `PostProcessor` 的 2.6 倍，说明 `ansys_runner.py` 承担了过多的跨模块协调职责。这与 CLAUDE.md 中"禁止写业务逻辑"的约定存在张力——`AnsysRunner` 可能已超出"生命周期管理"的单一职责。

---

## 三、Surprising Connections (意外连接)

Graphify 通过 AST 推断出的非显式导入关系，需人工验证：

| 源 | 关系 | 目标 | 置信度 | 验证状态 |
|----|------|------|--------|---------|
| `AnsysRunner` | uses | `PostProcessor` | INFERRED | ✅ 正确 (ansys_runner 调用 post_processor 进行后处理) |
| `AnalyzeLogRequest` | uses | `AnsysRunner` | INFERRED | ✅ 正确 (main.py 路由使用 AnsysRunner) |
| `AnsysDemoRequest` | uses | `AnsysRunner` | INFERRED | ✅ 正确 |
| `MapdlInputRequest` | uses | `AnsysRunner` | INFERRED | ✅ 正确 |
| `MechanicalBatchContactRequest` | uses | `AnsysRunner` | INFERRED | ⚠️ 待验证 (应为 MechanicalRunner) |

**说明**: `AnalyzeLogRequest` 等 Pydantic 模型本身不直接 import `AnsysRunner`，但 Graphify 通过 FastAPI 路由注册推断出它们在运行时与 `AnsysRunner` 绑定。这是 AST 静态分析的优势——能捕捉**运行时依赖**而不仅是 import 语句。

---

## 四、发现的问题与知识缺口

### 4.1 ⚠️ 重复代码（已核实为分发副本，非缺陷）

**Community 0** 和 **Community 1** 几乎完全相同（各 46 个节点），分别对应：
- `skills/knowledge-driven-skill-sync/scripts/skill_lifecycle.py`（Skill 自带的规范脚本）
- `.skills/skill_lifecycle.py`（`sync-projects` 从规范脚本复制到项目内的分发副本）

**验证命令**:
```bash
diff skills/knowledge-driven-skill-sync/scripts/skill_lifecycle.py .skills/skill_lifecycle.py
# 输出: 0 行差异（完全字节级相同）
```

这不是重复实现：`.skills/skill_lifecycle.py` 由 Skill 生命周期工具自动生成，其哈希被写入 `.skills/skills-lock.json`，pre-push 钩子会校验两者一致。**不要删除任何一份**——删除项目副本会让 `verify-project` 失败；删除 Skill 内脚本则丢失规范来源。

**建议**: 保持现状，由 `sync-projects` 维持两份字节一致。

### 4.2 孤立节点 (Knowledge Gaps)

9 个孤立节点，主要是 MCP 配置中的字符串字面量：

| 孤立节点 | 原因 |
|----------|------|
| `@anthropic/mcp-server-filesystem` | `.mcp.json` 中的命令字符串，无代码引用 |
| `deepseek-mcp-server` | `.mcp.json` 中的 npm 包名 |
| `DEEPSEEK_API_KEY` | 环境变量名，无 Python 常量定义 |
| `DEEPSEEK_MODEL` | 环境变量名 |
| `python` | `.mcp.json` 中的解释器路径 |

**说明**: 这些不是真正的"知识缺口"，而是配置文件中的字符串字面量被 Graphify 提取为节点，但它们在代码中没有被显式引用（仅被 MCP 框架在运行时解析）。

### 4.3 未在 CLAUDE.md 中显式文档化的组件

Graphify 曾发现以下组件未被手动文档覆盖，当前状态：

| 组件 | 位置 | 状态 |
|------|------|------|
| `scripts/validate_cantilever.py` | `scripts/` | ✅ 已在 README「验证与测试」列出 |
| `mechanical_post_processor.py` | 根目录 | ✅ 已纳入 CLAUDE.md 架构概览与职责表 |
| `knowledge_bridge.py` | 根目录 | ✅ 已纳入 CLAUDE.md 架构概览与职责表 |
| `.githooks/pre-push` | `.githooks/` | ✅ 由 AGENTS.md 声明，`verify-project` 执行校验 |

---

## 五、Graphify vs Obsidian 知识库对比

| 维度 | Graphify (自动) | Obsidian 知识库 (手动) |
|------|----------------|----------------------|
| **更新频率** | 命令触发 / `graphify update` | 对话触发 / `skill_lifecycle.py sync-all` |
| **覆盖范围** | 代码结构、模块依赖、调用链 | 工程经验、决策上下文、Fable5 标准、最佳实践 |
| **精度** | 精确到函数/类级别 (AST) | 精确到概念/经验级别 (自然语言) |
| **盲区** | 无法捕获运行时状态、配置语义 | 无法自动感知代码结构变化 |
| **成本** | 0 token (纯 AST) | 依赖 LLM 对话，有 token 消耗 |
| **可查询性** | `graphify query`, `graphify path` | Obsidian MCP Server 40+ 工具 |

**互补策略**: Graphify 回答"代码如何组织"，Obsidian 回答"为什么这样设计"。两者结合可形成"结构 + 语义"的完整知识覆盖。

---

## 六、与 validation.json 的关联

`runtime_data/cantilever_validation/validation.json`（运行时生成，未入库）的执行链路可通过 Graphify 图谱完整追溯：

```
main.py (Community 2)
  └── AnsysDemoRequest / TemplateSimulationRequest
        └── AnsysRunner (Community 3)
              ├── simulation_templates.py (Community 5)
              │     └── CantileverBeamTemplate
              └── post_processor.py (Community 6)
                    └── PostProcessor
                          └── engineering_results.displacement
```

Graphify 的 `path` 功能可直接回答："从 `TemplateSimulationRequest` 到 `PostProcessor` 的最短路径是什么？"

---

## 七、后续行动建议

### 短期 (方案 A 延续)

1. **保持分发副本同步**: `.skills/skill_lifecycle.py` 与 `skills/knowledge-driven-skill-sync/scripts/skill_lifecycle.py` 由 `sync-projects` 保持字节一致，`verify-project` 校验哈希，无需删除
2. **补充 CLAUDE.md**: `knowledge_bridge.py` 已纳入架构概览与职责表；`scripts/validate_cantilever.py` 已在 README「验证与测试」列出
3. **安装 Graphify Claude 集成**: `graphify claude install` 会在 `CLAUDE.md` 中追加 PreToolUse hook，使 Glob/Grep 调用先查图谱再查文件系统，节省 token

### 中期 (方案 B 前置条件)

1. **在 CI 中加入 `graphify update`**: 每次 PR 自动更新图谱，若社区结构变化 >20% 则触发架构审查
2. **统一工作区图谱**: 使用 `graphify merge-graphs` 将 `AI-ansys`、`code_check`、`unified-obsidian-knowledge` 的图谱合并为全局图，暴露跨项目依赖
3. **Graphify-Obsidian 闭环**: 将 `GRAPH_REPORT.md` 自动复制到 `knowledge-base/domain-knowledge/`（如本文件），并在 Obsidian Stage 2 (`knowledge-refine`) 中纳入审查

---

## 参考命令

```bash
# 更新图谱（代码变更后）
graphify update .

# 查询两个节点间的最短路径
graphify path "AnsysRunner" "PostProcessor"

# 解释某个节点的上下文
graphify explain "AnsysRunner"

# 导出 Mermaid 架构图
graphify export callflow-html

# 查看架构枢纽
cd graphify-out && graphify god-nodes
```
