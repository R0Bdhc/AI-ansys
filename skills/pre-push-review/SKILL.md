---
name: pre-push-review
description: Perform a read-only pre-push gate over staged or unpushed changes for security, privacy, secrets, PII, correctness, and test risk. Use immediately before git push or when the user requests a go/no-go review of local changes.
---

# Pre-Push Review

Review only; do not modify code, stage files, commit, or push.

## Establish scope

1. Prefer the staged diff when staged changes exist.
2. Otherwise compare unpushed commits with the configured upstream.
3. If only unstaged changes exist, state that they are outside the push scope and ask whether to include them in a separate review.
4. Inspect added lines for secrets and PII while using surrounding context to reject obvious fixtures and placeholders.

## Review

Check injection, authentication and authorization, unsafe deserialization, weak cryptography, dependency risk, leaked credentials, PII, sensitive logging, internal error disclosure, data-consent handling, logic defects, error propagation, concurrency, and test coverage.

Treat private keys, live tokens, credentials, exploitable authorization bypasses, and real PII as critical. Do not elevate pattern matches without validating context.

## Verdict

Return `BLOCKED` for any critical finding or at least three high-severity findings; return `WARNINGS` for non-blocking risk; otherwise return `CLEAR`. Every finding must include severity, file and line, evidence, impact, and a concrete remediation. State the reviewed revision range and any scope limitations.

## Knowledge lifecycle

Before substantial use or behavior changes, invoke `$knowledge-driven-skill-sync` to pull curated knowledge for `pre-push-review` and read `references/knowledge.md` when present. After reusable learning or a capability update, record it and run the lifecycle sync before committing.
