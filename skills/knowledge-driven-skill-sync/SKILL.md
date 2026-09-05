---
name: knowledge-driven-skill-sync
description: Package a canonical skills collection into multiple Git projects, install a pre-push consistency gate, and synchronize skill capabilities and reusable learnings with an Obsidian vault. Use when distributing skills, preparing project pushes, recording skill evolution, or updating skills from curated knowledge notes.
---

# Synchronize Skills and Knowledge

Use `scripts/skill_lifecycle.py` as the deterministic lifecycle tool. Read `references/project-map.json` before changing project assignments or the Vault location.

## Lifecycle

1. Run `pull-knowledge` before substantial skill use or functional edits. Read the generated `references/knowledge.md` when present.
2. Edit and validate the canonical skill under the central `skills/` collection.
3. Run `record-use` after a material use produces reusable knowledge. Summarize only durable lessons; never record secrets, raw private content, or transient logs.
4. Run `sync-all` to refresh Obsidian notes, distribute canonical skills into mapped projects, and regenerate project lock files.
5. Preserve each project's existing `AGENTS.md` and refresh its managed Skill invocation block.
6. Run `install-hooks` once per repository. The pre-push gate must reject missing, stale, ignored, untracked, or locally modified managed skill files and stale knowledge notes.

## Commands

```powershell
python scripts/skill_lifecycle.py pull-knowledge --skill <name>
python scripts/skill_lifecycle.py add-knowledge --skill <name> --content "<curated knowledge>"
python scripts/skill_lifecycle.py record-use --skill <name> --project <project> --summary "<durable learning>"
python scripts/skill_lifecycle.py sync-all
python scripts/skill_lifecycle.py verify-project --repo <project-root> --allow-untracked
python scripts/skill_lifecycle.py install-hooks
```

Use `--vault` or `OBSIDIAN_VAULT` to override the configured Vault. Treat `## Knowledge inputs` in each Obsidian skill note as curated user knowledge; preserve it during exports and pull it into the matching skill reference before redistributing. `add-knowledge` intentionally makes the gate stale until `sync-all` absorbs and redistributes the new knowledge.

Do not automatically commit, amend, or push. A blocked pre-push check means the user must run `sync-all`, review the changes, and commit the managed files.
