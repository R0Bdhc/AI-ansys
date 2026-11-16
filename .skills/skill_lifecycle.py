#!/usr/bin/env python3
"""Synchronize canonical skills, project copies, Git gates, and Obsidian notes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SCRIPT_PATH = Path(__file__).resolve()
IGNORED_DIRS = {".git", "__pycache__"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
PLACEHOLDER = (
    "<!-- 在此写入经确认、可反向影响 Skill 的知识。运行 pull-knowledge 或 "
    "sync-all 后会提炼到 references/knowledge.md。 -->"
)
AGENT_BLOCK_START = "<!-- skills-lifecycle:start -->"
AGENT_BLOCK_END = "<!-- skills-lifecycle:end -->"
SECRET_PATTERN = re.compile(
    r"(?:sk-(?:proj-|org-)?[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
    r"github_pat_[A-Za-z0-9_]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
    re.IGNORECASE,
)


class LifecycleError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def file_hash(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() in IGNORED_SUFFIXES:
            continue
        yield path


def tree_files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): file_hash(path)
        for path in iter_files(root)
    }


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for rel, value in tree_files(root).items():
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(value.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def project_config_path() -> Path:
    if SCRIPT_PATH.parent.name == "scripts":
        return Path()
    return SCRIPT_PATH.parent / "project.json"


def collection_root() -> Path:
    if SCRIPT_PATH.parent.name == "scripts":
        return SCRIPT_PATH.parents[2]
    config_path = project_config_path()
    if not config_path.exists():
        raise LifecycleError(f"Missing project configuration: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return Path(config["canonical_root"]).resolve()


def workspace_root() -> Path:
    return collection_root().parent


def manifest_path() -> Path:
    return (
        collection_root()
        / "knowledge-driven-skill-sync"
        / "references"
        / "project-map.json"
    )


def load_manifest() -> dict:
    path = manifest_path()
    if not path.exists():
        raise LifecycleError(f"Missing manifest: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def select_projects(manifest: dict, names: list[str] | None) -> list[dict]:
    projects = manifest["projects"]
    if not names:
        return projects
    wanted = set(names)
    selected = [p for p in projects if p["name"] in wanted]
    missing = wanted - {p["name"] for p in selected}
    if missing:
        raise LifecycleError(f"Unknown projects: {', '.join(sorted(missing))}")
    return selected


def all_skill_names() -> list[str]:
    root = collection_root()
    return sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "SKILL.md").exists()
    )


def select_skills(names: list[str] | None) -> list[str]:
    available = set(all_skill_names())
    if not names:
        return sorted(available)
    missing = set(names) - available
    if missing:
        raise LifecycleError(f"Unknown skills: {', '.join(sorted(missing))}")
    return sorted(set(names))


def resolve_vault(manifest: dict, override: str | None = None) -> Path:
    raw = override or os.environ.get("OBSIDIAN_VAULT") or manifest["vault_path"]
    return Path(raw).expanduser().resolve()


def extract_section(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"(?ms)^## {re.escape(heading)}\s*\n(.*?)(?=^##\s|\Z)"
    )
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def parse_frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        raise LifecycleError("Missing YAML frontmatter")
    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise LifecycleError(f"Invalid frontmatter line: {line}")
        values[key.strip()] = value.strip().strip('"')
    return values


def parse_note_field(text: str, field: str) -> str:
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return ""
    field_match = re.search(
        rf"(?m)^{re.escape(field)}:\s*[\"']?([^\"'\n]+)", match.group(1)
    )
    return field_match.group(1).strip() if field_match else ""


def validate_skill(skill_name: str) -> None:
    root = collection_root() / skill_name
    text = (root / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(text)
    if set(frontmatter) != {"name", "description"}:
        raise LifecycleError(
            f"{skill_name}: frontmatter must contain only name and description"
        )
    if frontmatter["name"] != skill_name:
        raise LifecycleError(f"{skill_name}: frontmatter name mismatch")
    if not frontmatter["description"]:
        raise LifecycleError(f"{skill_name}: empty description")
    if len(text.splitlines()) >= 500:
        raise LifecycleError(f"{skill_name}: SKILL.md must stay under 500 lines")
    openai_yaml = root / "agents" / "openai.yaml"
    if not openai_yaml.exists():
        raise LifecycleError(f"{skill_name}: missing agents/openai.yaml")
    if f"${skill_name}" not in openai_yaml.read_text(encoding="utf-8"):
        raise LifecycleError(f"{skill_name}: default prompt must name ${skill_name}")


def summarize_skill(skill_name: str) -> tuple[str, str]:
    text = (collection_root() / skill_name / "SKILL.md").read_text(encoding="utf-8")
    description = parse_frontmatter(text)["description"]
    body = re.split(r"\n---\s*\n", text, maxsplit=1)[-1]
    summary: list[str] = []
    current_heading = ""
    item_count = 0
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            heading = line[3:].strip()
            current_heading = "" if heading in {"Knowledge lifecycle", "Lifecycle"} else heading
            if current_heading:
                summary.append(f"### {current_heading}")
            item_count = 0
        elif current_heading and re.match(r"^(?:[-*]|\d+\.)\s+", line):
            if item_count < 5:
                summary.append(line)
            item_count += 1
        elif current_heading and line and not line.startswith(("#", "```", "|")):
            if item_count == 0:
                summary.append(line)
                item_count += 1
    return description, "\n".join(summary[:40]).strip()


def note_path_for(vault: Path, manifest: dict, skill_name: str) -> Path:
    return vault / manifest["knowledge_folder"] / f"{skill_name}.md"


def render_note(skill_name: str, existing: str = "") -> str:
    skill_root = collection_root() / skill_name
    description, summary = summarize_skill(skill_name)
    knowledge = extract_section(existing, "Knowledge inputs") or PLACEHOLDER
    usage = extract_section(existing, "Usage and evolution log") or "_No recorded uses yet._"
    knowledge_hash = sha256_text(knowledge.strip())
    source_hash = tree_hash(skill_root)
    source = (skill_root / "SKILL.md").as_posix()
    unchanged = (
        parse_note_field(existing, "source_hash") == source_hash
        and parse_note_field(existing, "knowledge_inputs_hash") == knowledge_hash
    )
    updated = parse_note_field(existing, "updated") if unchanged else utc_now()
    updated = updated or utc_now()
    return f'''---
type: "skill-knowledge"
skill: "{skill_name}"
source: "{source}"
source_hash: "{source_hash}"
knowledge_inputs_hash: "{knowledge_hash}"
updated: "{updated}"
tags:
  - "skill"
  - "skill-evolution"
---

# {skill_name}

## Current skill capability

{description}

{summary}

## Knowledge inputs

{knowledge}

## Usage and evolution log

{usage}
'''


def sync_knowledge(
    skills: list[str], manifest: dict, vault_override: str | None = None
) -> list[Path]:
    vault = resolve_vault(manifest, vault_override)
    if not vault.exists():
        raise LifecycleError(f"Obsidian Vault does not exist: {vault}")
    written: list[Path] = []
    for skill_name in skills:
        validate_skill(skill_name)
        note = note_path_for(vault, manifest, skill_name)
        existing = note.read_text(encoding="utf-8") if note.exists() else ""
        content = render_note(skill_name, existing)
        note.parent.mkdir(parents=True, exist_ok=True)
        if not note.exists() or note.read_text(encoding="utf-8") != content:
            note.write_text(content, encoding="utf-8", newline="\n")
            written.append(note)
    return written


def pull_knowledge(
    skills: list[str], manifest: dict, vault_override: str | None = None
) -> list[Path]:
    vault = resolve_vault(manifest, vault_override)
    changed: list[Path] = []
    for skill_name in skills:
        note = note_path_for(vault, manifest, skill_name)
        if not note.exists():
            continue
        knowledge = extract_section(note.read_text(encoding="utf-8"), "Knowledge inputs")
        meaningful = re.sub(r"<!--.*?-->", "", knowledge, flags=re.DOTALL).strip()
        if not meaningful:
            continue
        if SECRET_PATTERN.search(meaningful):
            raise LifecycleError(f"Refusing secret-like knowledge for {skill_name}")
        reference = collection_root() / skill_name / "references" / "knowledge.md"
        reference.parent.mkdir(parents=True, exist_ok=True)
        content = (
            f"# Curated knowledge for {skill_name}\n\n"
            f"Source: `{note.as_posix()}`\n\n{meaningful}\n"
        )
        if not reference.exists() or reference.read_text(encoding="utf-8") != content:
            reference.write_text(content, encoding="utf-8", newline="\n")
            changed.append(reference)
    return changed


def copy_managed_tree(source: Path, destination: Path, old_files: set[str]) -> None:
    source_files = tree_files(source)
    for rel in sorted(old_files - set(source_files)):
        stale = destination / rel
        if stale.is_file():
            stale.unlink()
    for rel in source_files:
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, target)


def hook_text() -> str:
    return '''#!/bin/sh
set -eu

repo_root=$(git rev-parse --show-toplevel)
checker="$repo_root/.skills/skill_lifecycle.py"

if command -v python3 >/dev/null 2>&1; then
  python3 "$checker" verify-project --repo "$repo_root"
elif command -v python >/dev/null 2>&1; then
  python "$checker" verify-project --repo "$repo_root"
elif command -v py >/dev/null 2>&1; then
  py -3 "$checker" verify-project --repo "$repo_root"
else
  echo "BLOCKED: Python is required to verify managed skills." >&2
  exit 1
fi

if [ -f "$repo_root/hooks/pre-push" ]; then
  bash "$repo_root/hooks/pre-push" "$@"
fi
'''


def agent_block(project: dict) -> str:
    skills = "\n".join(f"- `{name}`" for name in project["skills"])
    destination = project["destination"]
    return f'''{AGENT_BLOCK_START}
## Managed project skills

Project skills are stored in `{destination}/` and must be committed with the project.

- Match the task to each skill's frontmatter description, then read the selected `SKILL.md` completely before acting.
- Before substantial use or behavior changes, run `python .skills/skill_lifecycle.py pull-knowledge --skill <name>` and read `references/knowledge.md` when generated.
- After reusable learning, run `python .skills/skill_lifecycle.py record-use --skill <name> --project {project['name']} --summary "<durable learning>"`.
- After changing a skill, run the central `sync-all`, review all generated changes, and commit the managed files.
- The pre-push hook blocks stale, missing, ignored, untracked, or uncommitted managed skill artifacts.

Available managed skills:

{skills}
{AGENT_BLOCK_END}'''


def update_agent_instructions(path: Path, project: dict) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else "# AGENTS.md\n"
    block = agent_block(project)
    pattern = re.compile(
        rf"(?ms){re.escape(AGENT_BLOCK_START)}.*?{re.escape(AGENT_BLOCK_END)}"
    )
    if pattern.search(existing):
        updated = pattern.sub(block, existing)
    else:
        updated = existing.rstrip() + "\n\n" + block + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != updated:
        path.write_text(updated, encoding="utf-8", newline="\n")


def project_index_text(project: dict) -> str:
    entries = "\n".join(
        f"- [{name}]({name}/SKILL.md)" for name in project["skills"]
    )
    return f'''# Project Skills

This directory is synchronized from the canonical skill collection.
Read the matching `SKILL.md` before use. Do not edit generated project copies directly; update the canonical skill, synchronize Obsidian knowledge, and run `sync-all`.

{entries}
'''


def project_lock(project: dict, repo: Path, destination: Path) -> dict:
    files: dict[str, str] = {}
    skills: dict[str, dict[str, str]] = {}
    for skill_name in project["skills"]:
        local_root = destination / skill_name
        for rel, value in tree_files(local_root).items():
            path = (local_root / rel).relative_to(repo).as_posix()
            files[path] = value
        skills[skill_name] = {
            "destination": local_root.relative_to(repo).as_posix(),
            "canonical_hash": tree_hash(collection_root() / skill_name),
        }
    for rel in [
        ".skills/skill_lifecycle.py",
        ".skills/project.json",
        ".githooks/pre-push",
        "AGENTS.md",
        (destination / "INDEX.md").relative_to(repo).as_posix(),
    ]:
        files[rel] = file_hash(repo / rel)
    return {
        "version": 1,
        "project": project["name"],
        "generated": utc_now(),
        "canonical_root": collection_root().as_posix(),
        "vault_path": load_manifest()["vault_path"],
        "knowledge_folder": load_manifest()["knowledge_folder"],
        "skills": skills,
        "files": dict(sorted(files.items())),
        "required_tracked": [".skills/skills-lock.json"],
    }


def stabilize_generated_timestamp(new_lock: dict, old_lock: dict) -> dict:
    previous = dict(old_lock)
    current = dict(new_lock)
    previous.pop("generated", None)
    current.pop("generated", None)
    if previous == current and old_lock.get("generated"):
        new_lock["generated"] = old_lock["generated"]
    return new_lock


def sync_projects(project_names: list[str] | None = None) -> list[Path]:
    manifest = load_manifest()
    touched: list[Path] = []
    for project in select_projects(manifest, project_names):
        repo = workspace_root() / project["path"]
        if not (repo / ".git").exists():
            raise LifecycleError(f"Project is not a Git repository: {repo}")
        destination = repo / project["destination"]
        old_lock_path = repo / ".skills" / "skills-lock.json"
        old_lock = (
            json.loads(old_lock_path.read_text(encoding="utf-8"))
            if old_lock_path.exists()
            else {"files": {}}
        )
        for skill_name in project["skills"]:
            validate_skill(skill_name)
            source = collection_root() / skill_name
            local = destination / skill_name
            prefix = local.relative_to(repo).as_posix() + "/"
            old_files = {
                rel[len(prefix) :]
                for rel in old_lock.get("files", {})
                if rel.startswith(prefix)
            }
            copy_managed_tree(source, local, old_files)
            touched.append(local)

        helper_dir = repo / ".skills"
        helper_dir.mkdir(parents=True, exist_ok=True)
        canonical_script = (
            collection_root()
            / "knowledge-driven-skill-sync"
            / "scripts"
            / "skill_lifecycle.py"
        )
        shutil.copy2(canonical_script, helper_dir / "skill_lifecycle.py")
        project_config = {
            "project": project["name"],
            "canonical_root": collection_root().as_posix(),
            "destination": project["destination"],
            "skills": project["skills"],
        }
        (helper_dir / "project.json").write_text(
            json.dumps(project_config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        hook = repo / ".githooks" / "pre-push"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(hook_text(), encoding="utf-8", newline="\n")
        try:
            hook.chmod(0o755)
        except OSError:
            pass
        update_agent_instructions(repo / "AGENTS.md", project)
        index_path = destination / "INDEX.md"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_content = project_index_text(project)
        if not index_path.exists() or index_path.read_text(encoding="utf-8") != index_content:
            index_path.write_text(index_content, encoding="utf-8", newline="\n")
        lock = stabilize_generated_timestamp(
            project_lock(project, repo, destination), old_lock
        )
        old_lock_path.write_text(
            json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        touched.extend([helper_dir, hook, old_lock_path])
    return touched


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", f"safe.directory={repo.as_posix()}", "-C", str(repo), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def verify_knowledge(lock: dict, errors: list[str]) -> None:
    vault = Path(os.environ.get("OBSIDIAN_VAULT", lock["vault_path"])).resolve()
    folder = vault / lock["knowledge_folder"]
    canonical = Path(lock["canonical_root"])
    for skill_name, metadata in lock["skills"].items():
        note = folder / f"{skill_name}.md"
        if not note.exists():
            errors.append(f"missing Obsidian note: {note}")
            continue
        text = note.read_text(encoding="utf-8")
        note_source_hash = parse_note_field(text, "source_hash")
        input_hash = parse_note_field(text, "knowledge_inputs_hash")
        actual_input_hash = sha256_text(extract_section(text, "Knowledge inputs").strip())
        if input_hash != actual_input_hash:
            errors.append(f"knowledge inputs not pulled for {skill_name}")
        source = canonical / skill_name
        expected = tree_hash(source) if source.exists() else metadata["canonical_hash"]
        if note_source_hash != expected:
            errors.append(f"Obsidian capability note is stale for {skill_name}")


def verify_project(repo: Path, allow_untracked: bool = False) -> None:
    repo = repo.resolve()
    lock_path = repo / ".skills" / "skills-lock.json"
    if not lock_path.exists():
        raise LifecycleError(f"Missing lock file: {lock_path}")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for rel, expected in lock["files"].items():
        path = repo / rel
        if not path.exists():
            errors.append(f"missing managed file: {rel}")
        elif file_hash(path) != expected:
            errors.append(f"stale or modified managed file: {rel}")

    canonical = Path(lock["canonical_root"])
    if canonical.exists():
        for skill_name, metadata in lock["skills"].items():
            source = canonical / skill_name
            if source.exists() and tree_hash(source) != metadata["canonical_hash"]:
                errors.append(f"project copy is stale against canonical skill: {skill_name}")

    verify_knowledge(lock, errors)

    tracked_result = run_git(repo, "ls-files", "-z")
    if tracked_result.returncode != 0:
        errors.append(f"git ls-files failed: {tracked_result.stderr.strip()}")
        tracked: set[str] = set()
    else:
        tracked = {item for item in tracked_result.stdout.split("\0") if item}
    required = set(lock["files"]) | set(lock.get("required_tracked", []))
    missing_tracked = sorted(required - tracked)
    if missing_tracked and not allow_untracked:
        errors.extend(f"managed file is not tracked: {rel}" for rel in missing_tracked)

    status_result = run_git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    if status_result.returncode != 0:
        errors.append(f"git status failed: {status_result.stderr.strip()}")
    elif not allow_untracked:
        for line in status_result.stdout.splitlines():
            if len(line) < 4:
                continue
            path = line[3:].split(" -> ")[-1].replace("\\", "/")
            if path in required:
                errors.append(f"managed file has uncommitted changes: {path}")

    if errors:
        details = "\n  - ".join(errors)
        raise LifecycleError(
            "Skill lifecycle gate failed. Run sync-all, review, and commit:\n  - "
            + details
        )


def install_hooks(project_names: list[str] | None = None) -> None:
    manifest = load_manifest()
    for project in select_projects(manifest, project_names):
        repo = workspace_root() / project["path"]
        result = run_git(repo, "config", "core.hooksPath", ".githooks")
        if result.returncode != 0:
            raise LifecycleError(
                f"Unable to configure hook for {project['name']}: {result.stderr.strip()}"
            )


def record_use(
    skill_name: str,
    project: str,
    summary: str,
    manifest: dict,
    vault_override: str | None = None,
) -> Path:
    if SECRET_PATTERN.search(summary):
        raise LifecycleError("Refusing to record secret-like content")
    summary = " ".join(summary.split())[:800]
    if not summary:
        raise LifecycleError("Usage summary must not be empty")
    vault = resolve_vault(manifest, vault_override)
    sync_knowledge([skill_name], manifest, vault_override)
    note = note_path_for(vault, manifest, skill_name)
    text = note.read_text(encoding="utf-8")
    usage = extract_section(text, "Usage and evolution log")
    if usage == "_No recorded uses yet._":
        usage = ""
    entry = f"- {utc_now()} | `{project}` | {summary}"
    updated_usage = (usage.rstrip() + "\n" + entry).strip()
    pattern = re.compile(
        r"(?ms)^## Usage and evolution log\s*\n.*?(?=^##\s|\Z)"
    )
    text = pattern.sub(f"## Usage and evolution log\n\n{updated_usage}\n", text)
    note.write_text(text, encoding="utf-8", newline="\n")
    return note


def add_knowledge(
    skill_name: str,
    content: str,
    manifest: dict,
    vault_override: str | None = None,
) -> Path:
    if SECRET_PATTERN.search(content):
        raise LifecycleError("Refusing to add secret-like knowledge")
    content = " ".join(content.split())[:1200]
    if not content:
        raise LifecycleError("Knowledge content must not be empty")
    vault = resolve_vault(manifest, vault_override)
    sync_knowledge([skill_name], manifest, vault_override)
    note = note_path_for(vault, manifest, skill_name)
    text = note.read_text(encoding="utf-8")
    knowledge = extract_section(text, "Knowledge inputs")
    knowledge = re.sub(r"<!--.*?-->", "", knowledge, flags=re.DOTALL).strip()
    entry = f"- {content}"
    if entry not in knowledge.splitlines():
        knowledge = (knowledge.rstrip() + "\n" + entry).strip()
    pattern = re.compile(r"(?ms)^## Knowledge inputs\s*\n.*?(?=^##\s|\Z)")
    text = pattern.sub(f"## Knowledge inputs\n\n{knowledge}\n\n", text)
    note.write_text(text, encoding="utf-8", newline="\n")
    return note


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ["pull-knowledge", "sync-knowledge"]:
        command = sub.add_parser(name)
        command.add_argument("--skill", action="append")
        command.add_argument("--vault")

    sync_projects_parser = sub.add_parser("sync-projects")
    sync_projects_parser.add_argument("--project", action="append")

    sync_all_parser = sub.add_parser("sync-all")
    sync_all_parser.add_argument("--skill", action="append")
    sync_all_parser.add_argument("--project", action="append")
    sync_all_parser.add_argument("--vault")

    verify = sub.add_parser("verify-project")
    verify.add_argument("--repo", required=True)
    verify.add_argument("--allow-untracked", action="store_true")

    hooks = sub.add_parser("install-hooks")
    hooks.add_argument("--project", action="append")

    record = sub.add_parser("record-use")
    record.add_argument("--skill", required=True)
    record.add_argument("--project", required=True)
    record.add_argument("--summary", required=True)
    record.add_argument("--vault")

    knowledge = sub.add_parser("add-knowledge")
    knowledge.add_argument("--skill", required=True)
    knowledge.add_argument("--content", required=True)
    knowledge.add_argument("--vault")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        manifest = load_manifest()
        if args.command == "pull-knowledge":
            changed = pull_knowledge(select_skills(args.skill), manifest, args.vault)
            print(f"pulled_knowledge={len(changed)}")
        elif args.command == "sync-knowledge":
            written = sync_knowledge(select_skills(args.skill), manifest, args.vault)
            print(f"knowledge_notes_updated={len(written)}")
        elif args.command == "sync-projects":
            touched = sync_projects(args.project)
            print(f"project_artifacts_touched={len(touched)}")
        elif args.command == "sync-all":
            skills = select_skills(args.skill)
            pulled = pull_knowledge(skills, manifest, args.vault)
            for skill_name in skills:
                validate_skill(skill_name)
            notes = sync_knowledge(skills, manifest, args.vault)
            projects = sync_projects(args.project)
            print(
                f"pulled_knowledge={len(pulled)} "
                f"knowledge_notes_updated={len(notes)} "
                f"project_artifacts_touched={len(projects)}"
            )
        elif args.command == "verify-project":
            verify_project(Path(args.repo), args.allow_untracked)
            print("skill_lifecycle_gate=passed")
        elif args.command == "install-hooks":
            install_hooks(args.project)
            print("hooks_installed=true")
        elif args.command == "record-use":
            note = record_use(
                args.skill, args.project, args.summary, manifest, args.vault
            )
            print(f"usage_recorded={note}")
        elif args.command == "add-knowledge":
            note = add_knowledge(args.skill, args.content, manifest, args.vault)
            print(f"knowledge_added={note}")
        return 0
    except (LifecycleError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
