from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


ROOT_DIR = Path(__file__).resolve().parent
README_PATH = ROOT_DIR / "README.md"
HTML_PATH = ROOT_DIR / "index.html"


@dataclass(frozen=True)
class LogEntry:
    title: str
    created_at: datetime
    updated_at: datetime
    day_key: str
    entry_count: int
    tags: list[str]
    path: Path
    summary: str
    body: str


def split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    normalized = content.lstrip("\ufeff").replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return {}, content
    parts = normalized.split("---\n", 2)
    if len(parts) < 3:
        return {}, content
    metadata = yaml.safe_load(parts[1]) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return metadata, parts[2]


def parse_datetime(value: Any, fallback: datetime) -> datetime:
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
    updated_at = parse_datetime(metadata.get("updated_at"), created_at)
    day_key = str(metadata.get("day_key") or created_at.strftime("%Y-%m-%d"))
    title = str(metadata.get("title") or path.stem)
    tags = normalize_tags(metadata.get("tags"))
    try:
        entry_count = int(metadata.get("entry_count", 1))
    except (TypeError, ValueError):
        entry_count = 1
    return LogEntry(
        title=title,
        created_at=created_at,
        updated_at=updated_at,
        day_key=day_key,
        entry_count=max(entry_count, 1),
        tags=tags,
        path=path,
        summary=extract_summary(body),
        body=body,
    )


def discover_entries(root_dir: Path) -> list[LogEntry]:
    logs_dir = root_dir / "logs"
    entries = [load_log_entry(path) for path in logs_dir.rglob("*.md")]
    return sorted(entries, key=lambda entry: entry.updated_at, reverse=True)


def group_entries_by_day(entries: list[LogEntry]) -> list[tuple[str, list[LogEntry]]]:
    grouped: dict[str, list[LogEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.day_key, []).append(entry)
    return [(day, grouped[day]) for day in sorted(grouped, reverse=True)]


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
            f"- Created: {entry.created_at.strftime('%Y-%m-%d %H:%M')}",
            f"- Updated: {entry.updated_at.strftime('%Y-%m-%d %H:%M')}",
            f"- Entries Today: {entry.entry_count}",
            f"- Tags: {tag_text}",
            f"- Summary: {entry.summary}",
        ]
    )
    return lines


def build_daily_timeline(entries: list[LogEntry], root_dir: Path) -> list[str]:
    lines = ["## Daily Timeline", ""]
    if not entries:
        lines.append("No logs yet.")
        return lines
    for day_key, day_entries in group_entries_by_day(entries):
        total_updates = sum(entry.entry_count for entry in day_entries)
        lines.append(f"### {day_key} ({len(day_entries)} files, {total_updates} updates)")
        for entry in day_entries:
            relative_path = entry.path.relative_to(root_dir).as_posix()
            tag_text = ", ".join(f"`{tag}`" for tag in entry.tags) if entry.tags else "`untagged`"
            lines.append(
                f"- {entry.updated_at.strftime('%H:%M')} | "
                f"[{entry.title}]({relative_path}) | "
                f"{entry.entry_count} entries | {tag_text} | {entry.summary}"
            )
        lines.append("")
    if lines[-1] == "":
        lines.pop()
    return lines


def build_tag_index(entries: list[LogEntry], root_dir: Path) -> list[str]:
    lines = ["## Tag Index", ""]
    tag_map: dict[str, list[LogEntry]] = {}
    for entry in entries:
        for tag in entry.tags or ["untagged"]:
            tag_map.setdefault(tag, []).append(entry)
    if not tag_map:
        lines.append("No tags yet.")
        return lines
    for tag in sorted(tag_map):
        lines.append(f"### {tag} ({len(tag_map[tag])})")
        for entry in sorted(tag_map[tag], key=lambda item: item.updated_at, reverse=True):
            relative_path = entry.path.relative_to(root_dir).as_posix()
            lines.append(
                f"- {entry.updated_at.strftime('%Y-%m-%d %H:%M')} | "
                f"[{entry.title}]({relative_path})"
            )
        lines.append("")
    if lines[-1] == "":
        lines.pop()
    return lines


