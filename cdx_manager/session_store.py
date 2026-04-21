from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from .models import SessionInfo
from .textutil import clip_text, display_title, short_session_id

ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class InvalidSessionIdsError(ValueError):
    def __init__(self, bad_ids: list[str]) -> None:
        super().__init__("Invalid session id(s)")
        self.bad_ids = bad_ids


def default_codex_home() -> Path:
    from_env = os.environ.get("CODEX_HOME")
    if from_env:
        return Path(from_env)
    return Path.home() / ".codex"


def extract_id_from_filename(name: str) -> str | None:
    if not name.endswith(".jsonl"):
        return None
    m = ID_RE.search(name)
    if not m:
        return None
    return m.group(0)


def is_ignorable_user_text(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if t.startswith("<environment_context>") and t.endswith("</environment_context>"):
        return True
    return False


def extract_user_text_from_response_item(obj: dict) -> str | None:
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return None
    if payload.get("type") != "message" or payload.get("role") != "user":
        return None
    content = payload.get("content")
    if not isinstance(content, list):
        return None
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "input_text":
            txt = part.get("text")
            if isinstance(txt, str) and txt.strip() and not is_ignorable_user_text(txt):
                return txt
    return None


def extract_user_text_from_event_msg(obj: dict) -> str | None:
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return None
    if payload.get("type") != "user_message":
        return None
    msg = payload.get("message")
    if isinstance(msg, str) and msg.strip() and not is_ignorable_user_text(msg):
        return msg
    return None


def enrich_from_session_file(info: SessionInfo) -> None:
    if not info.files:
        return
    fp = info.files[0]
    try:
        with fp.open("r", encoding="utf-8") as f:
            for line in f:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                rec_type = obj.get("type")
                if rec_type == "session_meta":
                    payload = obj.get("payload")
                    if isinstance(payload, dict):
                        cwd = payload.get("cwd")
                        if isinstance(cwd, str) and cwd.strip():
                            info.cwd = cwd.strip()

                if info.first_prompt is None:
                    text = None
                    if rec_type == "response_item":
                        text = extract_user_text_from_response_item(obj)
                    elif rec_type == "event_msg":
                        text = extract_user_text_from_event_msg(obj)
                    if text:
                        info.first_prompt = text

                if info.cwd and info.first_prompt:
                    break
    except OSError:
        return


def collect_sessions(codex_home: Path) -> dict[str, SessionInfo]:
    sessions: dict[str, SessionInfo] = {}
    sessions_root = codex_home / "sessions"
    if sessions_root.exists():
        for fp in sessions_root.rglob("*.jsonl"):
            sid = extract_id_from_filename(fp.name)
            if sid is None:
                continue
            info = sessions.setdefault(sid, SessionInfo(session_id=sid, files=[]))
            info.files.append(fp)

    index_file = codex_home / "session_index.jsonl"
    if index_file.exists():
        with index_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sid = obj.get("id")
                if not isinstance(sid, str):
                    continue
                info = sessions.setdefault(sid, SessionInfo(session_id=sid, files=[]))
                tn = obj.get("thread_name")
                ua = obj.get("updated_at")
                info.thread_name = tn if isinstance(tn, str) else info.thread_name
                info.updated_at = ua if isinstance(ua, str) else info.updated_at

    for info in sessions.values():
        info.files.sort()
        enrich_from_session_file(info)
    return sessions


def sorted_sessions(sessions: dict[str, SessionInfo]) -> list[SessionInfo]:
    return sorted(
        sessions.values(),
        key=lambda s: (s.updated_at or "", s.session_id),
        reverse=True,
    )


def print_sessions(sessions: dict[str, SessionInfo], full_id: bool = False) -> None:
    if not sessions:
        print("No sessions found.")
        return
    ordered = sorted_sessions(sessions)
    print(f"Found {len(ordered)} session(s):")
    for idx, s in enumerate(ordered, start=1):
        title = display_title(s)
        header_id = s.session_id if full_id else short_session_id(s.session_id)
        print(f"{idx}. {title}  [{header_id}]")
        print(f"   id: {s.session_id}")
        if s.updated_at:
            print(f"   updated_at: {s.updated_at}")
        if s.cwd:
            print(f"   cwd: {s.cwd}")
        print(f"   files: {len(s.files)}")
        for fp in s.files:
            print(f"   - {fp}")
        print()


def validate_ids(ids: list[str]) -> list[str]:
    valid = []
    bad = []
    for sid in ids:
        if ID_RE.fullmatch(sid):
            valid.append(sid)
        else:
            bad.append(sid)
    if bad:
        raise InvalidSessionIdsError(bad)
    return valid


def rewrite_session_index(index_file: Path, delete_ids: set[str], dry_run: bool) -> int:
    if not index_file.exists():
        return 0

    removed = 0
    kept_lines: list[str] = []
    with index_file.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")
            if not raw:
                continue
            try:
                obj = json.loads(raw)
                sid = obj.get("id")
            except json.JSONDecodeError:
                sid = None
            if isinstance(sid, str) and sid in delete_ids:
                removed += 1
                continue
            kept_lines.append(raw)

    if not dry_run:
        tmp = index_file.with_suffix(index_file.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for ln in kept_lines:
                f.write(ln)
                f.write("\n")
        shutil.move(str(tmp), str(index_file))

    return removed


def remove_empty_dirs(root: Path, dry_run: bool) -> None:
    if not root.exists():
        return
    for d in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        try:
            next(d.iterdir())
            is_empty = False
        except StopIteration:
            is_empty = True
        if is_empty and not dry_run:
            d.rmdir()


def execute_delete(codex_home: Path, sessions: dict[str, SessionInfo], target_ids: set[str], dry_run: bool) -> tuple[int, int, list[Path]]:
    matched_ids = sorted(sid for sid in target_ids if sid in sessions)
    files_to_delete: list[Path] = []
    for sid in matched_ids:
        files_to_delete.extend(sessions[sid].files)

    if dry_run:
        removed_index = rewrite_session_index(codex_home / "session_index.jsonl", target_ids, dry_run=True)
        return (0, removed_index, files_to_delete)

    removed_files = 0
    for fp in files_to_delete:
        if fp.exists():
            fp.unlink()
            removed_files += 1

    removed_index = rewrite_session_index(codex_home / "session_index.jsonl", target_ids, dry_run=False)
    remove_empty_dirs(codex_home / "sessions", dry_run=False)
    return (removed_files, removed_index, files_to_delete)
