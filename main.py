from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

import click
import yaml

import generator


ROOT_DIR = Path(__file__).resolve().parent
LOGS_DIR = ROOT_DIR / "logs"
ASSETS_DIR = ROOT_DIR / "assets"
TEMPLATE_PATH = ROOT_DIR / "template.md"
TEMP_LOG_PATH = ROOT_DIR / "temp_log.md"
README_PATH = ROOT_DIR / "README.md"
HTML_PATH = ROOT_DIR / "index.html"
CONFIG_PATH = ROOT_DIR / "autodevlog.json"
SKIP_SYNC_ENV = "AUTODEVLOG_SKIP_SYNC"
SKIP_TOKENS = {".", "/skip"}

DEFAULT_TEMPLATE = """---
title: ""
created_at: "{timestamp}"
updated_at: "{timestamp}"
day_key: "{day_key}"
entry_count: 1
tags: []
---

## 核心产出

- 

## 踩坑记录

- 

## 灵感与碎片

- 
"""

DEFAULT_CONFIG = {
    "editor": "code --wait",
    "default_mode": "quick",
    "open_after_save": "readme",
    "auto_sync": True,
}


@dataclass(frozen=True)
class AppConfig:
    editor: str
    default_mode: str
    open_after_save: str
    auto_sync: bool


@dataclass(frozen=True)
class ClipboardImageResult:
    asset_path: Path
    markdown: str


@dataclass(frozen=True)
class QuickLogAnswers:
    title: str
    tags: list[str]
    core_work: str
    learned: str
    solved: str
    unresolved: str
    interesting: str


@dataclass(frozen=True)
class ParsedLogDocument:
    metadata: dict[str, Any]
    body: str


@dataclass(frozen=True)
class SyncResult:
    attempted: bool
    success: bool
    message: str


class AutoDevLogError(RuntimeError):
    """Raised when the CLI cannot complete a requested operation."""


def configure_console_encoding() -> None:
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raw_config = DEFAULT_CONFIG
    else:
        raw_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    if not isinstance(raw_config, dict):
        raise AutoDevLogError("autodevlog.json must contain a JSON object.")

    merged = {**DEFAULT_CONFIG, **raw_config}
    default_mode = str(merged.get("default_mode", "quick")).lower()
    if default_mode not in {"quick", "editor"}:
        default_mode = "quick"

    open_after_save = str(merged.get("open_after_save", "readme")).lower()
    if open_after_save not in {"readme", "html"}:
        open_after_save = "readme"

    return AppConfig(
        editor=str(merged.get("editor", DEFAULT_CONFIG["editor"])).strip() or DEFAULT_CONFIG["editor"],
        default_mode=default_mode,
        open_after_save=open_after_save,
        auto_sync=bool(merged.get("auto_sync", True)),
    )


def ensure_project_structure() -> AppConfig:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    if not TEMPLATE_PATH.exists():
        TEMPLATE_PATH.write_text(DEFAULT_TEMPLATE, encoding="utf-8")
    if not README_PATH.exists():
        README_PATH.write_text("# Auto-DevLog\n", encoding="utf-8")
    return load_config()


def current_log_paths(now: datetime) -> tuple[Path, Path]:
    log_dir = LOGS_DIR / now.strftime("%Y") / now.strftime("%m")
    asset_dir = ASSETS_DIR / now.strftime("%Y") / now.strftime("%m")
    return log_dir, asset_dir


def find_latest_log_for_day(now: datetime) -> Path | None:
    log_dir, _ = current_log_paths(now)
    if not log_dir.exists():
        return None
    prefix = f"{now.strftime('%Y-%m-%d')}_"
    candidates = sorted(log_dir.glob(f"{prefix}*.md"))
    return candidates[-1] if candidates else None


def detect_clipboard_image(now: datetime) -> ClipboardImageResult | None:
    try:
        from PIL import ImageGrab
        import pyperclip
    except ImportError as exc:
        raise AutoDevLogError(f"Clipboard support is unavailable: {exc}") from exc

    try:
        image = ImageGrab.grabclipboard()
    except Exception as exc:  # pragma: no cover
        raise AutoDevLogError(f"Failed to access clipboard: {exc}") from exc

    if image is None or not hasattr(image, "save"):
        return None

    _, asset_dir = current_log_paths(now)
    asset_dir.mkdir(parents=True, exist_ok=True)
    asset_name = f"img_{now.strftime('%Y%m%d_%H%M%S')}.png"
    asset_path = asset_dir / asset_name
    image.save(asset_path, format="PNG")

    relative_asset = Path("../../../assets") / now.strftime("%Y") / now.strftime("%m") / asset_name
    markdown = f"![Pasted Image]({relative_asset.as_posix()})"
    pyperclip.copy(markdown)
    return ClipboardImageResult(asset_path=asset_path, markdown=markdown)