def extract_sections(body: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_title = "正文"
    current_lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("#"):
            if current_lines:
                sections.append((current_title, current_lines))
            current_title = line.lstrip("#").strip() or "正文"
            current_lines = []
            continue
        if line:
            current_lines.append(line)
    if current_lines:
        sections.append((current_title, current_lines))
    return sections


def render_line_html(line: str) -> str:
    text = line[2:].strip() if line.startswith("- ") else line
    escaped = html.escape(text)
    return re.sub(r"!\[[^\]]*\]\(([^)]+)\)", r"<a href='\1'>Image</a>", escaped)


def render_body_html(body: str) -> str:
    chunks: list[str] = []
    for title, lines in extract_sections(body):
        items = "".join(f"<li>{render_line_html(line)}</li>" for line in lines)
        chunks.append(
            "<section class='entry-section'>"
            f"<h4>{html.escape(title)}</h4>"
            f"<ul>{items}</ul>"
            "</section>"
        )
    return "".join(chunks) or "<p>No details yet.</p>"


def build_html(entries: list[LogEntry], root_dir: Path) -> str:
    latest_html = "<p>No logs yet.</p>"
    if entries:
        latest = entries[0]
        latest_href = latest.path.relative_to(root_dir).as_posix()
        latest_tags = " ".join(f"<span class='tag'>{html.escape(tag)}</span>" for tag in latest.tags or ["untagged"])
        latest_html = (
            f"<article class='card latest'>"
            f"<h2><a href='{html.escape(latest_href)}'>{html.escape(latest.title)}</a></h2>"
            f"<p class='meta'>Created {latest.created_at:%Y-%m-%d %H:%M} &middot; Updated {latest.updated_at:%Y-%m-%d %H:%M}</p>"
            f"<p class='meta'>Entries today: {latest.entry_count}</p>"
            f"<p>{html.escape(latest.summary)}</p>"
            f"<div class='tags'>{latest_tags}</div>"
            f"<div class='detail-stack'>{render_body_html(latest.body)}</div>"
            f"</article>"
        )

    day_sections: list[str] = []
    for day_key, day_entries in group_entries_by_day(entries):
        day_total = sum(entry.entry_count for entry in day_entries)
        cards: list[str] = []
        for entry in day_entries:
            href = entry.path.relative_to(root_dir).as_posix()
            tags = " ".join(f"<span class='tag'>{html.escape(tag)}</span>" for tag in entry.tags or ["untagged"])
            cards.append(
                f"<article class='card'>"
                f"<h3><a href='{html.escape(href)}'>{html.escape(entry.title)}</a></h3>"
                f"<p class='meta'>{entry.updated_at:%H:%M} &middot; {entry.entry_count} entries</p>"
                f"<p>{html.escape(entry.summary)}</p>"
                f"<div class='tags'>{tags}</div>"
                f"<details class='detail-box'><summary>展开记录详情</summary>{render_body_html(entry.body)}</details>"
                f"</article>"
            )
        day_sections.append(
            f"<section class='day-section'>"
            f"<div class='day-header'><h2>{html.escape(day_key)}</h2><p class='meta'>{len(day_entries)} files &middot; {day_total} total updates</p></div>"
            f"<div class='grid'>{''.join(cards)}</div>"
            f"</section>"
        )

    tag_counts: dict[str, int] = {}
    for entry in entries:
        for tag in entry.tags or ["untagged"]:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    tag_html = "".join(
        f"<span class='tag tag-wall'>{html.escape(tag)} <strong>{count}</strong></span>"
        for tag, count in sorted(tag_counts.items())
    ) or "<p>No tags yet.</p>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Auto-DevLog</title>
  <style>
    :root {{
      --bg: #f6f3ec;
      --paper: #fffdf8;
      --ink: #1f1c18;
      --muted: #6f675e;
      --accent: #b55233;
      --line: #ded5c9;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, #f2e6d6 0, transparent 30%),
        linear-gradient(180deg, #faf7f1 0%, var(--bg) 100%);
    }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 40px 20px 80px; }}
    h1, h2, h3, h4 {{ margin: 0 0 12px; }}
    header {{ margin-bottom: 28px; }}
    p {{ line-height: 1.6; }}
    a {{ color: var(--accent); text-decoration: none; }}
    .meta {{ color: var(--muted); font-size: 0.95rem; }}
    .card {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 8px 24px rgba(48, 39, 27, 0.06);
    }}
    .latest {{ margin-bottom: 28px; }}
    .detail-stack {{
      margin-top: 18px;
      display: grid;
      gap: 14px;
    }}
    .entry-section {{
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }}
    .entry-section ul {{
      margin: 0;
      padding-left: 18px;
      line-height: 1.7;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
    }}
    section {{ margin-top: 26px; }}
    .day-header {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 16px;
      margin-bottom: 14px;
    }}
    .tags {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
    .tag {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      background: #f3e1d8;
      color: #7f341e;
      font-size: 0.9rem;
    }}
    .tag-wall {{ margin-right: 8px; margin-bottom: 8px; }}
    .detail-box {{
      margin-top: 14px;
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }}
    .detail-box summary {{
      cursor: pointer;
      color: var(--accent);
      font-weight: 600;
      margin-bottom: 10px;
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Auto-DevLog</h1>
      <p class="meta">A day-grouped development journal with quick capture, appendable daily logs, and GitHub-friendly archives.</p>
    </header>
    <section>
      <h2>Latest Entry</h2>
      {latest_html}
    </section>
    <section>
      <h2>Tag Wall</h2>
      <div class="tags">{tag_html}</div>
    </section>
    {''.join(day_sections) or "<section><h2>Timeline</h2><p>No logs yet.</p></section>"}
  </main>
</body>
</html>
"""


def generate_outputs(root_dir: Path | None = None) -> tuple[Path, Path]:
    actual_root = root_dir or ROOT_DIR
    entries = discover_entries(actual_root)
    content = [
        "# Auto-DevLog",
        "",
        "A personal development log with clipboard image capture, structured markdown, HTML browsing, and git sync.",
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
        "## Primary View",
        "",
        "- Main browsing page: `index.html`",
        "- GitHub-friendly index: `README.md`",
        "",
        *build_latest_entry(entries, actual_root),
        "",
        *build_daily_timeline(entries, actual_root),
        "",
        *build_tag_index(entries, actual_root),
        "",
    ]
    readme_path = actual_root / "README.md"
    readme_path.write_text("\n".join(content), encoding="utf-8")

    html_path = actual_root / "index.html"
    html_path.write_text(build_html(entries, actual_root), encoding="utf-8")
    return readme_path, html_path


if __name__ == "__main__":
    generate_outputs()
