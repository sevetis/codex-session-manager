from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import SessionInfo

VIEW_TIME = "time"
VIEW_CWD = "cwd"
VIEW_MODES = (VIEW_TIME, VIEW_CWD)

EntryType = Literal["header", "session"]


@dataclass(frozen=True)
class SessionEntry:
    type: EntryType
    title: str = ""
    session: SessionInfo | None = None


@dataclass
class UiState:
    selected_row: int = 0
    top: int = 0
    status: str = ""
    view_mode: str = VIEW_CWD
    selected_session_id: str = ""


def normalized_cwd(session: SessionInfo) -> str:
    cwd = (session.cwd or "").strip()
    return cwd if cwd else "(no cwd)"


def build_entries(ordered: list[SessionInfo], view_mode: str) -> list[SessionEntry]:
    if view_mode == VIEW_TIME:
        return [SessionEntry(type="session", session=s) for s in ordered]

    groups: dict[str, list[SessionInfo]] = {}
    for s in ordered:
        key = normalized_cwd(s)
        groups.setdefault(key, []).append(s)

    group_items: list[tuple[str, list[SessionInfo], str]] = []
    for cwd, items in groups.items():
        items_sorted = sorted(items, key=lambda x: (x.updated_at or "", x.session_id), reverse=True)
        latest = items_sorted[0].updated_at or ""
        group_items.append((cwd, items_sorted, latest))
    group_items.sort(key=lambda t: (t[2], t[0]), reverse=True)

    entries: list[SessionEntry] = []
    for cwd, items, _latest in group_items:
        entries.append(SessionEntry(type="header", title=f"{cwd} ({len(items)})"))
        entries.extend(SessionEntry(type="session", session=s) for s in items)
    return entries


def selectable_rows(entries: list[SessionEntry]) -> list[int]:
    return [i for i, e in enumerate(entries) if e.type == "session" and e.session is not None]


def session_from_entry(entry: SessionEntry) -> SessionInfo | None:
    return entry.session if entry.type == "session" else None


def format_view_mode(view_mode: str) -> str:
    if view_mode == VIEW_CWD:
        return "group-by-cwd"
    return "time"
