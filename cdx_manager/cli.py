from __future__ import annotations

import argparse
import curses
from pathlib import Path

from .codex_ops import run_codex_new, run_codex_resume
from .session_store import (
    collect_sessions,
    default_codex_home,
    execute_delete,
    print_sessions,
    validate_ids,
)
from .tui import run_tui


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Codex session manager")
    p.add_argument("session_ids", nargs="*", help="session id(s) to delete")
    p.add_argument("-l", "--list", action="store_true", help="list sessions")
    p.add_argument("--full-id", action="store_true", help="show full id in list header (default shows shortened id)")
    p.add_argument("--new", dest="new_dir", type=Path, help="create a new session in target directory")
    p.add_argument("--prompt", dest="new_prompt", default="", help="optional initial prompt for --new")
    p.add_argument("--all", action="store_true", help="delete all sessions")
    p.add_argument("--dry-run", action="store_true", help="preview only, no changes")
    p.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    p.add_argument("--codex-home", type=Path, default=default_codex_home(), help="Codex home dir (default: $CODEX_HOME or ~/.codex)")
    p.add_argument("--no-tui", action="store_true", help="disable default interactive TUI mode")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    codex_home: Path = args.codex_home.expanduser()

    if args.new_dir is not None:
        return run_codex_new(args.new_dir, args.new_prompt)

    if not args.no_tui and not args.list and not args.all and not args.session_ids:
        try:
            while True:
                action, payload = run_tui(codex_home)
                if action == "resume" and payload is not None:
                    run_codex_resume(payload.get("session_id", ""), payload.get("cwd", ""))
                    continue
                if action == "new" and payload is not None:
                    run_codex_new(payload.get("cwd", ""), payload.get("prompt", ""))
                    continue
                return 0
        except curses.error:
            print("TUI could not start in this terminal. Try --list or run in a real TTY.")
            return 1

    sessions = collect_sessions(codex_home)

    if args.list:
        print_sessions(sessions, full_id=args.full_id)
        if not args.all and not args.session_ids:
            return 0

    if not args.all and not args.session_ids:
        print("Nothing to delete. Use --list, --all, or provide session id(s).")
        return 1

    if args.all:
        target_ids = set(sessions.keys())
    else:
        target_ids = set(validate_ids(args.session_ids))

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
