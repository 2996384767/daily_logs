from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


ROOT_DIR = Path(__file__).resolve().parent
LOGS_DIR = ROOT_DIR / "logs"
README_PATH = ROOT_DIR / "README.md"


@dataclass(frozen=True)
class LogEntry:
    title: str
    created_at: datetime
    tags: list[str]
    path: Path
    summary: str


def split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    normalized = content.lstrip("\ufeff").replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return {}, content

    parts = normalized.split("---\n", 2)
    if len(parts) < 3:
        return {}, content

    raw_frontmatter = parts[1]
    body = parts[2]
    metadata = yaml.safe_load(raw_frontmatter) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return metadata, body


def parse_datetime(value: Any, fallback: datetime) -> datetime:
    if not value:
        return fallback
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return fallback
    return fallback


def normalize_tags(raw_tags: Any) -> list[str]:
    if isinstance(raw_tags, list):
        return sorted({str(tag).strip() for tag in raw_tags if str(tag).strip()})
    if isinstance(raw_tags, str) and raw_tags.strip():
        return [raw_tags.strip()]
    return []


def extract_summary(body: str) -> str:
    for line in body.splitlines():
        cleaned = line.strip().lstrip("-").strip()
        if cleaned and not cleaned.startswith("#"):
            return cleaned
    return "No summary provided."


def load_log_entry(path: Path) -> LogEntry:
    content = path.read_text(encoding="utf-8")
    metadata, body = split_frontmatter(content)
    fallback_dt = datetime.fromtimestamp(path.stat().st_mtime)
    created_at = parse_datetime(metadata.get("created_at"), fallback_dt)
    title = str(metadata.get("title") or path.stem)
    tags = normalize_tags(metadata.get("tags"))
    summary = extract_summary(body)
    return LogEntry(title=title, created_at=created_at, tags=tags, path=path, summary=summary)


def discover_entries(root_dir: Path) -> list[LogEntry]:
    logs_dir = root_dir / "logs"
    entries = [load_log_entry(path) for path in logs_dir.rglob("*.md")]
    return sorted(entries, key=lambda entry: entry.created_at, reverse=True)


def build_timeline(entries: list[LogEntry], root_dir: Path) -> list[str]:
    lines = ["## Timeline", ""]
    if not entries:
        lines.append("No logs yet.")
        return lines

    for entry in entries:
        relative_path = entry.path.relative_to(root_dir).as_posix()
        tag_text = ", ".join(f"`{tag}`" for tag in entry.tags) if entry.tags else "`untagged`"
        lines.append(
            f"- {entry.created_at.strftime('%Y-%m-%d %H:%M')} | "
            f"[{entry.title}]({relative_path}) | {tag_text} | {entry.summary}"
        )
    return lines


def build_latest_entry(entries: list[LogEntry], root_dir: Path) -> list[str]:
    lines = ["## Latest Entry", ""]
    if not entries:
        lines.append("No logs yet.")
        return lines

    entry = entries[0]
    relative_path = entry.path.relative_to(root_dir).as_posix()
    tag_text = ", ".join(f"`{tag}`" for tag in entry.tags) if entry.tags else "`untagged`"
    lines.extend(
        [
            f"### [{entry.title}]({relative_path})",
            "",
            f"- Time: {entry.created_at.strftime('%Y-%m-%d %H:%M')}",
            f"- Tags: {tag_text}",
            f"- Summary: {entry.summary}",
        ]
    )
    return lines


def build_tag_index(entries: list[LogEntry], root_dir: Path) -> list[str]:
    lines = ["## Tag Index", ""]
    tag_map: dict[str, list[LogEntry]] = {}

    for entry in entries:
        effective_tags = entry.tags or ["untagged"]
        for tag in effective_tags:
            tag_map.setdefault(tag, []).append(entry)

    if not tag_map:
        lines.append("No tags yet.")
        return lines

    for tag in sorted(tag_map):
        lines.append(f"### {tag}")
        for entry in tag_map[tag]:
            relative_path = entry.path.relative_to(root_dir).as_posix()
            lines.append(
                f"- {entry.created_at.strftime('%Y-%m-%d %H:%M')} | "
                f"[{entry.title}]({relative_path})"
            )
        lines.append("")

    if lines[-1] == "":
        lines.pop()
    return lines


def generate_readme(root_dir: Path | None = None) -> Path:
    actual_root = root_dir or ROOT_DIR
    entries = discover_entries(actual_root)
    content = [
        "# Auto-DevLog",
        "",
        "A personal development log with clipboard image capture, structured markdown, and git sync.",
        "",
        "## Quick Start",
        "",
        "Desktop one-click entry:",
        "",
        "`C:\\Users\\29963\\Desktop\\Auto-DevLog.lnk`",
        "",
        "Quick mode is the default. Advanced editor mode is still available:",
        "",
        "```powershell",
        r"D:\anaconda3\envs\deeplearning\python.exe main.py new",
        r"D:\anaconda3\envs\deeplearning\python.exe main.py new --mode editor",
        "```",
        "",
        "## Line Endings",
        "",
        "This project standardizes on `LF` to keep Git diffs clean and avoid shell-script issues in WSL2 or Linux.",
        "",
        *build_latest_entry(entries, actual_root),
        "",
        *build_timeline(entries, actual_root),
        "",
        *build_tag_index(entries, actual_root),
        "",
    ]
    readme_path = actual_root / "README.md"
    readme_path.write_text("\n".join(content), encoding="utf-8")
    return readme_path


if __name__ == "__main__":
    generate_readme()
