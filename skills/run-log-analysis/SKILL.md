---
name: run-log-analysis
description: Analyze ANSYS .out, .log, or .err solver logs, detect known errors, obtain LLM or rule-based diagnosis, and produce a Markdown report. Use when a solve fails, convergence is poor, or the user provides an ANSYS log path or pasted log text.
---

# Analyze ANSYS Run Logs

Turn a solver log into an evidence-based error summary and remediation report.

## Workflow

1. Accept either an absolute log path or pasted log text.
2. For a path, verify that the file exists and is readable.
3. Call `log_analyze(log_path=...)` or `log_analyze(log_text=...)` from the `ansys-local` MCP server.
4. Extract `error_count`, `detected_errors`, `llm_result.mode`, `report_path`, and `markdown_preview` when present.
5. Distinguish `deepseek`, `rule_based`, and `fallback_after_llm_error`; never present rule-based output as an LLM conclusion.

## Report

List each error code, title, evidence snippet, likely causes, and suggested checks. Include the analysis mode and report path. Mention when input sent to the LLM was truncated or when local rules were used as fallback.

## Knowledge lifecycle

Before substantial use or behavior changes, invoke `$knowledge-driven-skill-sync` to pull curated knowledge for `run-log-analysis` and read `references/knowledge.md` when present. After reusable learning or a capability update, record it and run the lifecycle sync before committing.
