---
name: code-debugger
description: Reproduce software defects, locate root causes, implement minimal fixes, run regression checks, and document evidence. Use when the user asks to debug, fix, or investigate failing code across common programming languages and repositories.
---

# Debug Code

Complete the loop: understand, reproduce, isolate, fix, verify, and report.

## Workflow

1. Read repository instructions, architecture notes, relevant code, recent changes, and nearby tests.
2. Reproduce the failure with the smallest reliable input. Preserve the exact error and command.
3. Trace the call path and identify the root cause, affected boundaries, and likely blast radius.
4. Implement the smallest coherent fix. Do not mix unrelated cleanup into the patch.
5. Run focused tests first, then the broader relevant suite, static checks, and diagnostics.
6. Report the root cause, changed files, validation evidence, remaining risk, and useful follow-up tests.

Consult recent project debug logs when they exist, but verify old conclusions against current code. Never record secrets or PII in a debug log. Modify CI, deployment, or repository metadata only when the requested fix truly requires it.

If the user asked only for diagnosis, stop after evidence-backed root-cause analysis and do not edit files.

## Knowledge lifecycle

Before substantial use or behavior changes, invoke `$knowledge-driven-skill-sync` to pull curated knowledge for `code-debugger` and read `references/knowledge.md` when present. After reusable learning or a capability update, record it and run the lifecycle sync before committing.
