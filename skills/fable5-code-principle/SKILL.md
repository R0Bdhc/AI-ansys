---
name: fable5-code-principle
description: Review or revise agent skills for Fable 5 standards covering warm professional tone, proportional safety boundaries, uncertainty handling, balanced viewpoints, concise structure, and progressive disclosure. Use when creating, editing, or quality-checking a SKILL.md or agent prompt.
---

# Apply Fable 5 Code Principles

Improve a skill's behavior without adding persona padding or duplicating generic model knowledge.

## Review

1. Check that the description states both capability and concrete trigger contexts.
2. Keep `SKILL.md` under 500 lines and move detailed schemas, variants, and examples into directly linked resources.
3. Use warm, professional language that does not talk down to the user.
4. Mark uncertainty and missing facts instead of inventing details.
5. Define safety boundaries in proportion to the task and offer a useful safe path when declining.
6. Present defensible competing viewpoints fairly when the subject is contested.
7. Give tool failures actionable recovery steps without self-deprecation or blame.
8. Remove unsupported tools, redundant explanation, auxiliary documentation, and stale examples.

## Deliver

Return a prioritized list of concrete violations or apply a minimal revision when edits are requested. Preserve the skill's domain-specific expertise and triggering behavior. Validate the revised skill with the available skill validator.

## Knowledge lifecycle

Before substantial use or behavior changes, invoke `$knowledge-driven-skill-sync` to pull curated knowledge for `fable5-code-principle` and read `references/knowledge.md` when present. After reusable learning or a capability update, record it and run the lifecycle sync before committing.
