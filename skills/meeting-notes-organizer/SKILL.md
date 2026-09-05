---
name: meeting-notes-organizer
description: Convert meeting transcripts into structured Markdown minutes with topics, decisions, action items, owners, deadlines, and CAE-specific discussion tags. Use for design reviews, technical discussions, project iterations, and troubleshooting meetings.
---

# Organize Meeting Notes

Extract decisions and responsibilities from messy conversation while preserving uncertainty and competing viewpoints.

## Workflow

1. Identify the meeting title, date, participants, type, and one-sentence purpose.
2. Group discussion by topic; mark CAE-specific sections with `[CAE]`.
3. Separate explicit decisions from proposals and unresolved questions.
4. Extract each action, owner, due date, and status. Mark absent or ambiguous fields as `[待确认]`.
5. Add externally verified background only in a clearly labeled reference section with sources.
6. Save only when requested, using `meeting-<topic>-<YYYY-MM-DD>.md` in the user's chosen knowledge-base folder.

## Output

Use sections for meeting overview, topic discussions, decisions, action items, unresolved questions, and references. Use a table for action items. Record sensitive personnel, budget, or commercial information factually without adding legal, HR, or compliance judgments.

## Knowledge lifecycle

Before substantial use or behavior changes, invoke `$knowledge-driven-skill-sync` to pull curated knowledge for `meeting-notes-organizer` and read `references/knowledge.md` when present. After reusable learning or a capability update, record it and run the lifecycle sync before committing.
