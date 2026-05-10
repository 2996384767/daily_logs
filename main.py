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
import pyperclip
from PIL import ImageGrab

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


class AutoDevLogError(RuntimeError):
    """Raised when the CLI cannot complete a requested operation."""


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


def archive_temp_log(now: datetime, original_content: str) -> Path | None:
    updated_content = TEMP_LOG_PATH.read_text(encoding="utf-8")
    if updated_content == original_content:
        TEMP_LOG_PATH.unlink(missing_ok=True)
        return None

    log_dir, _ = current_log_paths(now)
    log_dir.mkdir(parents=True, exist_ok=True)
    target_path = log_dir / f"{now.strftime('%Y-%m-%d_%H%M')}.md"
    target_path.write_text(updated_content, encoding="utf-8")
    TEMP_LOG_PATH.unlink(missing_ok=True)
    return target_path


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
def new() -> None:
    """Create a new development log entry."""
    ensure_project_structure()
    now = datetime.now()

    clipboard_result = detect_clipboard_image(now)
    if clipboard_result:
        click.echo(
            f"Clipboard image saved to {clipboard_result.asset_path.relative_to(ROOT_DIR).as_posix()}."
        )
        click.echo("Markdown image link copied to clipboard. Paste it in the editor when needed.")

    content = build_temp_log_content(now)
    TEMP_LOG_PATH.write_text(content, encoding="utf-8")

    try:
        open_editor(TEMP_LOG_PATH)
        archived_path = archive_temp_log(now, content)
        if archived_path is None:
            click.echo("No changes detected. Temporary log discarded.")
            return

        generator.generate_readme(ROOT_DIR)
        sync_git(now)
        click.echo(f"Archived log: {archived_path.relative_to(ROOT_DIR).as_posix()}")
        click.echo("README updated and git sync finished.")
    finally:
        TEMP_LOG_PATH.unlink(missing_ok=True)


def main() -> int:
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
