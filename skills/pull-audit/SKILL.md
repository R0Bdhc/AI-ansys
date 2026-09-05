---
name: pull-audit
description: Audit a pull request or branch diff for exploitable security defects, leaked credentials, PII, privacy compliance, and merge risk. Use when reviewing a PR, responding to an audit request, or deciding whether changes are safe to merge.
---

# Pull Audit

Evaluate the PR diff as a merge gate. Do not change code or submit a review unless the user explicitly asks for the external action.

## Workflow

1. Resolve the PR metadata, base branch, head branch, and complete diff. If no PR exists, compare the current branch with its base.
2. Review only changed behavior, but read surrounding code and tests when needed to validate impact.
3. Check injection, authentication, authorization, IDOR, unsafe crypto, SSRF, CSRF, CORS, dependency and supply-chain risk, secrets, PII, sensitive logs, excessive API responses, consent, retention, deletion, and transport security.
4. Distinguish genuine data from tests, examples, localhost addresses, and deleted secrets.
5. Give every finding a severity, tight location, evidence, impact, and actionable fix.

## Verdict

Return `BLOCKED` for any critical finding, `NEEDS CHANGES` for high-severity findings without criticals, and `APPROVED` when neither exists. State which tools or checks were unavailable and how that limits confidence.

## Knowledge lifecycle

Before substantial use or behavior changes, invoke `$knowledge-driven-skill-sync` to pull curated knowledge for `pull-audit` and read `references/knowledge.md` when present. After reusable learning or a capability update, record it and run the lifecycle sync before committing.
