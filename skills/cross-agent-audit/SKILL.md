---
name: cross-agent-audit
description: Run a repository-wide or incremental audit that combines change detection, secret and PII scanning, code-risk heuristics, contextual validation, and a unified report. Use for recurring library audits, CI checks, or agent-to-agent repository review.
---

# Cross-Agent Audit

Audit a target Git repository using the workspace `code_check` pipeline when available, then validate important findings in context.

## Workflow

1. Verify the target path exists and is a Git repository.
2. Default to incremental review from the last recorded SHA; use full review only when requested or no baseline exists.
3. If `D:/Projects/code_check/cross-agent/check.sh` is available, run it through a compatible shell with the requested options.
4. Review security patterns, PII, weak crypto, dangerous execution, sensitive logging, TODO-like risk markers, null handling, and changed tests.
5. Read surrounding code for critical and high matches, trace callers, and classify false positives before reporting.
6. Preserve the baseline state only when the audit pipeline completes successfully.

## Verdict

Return `BLOCKED` for validated critical findings, `WARNINGS` for high or medium findings and debug risks, and `CLEAR` when none remain. Include the reviewed range, baseline SHA, report path, counts by severity, and any unavailable checks.

## Knowledge lifecycle

Before substantial use or behavior changes, invoke `$knowledge-driven-skill-sync` to pull curated knowledge for `cross-agent-audit` and read `references/knowledge.md` when present. After reusable learning or a capability update, record it and run the lifecycle sync before committing.
