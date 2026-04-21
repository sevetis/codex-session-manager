from __future__ import annotations

import argparse
import curses
import os
import shutil
import sys
from pathlib import Path

from .codex_ops import ensure_tmux_tab_keybindings, run_codex_new
from .session_store import (
    collect_sessions,
    default_codex_home,
    execute_delete,
    InvalidSessionIdsError,
    print_sessions,
    validate_ids,
)
from .tui import run_tui


def _looks_like_dir_arg(raw: str) -> bool:
    p = Path(raw).expanduser()
    if p.exists() and p.is_dir():
        return True
    return (
        raw in (".", "..")
        or raw.startswith("/")
        or raw.startswith("./")
        or raw.startswith("../")
        or raw.startswith("~/")
        or "/" in raw
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Codex session manager")
    p.add_argument("targets", nargs="*", help="session id(s) to delete, or '<dir> [prompt]' to create new session")
    p.add_argument("-l", "--list", action="store_true", help="list sessions")
    p.add_argument("--full-id", action="store_true", help="show full id in list header (default shows shortened id)")
    p.add_argument("--new", dest="new_dir", type=Path, help=argparse.SUPPRESS)
    p.add_argument("--prompt", dest="new_prompt", default="", help=argparse.SUPPRESS)
    p.add_argument("--dry-run", action="store_true", help="preview only, no changes")
    p.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    p.add_argument("--codex-home", type=Path, default=default_codex_home(), help="Codex home dir (default: $CODEX_HOME or ~/.codex)")
    p.add_argument("--no-tui", action="store_true", help="disable default interactive TUI mode")
    p.add_argument("--no-auto-tmux", action="store_true", help=argparse.SUPPRESS)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    codex_home: Path = args.codex_home.expanduser()

    # Auto-host manager in a dedicated tmux session so tab-like workflow works
    # in the same terminal window without requiring users to manually start tmux.
    should_auto_tmux = (
        not args.no_auto_tmux
        and not args.no_tui
        and not args.list
        and not args.targets
        and not os.environ.get("TMUX")
        and shutil.which("tmux") is not None
    )
    if should_auto_tmux:
        launcher = Path(__file__).resolve().parent.parent / "codex_session_manager.py"
        cmd = [
            "tmux",
            "new-session",
            "-A",
            "-s",
            "cdx",
            sys.executable,
            str(launcher),
            "--no-auto-tmux",
        ]
        os.execvp(cmd[0], cmd)

    # Preferred new-session UX: `cdx <dir> [optional prompt]`
    if args.targets and not args.list:
        first = args.targets[0]
        if _looks_like_dir_arg(first):
            prompt_text = " ".join(args.targets[1:]).strip()
            if args.dry_run:
                print("Warning: --dry-run is ignored for new-session mode.")
            return run_codex_new(first, prompt_text)

    # Backward-compatible path.
    if args.new_dir is not None:
        return run_codex_new(args.new_dir, args.new_prompt)

    if not args.no_tui and not args.list and not args.targets:
        try:
            if os.environ.get("TMUX"):
                ensure_tmux_tab_keybindings()
            while True:
                action, payload = run_tui(codex_home)
                if action == "new" and payload is not None:
                    run_codex_new(payload.get("cwd", ""), payload.get("prompt", ""))
                    continue
                return 0
        except curses.error:
            print("TUI could not start in this terminal. Try --list or run in a real TTY.")
            return 1
        except KeyboardInterrupt:
            print()
            return 130

    sessions = collect_sessions(codex_home)

    if args.list:
        print_sessions(sessions, full_id=args.full_id)
        if not args.targets:
            return 0

    if not args.targets:
        print("Nothing to delete. Use --list or provide session id(s).")
        return 1

    try:
        target_ids = set(validate_ids(args.targets))
    except InvalidSessionIdsError as exc:
        print("Invalid session id(s):")
        for sid in exc.bad_ids:
            print(f"- {sid}")
        return 2

    if not target_ids:
        print("No matching sessions to delete.")
        return 0

    missing = sorted(sid for sid in target_ids if sid not in sessions)
    if missing:
        print("Warning: session id(s) not found in current data:")
        for sid in missing:
            print(f"- {sid}")

    matched_ids = sorted(sid for sid in target_ids if sid in sessions)
    if not matched_ids:
        print("No existing session files matched. Will still clean matching entries in session_index.jsonl if any.")

    files_to_delete: list[Path] = []
    for sid in matched_ids:
        files_to_delete.extend(sessions[sid].files)

    print("Planned actions:")
    print(f"- delete session IDs: {len(target_ids)}")
    print(f"- delete files: {len(files_to_delete)}")
    for fp in files_to_delete:
        print(f"    {fp}")

    if args.dry_run:
        _removed_files, removed_index, _planned = execute_delete(
            codex_home=codex_home,
            sessions=sessions,
            target_ids=target_ids,
            dry_run=True,
        )
        print(f"- session_index entries to remove: {removed_index}")
        print("Dry-run only, no files changed.")
        return 0

    if not args.yes:
        reply = input("Proceed? Type 'yes' to continue: ").strip().lower()
        if reply != "yes":
            print("Aborted.")
            return 1

    removed_files, removed_index, _planned = execute_delete(
        codex_home=codex_home,
        sessions=sessions,
        target_ids=target_ids,
        dry_run=False,
    )

    print("Done.")
    print(f"- removed files: {removed_files}")
    print(f"- removed session_index entries: {removed_index}")
    return 0
