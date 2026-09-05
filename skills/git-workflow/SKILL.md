---
name: git-workflow
description: Manage Git status, staging, commits, branch synchronization, pushes, and pull requests with a pre-push safety gate. Use when the user asks to commit, push, pull, sync, open a PR, or explain a safe Git workflow.
---

# Git Workflow

Keep local history intentional and never publish changes beyond the user's requested scope.

## Commit and push

1. Inspect status, branch, diff, and configured upstream.
2. Identify unrelated or user-owned changes and exclude them from the proposed commit.
3. Check for credentials, `.env` files, generated artifacts, and debugging leftovers.
4. Run relevant tests and invoke `$pre-push-review` when available.
5. Stage only intended files and create a concise Conventional Commit message.
6. Push the current branch without force. Never force-push a protected branch unless the user explicitly authorizes it and the consequences are clear.
7. Report the commit SHA, pushed ref, included files, validation, and review verdict.

## Pull and sync

Inspect for local changes first. Prefer a non-destructive rebase or fast-forward strategy consistent with repository instructions. Do not auto-stash or resolve conflicts by discarding work.

## Pull requests

Confirm the branch is pushed, summarize the diff and tests, then create or update a PR only when requested. Return the PR link and any remaining checks.

## Knowledge lifecycle

Before substantial use or behavior changes, invoke `$knowledge-driven-skill-sync` to pull curated knowledge for `git-workflow` and read `references/knowledge.md` when present. After reusable learning or a capability update, record it and run the lifecycle sync before committing.