def build_temp_log_content(now: datetime) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return (
        template.replace("{timestamp}", now.isoformat(timespec="seconds"))
        .replace("{day_key}", now.strftime("%Y-%m-%d"))
    )


def choose_editor(config: AppConfig) -> list[str]:
    configured = os.getenv("AUTODEVLOG_EDITOR", "").strip()
    editor = configured or config.editor
    parts = shlex.split(editor, posix=False)
    executable = shutil.which(parts[0])
    if executable:
        parts[0] = executable
        return parts

    fallback = shutil.which("notepad")
    if fallback:
        return [fallback]

    raise AutoDevLogError("No usable editor found. Set AUTODEVLOG_EDITOR or update autodevlog.json.")


def open_editor(file_path: Path, config: AppConfig) -> None:
    editor_cmd = choose_editor(config)
    subprocess.run([*editor_cmd, str(file_path)], check=True, cwd=ROOT_DIR)


def normalize_skip_value(value: str) -> str:
    stripped = value.strip()
    if stripped in SKIP_TOKENS:
        return ""
    return stripped


def prompt_text(label: str) -> str:
    return normalize_skip_value(click.prompt(label, default="", show_default=False))


def prompt_for_tags(default_tags: list[str]) -> list[str]:
    default_text = ", ".join(default_tags)
    raw_tags = click.prompt(
        "标签（留空默认沿用上次，输入 /clear 清空）",
        default=default_text,
        show_default=bool(default_text),
    ).strip()

    if raw_tags in SKIP_TOKENS or raw_tags == default_text:
        raw_tags = default_text
    if raw_tags == "/clear":
        return []

    tags: list[str] = []
    seen: set[str] = set()
    normalized = raw_tags.replace("，", ",")
    for part in normalized.split(","):
        tag = part.strip()
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tags


def derive_title(answers: QuickLogAnswers) -> str:
    if answers.title:
        return answers.title
    for candidate in (
        answers.core_work,
        answers.learned,
        answers.solved,
        answers.unresolved,
        answers.interesting,
    ):
        if candidate.strip():
            return candidate.strip()[:28]
    return "Quick Dev Log"


def build_bullet_lines(items: list[str], empty_text: str) -> list[str]:
    lines = [f"- {item}" for item in items if item.strip()]
    return lines or [f"- {empty_text}"]


def parse_log_document(content: str) -> ParsedLogDocument:
    normalized = content.lstrip("\ufeff").replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return ParsedLogDocument(metadata={}, body=normalized)
    parts = normalized.split("---\n", 2)
    if len(parts) < 3:
        return ParsedLogDocument(metadata={}, body=normalized)
    metadata = yaml.safe_load(parts[1]) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return ParsedLogDocument(metadata=metadata, body=parts[2].lstrip("\n"))


def get_default_tags(existing_log_path: Path | None) -> list[str]:
    if existing_log_path is None:
        return []
    parsed = parse_log_document(existing_log_path.read_text(encoding="utf-8"))
    raw_tags = parsed.metadata.get("tags")
    if isinstance(raw_tags, list):
        return [str(tag).strip() for tag in raw_tags if str(tag).strip()]
    return []


def prompt_for_quick_answers(default_tags: list[str]) -> QuickLogAnswers:
    click.echo("直接输入今天的要点，回车可跳过某项。输入 . 或 /skip 也可以快速略过。")
    core_work = prompt_text("今天主要做了什么")
    learned = prompt_text("学到了什么")
    solved = prompt_text("解决了什么问题")
    unresolved = prompt_text("还有什么没解决")
    interesting = prompt_text("发现了什么有意思的东西")
    tags = prompt_for_tags(default_tags)
    title = prompt_text("这条记录的标题（可留空自动生成）")

    answers = QuickLogAnswers(
        title=title,
        tags=tags,
        core_work=core_work,
        learned=learned,
        solved=solved,
        unresolved=unresolved,
        interesting=interesting,
    )

    if not any((core_work, learned, solved, unresolved, interesting)):
        raise AutoDevLogError("没有输入任何内容，本次记录已取消。")
    return answers


