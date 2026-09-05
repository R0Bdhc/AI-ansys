# AGENTS.md

<!-- skills-lifecycle:start -->
## Managed project skills

Project skills are stored in `skills/` and must be committed with the project.

- Match the task to each skill's frontmatter description, then read the selected `SKILL.md` completely before acting.
- Before substantial use or behavior changes, run `python .skills/skill_lifecycle.py pull-knowledge --skill <name>` and read `references/knowledge.md` when generated.
- After reusable learning, run `python .skills/skill_lifecycle.py record-use --skill <name> --project ai-ansys --summary "<durable learning>"`.
- After changing a skill, run the central `sync-all`, review all generated changes, and commit the managed files.
- The pre-push hook blocks stale, missing, ignored, untracked, or uncommitted managed skill artifacts.

Available managed skills:

- `knowledge-driven-skill-sync`
- `batch-contact`
- `check-ansys-env`
- `run-log-analysis`
- `run-mapdl-input`
- `meeting-notes-organizer`
- `code-debugger`
- `git-workflow`
- `pre-push-review`
- `pull-audit`
- `cross-agent-audit`
- `skill-creator-fable5`
- `fable5-code-principle`
<!-- skills-lifecycle:end -->
