from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

import click

import generator


ROOT_DIR = Path(__file__).resolve().parent
LOGS_DIR = ROOT_DIR / "logs"
ASSETS_DIR = ROOT_DIR / "assets"
TEMPLATE_PATH = ROOT_DIR / "template.md"
TEMP_LOG_PATH = ROOT_DIR / "temp_log.md"
README_PATH = ROOT_DIR / "README.md"
DEFAULT_EDITOR = "code --wait"
SKIP_SYNC_ENV = "AUTODEVLOG_SKIP_SYNC"

DEFAULT_TEMPLATE = """---
title: ""
created_at: "{timestamp}"
tags: []
---

## 核心产出

- 

## 踩坑记录

- 

## 灵感与碎片

- 
"""


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


class AutoDevLogError(RuntimeError):
    """Raised when the CLI cannot complete a requested operation."""


def configure_console_encoding() -> None:
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def ensure_project_structure() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    if not TEMPLATE_PATH.exists():
        TEMPLATE_PATH.write_text(DEFAULT_TEMPLATE, encoding="utf-8")
    if not README_PATH.exists():
        README_PATH.write_text("# Auto-DevLog\n", encoding="utf-8")


def current_log_paths(now: datetime) -> tuple[Path, Path]:
    log_dir = LOGS_DIR / now.strftime("%Y") / now.strftime("%m")
    asset_dir = ASSETS_DIR / now.strftime("%Y") / now.strftime("%m")
    return log_dir, asset_dir


def detect_clipboard_image(now: datetime) -> ClipboardImageResult | None:
    try:
        from PIL import ImageGrab
        import pyperclip
    except ImportError as exc:
        raise AutoDevLogError(f"Clipboard support is unavailable: {exc}") from exc

    try:
        image = ImageGrab.grabclipboard()
    except Exception as exc:  # pragma: no cover - platform dependent branch
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
    return template.replace("{timestamp}", now.isoformat(timespec="seconds"))


def choose_editor() -> list[str]:
    configured = os.getenv("AUTODEVLOG_EDITOR", "").strip()
    editor = configured or DEFAULT_EDITOR
    parts = shlex.split(editor, posix=False)
    executable = shutil.which(parts[0])
    if executable:
        parts[0] = executable
        return parts

    fallback = shutil.which("notepad")
    if fallback:
        return [fallback]

    raise AutoDevLogError(
        "No usable editor found. Set AUTODEVLOG_EDITOR, for example: code --wait"
    )


def open_editor(file_path: Path) -> None:
    editor_cmd = choose_editor()
    subprocess.run([*editor_cmd, str(file_path)], check=True, cwd=ROOT_DIR)


def prompt_text(label: str) -> str:
    return click.prompt(label, default="", show_default=False).strip()


def prompt_for_tags() -> list[str]:
    raw_tags = click.prompt("标签（可留空，逗号分隔）", default="", show_default=False).strip()
    if not raw_tags:
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
        text = candidate.strip()
        if text:
            return text[:28]
    return "Quick Dev Log"


def build_bullet_lines(items: list[str], empty_text: str) -> list[str]:
    lines = [f"- {item}" for item in items if item.strip()]
    if lines:
        return lines
    return [f"- {empty_text}"]


def prompt_for_quick_answers() -> QuickLogAnswers:
    click.echo("直接输入今天的要点，回车可跳过某项。")
    core_work = prompt_text("今天主要做了什么")
    learned = prompt_text("学到了什么")
    solved = prompt_text("解决了什么问题")
    unresolved = prompt_text("还有什么没解决")
    interesting = prompt_text("发现了什么有意思的东西")
    tags = prompt_for_tags()
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

    has_content = any(
        (
            answers.core_work,
            answers.learned,
            answers.solved,
            answers.unresolved,
            answers.interesting,
        )
    )
    if not has_content:
        raise AutoDevLogError("没有输入任何内容，本次记录已取消。")
    return answers


