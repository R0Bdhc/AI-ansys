---
name: skill-creator-fable5
description: Create, revise, evaluate, and consolidate reusable Codex or Claude-style skills while applying concise Fable 5 behavior, safety, error-handling, and progressive-disclosure standards. Use when designing a skill, migrating legacy skill.yaml or Markdown prompts, deduplicating skills, or reviewing skill quality.
---

# Create Skills with Fable 5

Produce a compact, installable skill that another agent can reliably trigger and follow.

## Workflow

1. Identify concrete user prompts that should trigger the skill and the outcomes it must produce.
2. Inspect existing workflows, scripts, references, assets, and duplicates before drafting.
3. Choose a lowercase hyphenated name under 64 characters.
4. Keep only `name` and `description` in `SKILL.md` frontmatter. Put all trigger conditions in the description.
5. Write imperative instructions. Keep the core workflow lean and move detailed schemas, examples, or variants into one-level `references/` files.
6. Reuse deterministic scripts for repeated fragile operations and test them directly.
7. Generate `agents/openai.yaml` with quoted `display_name`, `short_description`, and a `default_prompt` that explicitly names `$skill-name`.
8. Validate with the available skill validator and fix every reported issue.
9. Forward-test only when requested or when project instructions explicitly permit delegated evaluation.

## Fable 5 checks

Use warm professional language, state uncertainty instead of guessing, preserve multiple defensible viewpoints, define safety boundaries proportionally, and handle tool failures with actionable recovery. Avoid persona padding, repeated explanations, auxiliary READMEs, and unsupported tool names.

When consolidating legacy skills, preserve distinct capabilities, merge exact duplicates, replace redirect stubs with the canonical skill, and record the source mapping in the collection index.

## Knowledge lifecycle

Before substantial use or behavior changes, invoke `$knowledge-driven-skill-sync` to pull curated knowledge for `skill-creator-fable5` and read `references/knowledge.md` when present. After reusable learning or a capability update, record it and run the lifecycle sync before committing.