def build_quick_log_content(
    now: datetime,
    answers: QuickLogAnswers,
    clipboard_result: ClipboardImageResult | None,
) -> str:
    title = derive_title(answers).replace('"', '\\"')
    idea_items = [answers.interesting]
    if clipboard_result:
        idea_items.append(f"剪贴板图片已接管：{clipboard_result.markdown}")

    metadata = {
        "title": title,
        "created_at": now.isoformat(timespec="seconds"),
        "updated_at": now.isoformat(timespec="seconds"),
        "day_key": now.strftime("%Y-%m-%d"),
        "entry_count": 1,
        "tags": answers.tags,
    }
    body_lines = [
        "## 核心产出",
        "",
        *build_bullet_lines([answers.core_work, answers.learned], "今天先快速记一下，稍后可以补充细节。"),
        "",
        "## 踩坑记录",
        "",
        *build_bullet_lines([answers.solved, answers.unresolved], "今天没有特别要补充的问题记录。"),
        "",
        "## 灵感与碎片",
        "",
        *build_bullet_lines(idea_items, "今天还没有额外的灵感碎片。"),
        "",
    ]
    return dump_log_document(metadata, "\n".join(body_lines))


def build_append_section(
    now: datetime,
    answers: QuickLogAnswers,
    clipboard_result: ClipboardImageResult | None,
) -> str:
    idea_items = [answers.interesting]
    if clipboard_result:
        idea_items.append(f"剪贴板图片已接管：{clipboard_result.markdown}")
    section_lines = [
        "",
        "---",
        "",
        f"## {now.strftime('%H:%M')} 追加记录",
        "",
        "### 核心产出",
        "",
        *build_bullet_lines([answers.core_work, answers.learned], "这次补充里没有新的核心产出。"),
        "",
        "### 踩坑记录",
        "",
        *build_bullet_lines([answers.solved, answers.unresolved], "这次补充里没有新的问题记录。"),
        "",
        "### 灵感与碎片",
        "",
        *build_bullet_lines(idea_items, "这次补充里没有新的灵感碎片。"),
        "",
    ]
    return "\n".join(section_lines)


def build_editor_append_scaffold(now: datetime, clipboard_result: ClipboardImageResult | None) -> str:
    image_hint = clipboard_result.markdown if clipboard_result else ""
    section_lines = [
        "",
        "---",
        "",
        f"## {now.strftime('%H:%M')} 追加记录",
        "",
        "### 核心产出",
        "",
        "- ",
        "",
        "### 踩坑记录",
        "",
        "- ",
        "",
        "### 灵感与碎片",
        "",
        "- ",
    ]
    if image_hint:
        section_lines.extend(["", image_hint])
    section_lines.append("")
    return "\n".join(section_lines)