def build_quick_log_content(
    now: datetime,
    answers: QuickLogAnswers,
    clipboard_result: ClipboardImageResult | None,
) -> str:
    title = derive_title(answers).replace('"', '\\"')
    tags_literal = ", ".join(answers.tags)
    tags_line = f"[{tags_literal}]" if tags_literal else "[]"

    core_lines = build_bullet_lines(
        [answers.core_work, answers.learned],
        "今天先快速记一下，稍后可以补充细节。",
    )
    pitfall_lines = build_bullet_lines(
        [answers.solved, answers.unresolved],
        "今天没有特别要补充的问题记录。",
    )

    idea_items = [answers.interesting]
    if clipboard_result:
        idea_items.append(f"剪贴板图片已接管：{clipboard_result.markdown}")
    idea_lines = build_bullet_lines(
        idea_items,
        "今天还没有额外的灵感碎片。",
    )

    content_lines = [
        "---",
        f'title: "{title}"',
        f'created_at: "{now.isoformat(timespec="seconds")}"',
        f"tags: {tags_line}",
        "---",
        "",
        "## 核心产出",
        "",
        *core_lines,
        "",
        "## 踩坑记录",
        "",
        *pitfall_lines,
        "",
        "## 灵感与碎片",
        "",
        *idea_lines,
        "",
    ]
    return "\n".join(content_lines)


def archive_content(now: datetime, content: str) -> Path:
    log_dir, _ = current_log_paths(now)
    log_dir.mkdir(parents=True, exist_ok=True)
    target_path = log_dir / f"{now.strftime('%Y-%m-%d_%H%M')}.md"
    target_path.write_text(content, encoding="utf-8")
    return target_path


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


def sync_git(now: datetime) -> None:
    if os.getenv(SKIP_SYNC_ENV, "").strip().lower() in {"1", "true", "yes"}:
        click.echo("Git sync skipped because AUTODEVLOG_SKIP_SYNC is enabled.")
        return

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
            click.echo("No git changes detected; skipped commit.")
            return

        if command[1] in {"pull", "push"}:
            click.echo("Git sync did not complete. Local changes are preserved for the next attempt.")
            if result.stderr.strip():
                click.echo(result.stderr.strip())
            return

        message = result.stderr.strip() or result.stdout.strip() or "Unknown git error."
        raise AutoDevLogError(f"Git command failed: {' '.join(command)}\n{message}")


def finalize_log(now: datetime, archived_path: Path) -> None:
    generator.generate_readme(ROOT_DIR)
    sync_git(now)
    click.echo(f"已保存：{archived_path.relative_to(ROOT_DIR).as_posix()}")
    click.echo("README 已更新。")


def run_quick_mode(now: datetime, clipboard_result: ClipboardImageResult | None) -> None:
    answers = prompt_for_quick_answers()
    content = build_quick_log_content(now, answers, clipboard_result)
    archived_path = archive_content(now, content)
    finalize_log(now, archived_path)


def run_editor_mode(now: datetime, clipboard_result: ClipboardImageResult | None) -> None:
    if clipboard_result:
        click.echo("检测到剪贴板图片，Markdown 链接已复制，可在编辑器中直接粘贴。")

    content = build_temp_log_content(now)
    TEMP_LOG_PATH.write_text(content, encoding="utf-8")

    try:
        open_editor(TEMP_LOG_PATH)
        archived_path = archive_temp_log(now, content)
        if archived_path is None:
            click.echo("No changes detected. Temporary log discarded.")
            return
        finalize_log(now, archived_path)
    finally:
        TEMP_LOG_PATH.unlink(missing_ok=True)


@click.group()
def cli() -> None:
    """Auto-DevLog CLI."""


@cli.command()
def init() -> None:
    """Initialize the project structure."""
    ensure_project_structure()
    generator.generate_readme(ROOT_DIR)
    click.echo("Auto-DevLog initialized.")


@cli.command()
def generate() -> None:
    """Regenerate README.md from the log archive."""
    ensure_project_structure()
    generator.generate_readme(ROOT_DIR)
    click.echo("README.md regenerated.")


@cli.command()
@click.option(
    "--mode",
    type=click.Choice(["quick", "editor"], case_sensitive=False),
    default="quick",
    show_default=True,
    help="Choose the fast prompt flow or the advanced editor flow.",
)
def new(mode: str) -> None:
    """Create a new development log entry."""
    ensure_project_structure()
    now = datetime.now()
    clipboard_result = detect_clipboard_image(now)
    if clipboard_result:
        click.echo("检测到剪贴板图片，已自动保存并接管链接。")

    selected_mode = mode.lower()
    if selected_mode == "editor":
        run_editor_mode(now, clipboard_result)
        return

    run_quick_mode(now, clipboard_result)


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