def merge_tags(existing_tags: Any, new_tags: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    if isinstance(existing_tags, list):
        for tag in existing_tags:
            normalized = str(tag).strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                merged.append(normalized)
    for tag in new_tags:
        normalized = tag.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            merged.append(normalized)
    return merged


def dump_log_document(metadata: dict[str, Any], body: str) -> str:
    yaml_text = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    return f"---\n{yaml_text}\n---\n\n{body.strip()}\n"


def archive_content(now: datetime, content: str) -> Path:
    log_dir, _ = current_log_paths(now)
    log_dir.mkdir(parents=True, exist_ok=True)
    target_path = log_dir / f"{now.strftime('%Y-%m-%d_%H%M')}.md"
    target_path.write_text(content, encoding="utf-8")
    return target_path


def build_quick_preview(now: datetime, answers: QuickLogAnswers, appended: bool) -> str:
    lines = [
        f"时间：{now.strftime('%Y-%m-%d %H:%M')}",
        f"模式：{'追加到当天日志' if appended else '创建当天新日志'}",
        f"标题：{derive_title(answers)}",
        f"标签：{', '.join(answers.tags) if answers.tags else '无'}",
    ]
    for label, value in (
        ("工作", answers.core_work),
        ("学习", answers.learned),
        ("解决", answers.solved),
        ("未解决", answers.unresolved),
        ("有趣发现", answers.interesting),
    ):
        if value:
            lines.append(f"{label}：{value}")
    return "\n".join(lines)


def update_existing_log(
    log_path: Path,
    now: datetime,
    answers: QuickLogAnswers,
    clipboard_result: ClipboardImageResult | None,
) -> Path:
    parsed = parse_log_document(log_path.read_text(encoding="utf-8"))
    metadata = dict(parsed.metadata)
    metadata["updated_at"] = now.isoformat(timespec="seconds")
    metadata["day_key"] = metadata.get("day_key") or now.strftime("%Y-%m-%d")
    metadata["entry_count"] = int(metadata.get("entry_count", 1)) + 1
    metadata["tags"] = merge_tags(metadata.get("tags"), answers.tags)
    if answers.title and not metadata.get("title"):
        metadata["title"] = answers.title
    if not metadata.get("created_at"):
        metadata["created_at"] = now.isoformat(timespec="seconds")

    updated_body = parsed.body.rstrip() + build_append_section(now, answers, clipboard_result)
    log_path.write_text(dump_log_document(metadata, updated_body), encoding="utf-8")
    return log_path


def write_existing_log_from_temp(
    log_path: Path,
    now: datetime,
    updated_content: str,
) -> Path:
    parsed = parse_log_document(updated_content)
    metadata = dict(parsed.metadata)
    metadata["updated_at"] = now.isoformat(timespec="seconds")
    metadata["day_key"] = metadata.get("day_key") or now.strftime("%Y-%m-%d")
    metadata["entry_count"] = int(metadata.get("entry_count", 1)) + 1
    metadata["tags"] = merge_tags(metadata.get("tags"), [])
    rewritten = dump_log_document(metadata, parsed.body)
    log_path.write_text(rewritten, encoding="utf-8")
    return log_path


def archive_temp_log(now: datetime, original_content: str) -> Path | None:
    updated_content = TEMP_LOG_PATH.read_text(encoding="utf-8")
    if updated_content == original_content:
        TEMP_LOG_PATH.unlink(missing_ok=True)
        return None
    return archive_content(now, updated_content)


def run_git_command(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )


def sync_git(now: datetime, config: AppConfig) -> SyncResult:
    if os.getenv(SKIP_SYNC_ENV, "").strip().lower() in {"1", "true", "yes"}:
        return SyncResult(attempted=False, success=False, message="已跳过 Git 同步（测试模式）。")
    if not config.auto_sync:
        return SyncResult(attempted=False, success=False, message="已跳过 Git 同步（配置关闭）。")

    commands: Iterable[Sequence[str]] = (
        ("git", "add", "."),
        ("git", "commit", "-m", f"Auto-log: {now.strftime('%Y-%m-%d %H:%M')}"),
        ("git", "pull", "--rebase", "origin", "main"),
        ("git", "push", "origin", "main"),
    )

    for command in commands:
        result = run_git_command(command)
        if result.returncode == 0:
            continue
        stdout = result.stdout.lower()
        stderr = result.stderr.lower()
        if command[1] == "commit" and "nothing to commit" in f"{stdout}\n{stderr}":
            return SyncResult(attempted=True, success=True, message="Git 没有新增变更，已跳过 commit。")
        if command[1] in {"pull", "push"}:
            details = result.stderr.strip() or result.stdout.strip()
            message = "Git 同步未完成，本地记录已保留，稍后可继续同步。"
            if details:
                message = f"{message}\n{details}"
            return SyncResult(attempted=True, success=False, message=message)
        message = result.stderr.strip() or result.stdout.strip() or "Unknown git error."
        raise AutoDevLogError(f"Git command failed: {' '.join(command)}\n{message}")
    return SyncResult(attempted=True, success=True, message="GitHub 已同步成功。")


def build_feedback(
    archived_path: Path,
    appended: bool,
    sync_result: SyncResult,
    view_path: Path,
) -> str:
    action = "追加完成" if appended else "记录完成"
    lines = [
        "",
        "==== Auto-DevLog ====",
        f"状态：{action}",
        f"日志：{archived_path.relative_to(ROOT_DIR).as_posix()}",
        f"查看：{view_path.name}",
        f"同步：{sync_result.message}",
        "=====================",
    ]
    return "\n".join(lines)


def get_view_path(config: AppConfig) -> Path:
    return HTML_PATH if config.open_after_save == "html" else README_PATH


def finalize_log(now: datetime, archived_path: Path, appended: bool, config: AppConfig) -> None:
    generator.generate_outputs(ROOT_DIR)
    sync_result = sync_git(now, config)
    click.echo(build_feedback(archived_path, appended, sync_result, get_view_path(config)))


def run_quick_mode(now: datetime, clipboard_result: ClipboardImageResult | None, config: AppConfig) -> None:
    existing_log_path = find_latest_log_for_day(now)
    answers = prompt_for_quick_answers(get_default_tags(existing_log_path))
    click.echo()
    click.echo(build_quick_preview(now, answers, appended=existing_log_path is not None))
    if not click.confirm("保存这次记录？", default=True):
        raise AutoDevLogError("本次记录已取消。")

    if existing_log_path is not None:
        archived_path = update_existing_log(existing_log_path, now, answers, clipboard_result)
        finalize_log(now, archived_path, appended=True, config=config)
        return

    content = build_quick_log_content(now, answers, clipboard_result)
    archived_path = archive_content(now, content)
    finalize_log(now, archived_path, appended=False, config=config)


def run_editor_mode(now: datetime, clipboard_result: ClipboardImageResult | None, config: AppConfig) -> None:
    if clipboard_result:
        click.echo("检测到剪贴板图片，Markdown 链接已复制，可在编辑器中直接粘贴。")

    existing_log_path = find_latest_log_for_day(now)
    if existing_log_path is not None:
        original_content = existing_log_path.read_text(encoding="utf-8")
        scaffold_content = original_content.rstrip() + build_editor_append_scaffold(now, clipboard_result)
        TEMP_LOG_PATH.write_text(scaffold_content, encoding="utf-8")
        try:
            open_editor(TEMP_LOG_PATH, config)
            updated_content = TEMP_LOG_PATH.read_text(encoding="utf-8")
            if updated_content == scaffold_content:
                click.echo("No changes detected. Existing log left untouched.")
                return
            archived_path = write_existing_log_from_temp(existing_log_path, now, updated_content)
            finalize_log(now, archived_path, appended=True, config=config)
        finally:
            TEMP_LOG_PATH.unlink(missing_ok=True)
        return

    content = build_temp_log_content(now)
    TEMP_LOG_PATH.write_text(content, encoding="utf-8")
    try:
        open_editor(TEMP_LOG_PATH, config)
        archived_path = archive_temp_log(now, content)
        if archived_path is None:
            click.echo("No changes detected. Temporary log discarded.")
            return
        finalize_log(now, archived_path, appended=False, config=config)
    finally:
        TEMP_LOG_PATH.unlink(missing_ok=True)


@click.group()
def cli() -> None:
    """Auto-DevLog CLI."""


@cli.command()
def init() -> None:
    """Initialize the project structure."""
    ensure_project_structure()
    generator.generate_outputs(ROOT_DIR)
    click.echo("Auto-DevLog initialized.")


@cli.command()
def generate() -> None:
    """Regenerate README.md and index.html from the log archive."""
    ensure_project_structure()
    generator.generate_outputs(ROOT_DIR)
    click.echo("README.md and index.html regenerated.")


@cli.command(name="view-path")
def view_path_command() -> None:
    """Print the configured result page path for launchers."""
    config = ensure_project_structure()
    click.echo(str(get_view_path(config)))


@cli.command()
@click.option(
    "--mode",
    type=click.Choice(["quick", "editor"], case_sensitive=False),
    default=None,
    help="Choose the fast prompt flow or the advanced editor flow.",
)
def new(mode: str | None) -> None:
    """Create a new development log entry."""
    config = ensure_project_structure()
    now = datetime.now()
    selected_mode = (mode or config.default_mode).lower()
    clipboard_result = detect_clipboard_image(now)
    if clipboard_result:
        click.echo("检测到剪贴板图片，已自动保存并接管链接。")
    if selected_mode == "editor":
        run_editor_mode(now, clipboard_result, config)
        return
    run_quick_mode(now, clipboard_result, config)


def main() -> int:
    configure_console_encoding()
    try:
        cli(standalone_mode=False)
    except AutoDevLogError as exc:
        click.echo(f"Error: {exc}", err=True)
        return 1
    except subprocess.CalledProcessError as exc:
        click.echo(f"Editor exited unexpectedly: {exc}", err=True)
        return 1
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except KeyboardInterrupt:
        click.echo("Interrupted by user.", err=True)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
