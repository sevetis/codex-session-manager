from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .codex_ops import close_managed_tmux_tabs, run_codex_resume_background, switch_tmux_window
from .session_store import execute_delete
from .textutil import clip_text_cells, display_title, pad_text_cells, short_session_id
from .tui_controller import sync_selection
from .tui_repo import SessionRepository
from .tui_state import VIEW_MODES, UiState, build_entries, format_view_mode, session_from_entry

try:
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import StyleAndTextTuples
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.shortcuts import input_dialog, yes_no_dialog
    from prompt_toolkit.styles import Style
except Exception as exc:  # pragma: no cover
    raise RuntimeError("prompt_toolkit is not installed") from exc


def _detect_terminal_theme() -> str:
    """Best-effort terminal theme detection: returns 'dark' or 'light'."""
    value = os.environ.get("COLORFGBG", "").strip()
    if value:
        # Common forms: "15;0", "default;default", "0;15"
        parts = [p for p in value.split(";") if p]
        if parts:
            last = parts[-1]
            try:
                bg = int(last)
                return "dark" if bg <= 7 else "light"
            except ValueError:
                pass
    # Conservative default for most dev terminals.
    return "dark"


def _build_style(theme: str) -> Style:
    if theme == "light":
        return Style.from_dict(
            {
                "titlebar": "bg:#b7d8f3 #0d2b45",
                "title": "bg:#b7d8f3 #0d2b45 bold",
                "summarybar": "bg:#dbe8f5 #1b3550",
                "summary": "bg:#dbe8f5 #1b3550",
                "panelbar": "bg:#c8dcf2 #173a58",
                "panel": "bg:#c8dcf2 #173a58 bold",
                "statusbar": "bg:#f4e7be #4b3311",
                "status": "bg:#f4e7be #4b3311",
                "helpbar": "bg:#e5ecf4 #3a4d62",
                "help": "bg:#e5ecf4 #3a4d62",
                "row": "#223648",
                "group": "#1c5f8f bold",
                "selected": "bg:#2c6ea3 #ffffff bold",
                "key": "#1f679b bold",
                "value": "#13293a",
            }
        )

    return Style.from_dict(
        {
            "titlebar": "bg:#12324a #d7f2ff",
            "title": "bg:#12324a #d7f2ff bold",
            "summarybar": "bg:#1b1f2a #9ec6e0",
            "summary": "bg:#1b1f2a #9ec6e0",
            "panelbar": "bg:#243244 #a8ddff",
            "panel": "bg:#243244 #a8ddff bold",
            "statusbar": "bg:#2f2414 #ffd787",
            "status": "bg:#2f2414 #ffd787",
            "helpbar": "bg:#111827 #7f8ea3",
            "help": "bg:#111827 #7f8ea3",
            "row": "#d7dde5",
            "group": "#8fd0ff bold",
            "selected": "bg:#2a4b6f #ffffff bold",
            "key": "#8fd0ff bold",
            "value": "#eef3f8",
        }
    )


def run_tui_ptk(codex_home: Path) -> tuple[str, dict[str, str] | None]:
    repo = SessionRepository.create(codex_home)
    state = UiState()
    theme = _detect_terminal_theme()

    entries = []
    selectable = []
    status = "ready"
    top = 0

    def current_session() -> Any:
        if not entries or state.selected_row < 0 or state.selected_row >= len(entries):
            return None
        return session_from_entry(entries[state.selected_row])

    def term_size() -> tuple[int, int]:
        try:
            s = app.output.get_size()
            return s.rows, s.columns
        except Exception:
            return 24, 100

    def left_width() -> int:
        _rows, cols = term_size()
        return max(52, int(cols * 0.60))

    def visible_rows() -> int:
        rows, _cols = term_size()
        # Reserve rows for header, summary, panel titles and footer/status rows.
        return max(3, rows - 8)

    def fit(text: str, width: int) -> str:
        return clip_text_cells(text, max(1, width))

    def pad(text: str, width: int) -> str:
        return pad_text_cells(text, width)

    def wrap_lines(text: str, width: int) -> list[str]:
        if width <= 0:
            return [""]
        src = text if text else "-"
        src = src.replace("\n", " ")
        out: list[str] = []
        while src:
            chunk = fit(src, width)
            if not chunk:
                break
            out.append(chunk)
            src = src[len(chunk) :]
        return out or [""]

    def adjust_top() -> None:
        nonlocal top
        if not entries:
            top = 0
            return
        vis = visible_rows()
        if state.selected_row < top:
            top = state.selected_row
        if state.selected_row >= top + vis:
            top = state.selected_row - vis + 1
        max_top = max(0, len(entries) - vis)
        if top > max_top:
            top = max_top

    def refresh(force_repo: bool) -> None:
        nonlocal entries, selectable
        if force_repo:
            repo.refresh()
        entries = build_entries(repo.ordered(), state.view_mode)
        selectable = sync_selection(entries, state)
        adjust_top()
        app.invalidate()

    def set_status(msg: str) -> None:
        nonlocal status
        status = msg
        app.invalidate()

    def move(delta: int) -> None:
        if not selectable or state.selected_row not in selectable:
            return
        pos = selectable.index(state.selected_row)
        pos = max(0, min(len(selectable) - 1, pos + delta))
        state.selected_row = selectable[pos]
        cur = current_session()
        if cur is not None:
            state.selected_session_id = cur.session_id
        adjust_top()
        app.invalidate()

    def left_text() -> StyleAndTextTuples:
        out: StyleAndTextTuples = []
        vis = visible_rows()
        end = min(len(entries), top + vis)

        width = left_width() - 3
        title_w = max(18, min(34, width // 2 - 10))
        id_w = 14
        cwd_w = max(8, width - (2 + title_w + 2 + id_w + 2))

        for idx in range(top, end):
            e = entries[idx]
            if e.type == "header":
                line = pad(f"■ {e.title}", width)
                out.append(("class:group", line))
                out.append(("", "\n"))
                continue

            s = session_from_entry(e)
            if s is None:
                out.append(("", "\n"))
                continue

            marker = "▸" if idx == state.selected_row else " "
            line = (
                f"{marker} "
                f"{pad(display_title(s), title_w)}  "
                f"{pad(short_session_id(s.session_id), id_w)}  "
                f"{fit(s.cwd or '-', cwd_w)}"
            )
            style = "class:selected" if idx == state.selected_row else "class:row"
            out.append((style, line))
            out.append(("", "\n"))
        if top >= end:
            out.append(("class:row", pad("(no sessions)", width)))
        return out

    def detail_text() -> StyleAndTextTuples:
        out: StyleAndTextTuples = []
        cur = current_session()
        if cur is None:
            out.append(("class:key", "No session selected."))
            return out

        _rows, cols = term_size()
        right_w = max(28, cols - left_width() - 4)
        key_w = 13
        val_w = max(10, right_w - key_w - 2)

        def kv(key: str, value: str) -> None:
            vline = fit(value or "-", val_w)
            out.append(("class:key", f"{key:<{key_w}}  "))
            out.append(("class:value", vline))
            out.append(("", "\n"))

        kv("title", display_title(cur))
        kv("short_id", short_session_id(cur.session_id))
        kv("full_id", cur.session_id)
        kv("updated_at", cur.updated_at or "-")
        kv("cwd", cur.cwd or "-")
        kv("files", str(len(cur.files)))
        out.append(("", "\n"))

        out.append(("class:key", "first_prompt\n"))
        for ln in wrap_lines(cur.first_prompt or "-", max(8, right_w - 2)):
            out.append(("class:value", f"  {ln}\n"))
        out.append(("", "\n"))

        out.append(("class:key", "session_files\n"))
        if cur.files:
            for fp in cur.files:
                for ln in wrap_lines(str(fp), max(8, right_w - 2)):
                    out.append(("class:value", f"  {ln}\n"))
        else:
            out.append(("class:value", "  -\n"))
        return out

    def summary_text() -> StyleAndTextTuples:
        selected_pos = selectable.index(state.selected_row) + 1 if state.selected_row in selectable else 0
        msg = f"PTK mode ({theme})  total {len(selectable)}  view {format_view_mode(state.view_mode)}"
        if selectable:
            msg += f"  selected {selected_pos}/{len(selectable)}"
        return [("class:summary", msg)]

    summary_ctrl = FormattedTextControl(lambda: summary_text())
    left_title_ctrl = FormattedTextControl(lambda: [("class:panel", " Sessions ")])
    right_title_ctrl = FormattedTextControl(lambda: [("class:panel", " Detail ")])
    left_ctrl = FormattedTextControl(lambda: left_text())
    right_ctrl = FormattedTextControl(lambda: detail_text())
    status_ctrl = FormattedTextControl(lambda: [("class:status", f"Status: {status}")])
    help_ctrl = FormattedTextControl(
        lambda: [
            (
                "class:help",
                "j/k move  g/G jump  PgUp/PgDn page  Enter/o open  n new  d delete  v view  r refresh  [ ] tab  q quit",
            )
        ]
    )

    kb = KeyBindings()

    @kb.add("q")
    def _quit(_event) -> None:
        close_managed_tmux_tabs()
        app.exit(result=("quit", None))

    @kb.add("j")
    @kb.add("down")
    def _down(_event) -> None:
        move(1)

    @kb.add("k")
    @kb.add("up")
    def _up(_event) -> None:
        move(-1)

    @kb.add("g")
    def _top(_event) -> None:
        if selectable:
            state.selected_row = selectable[0]
            cur = current_session()
            if cur is not None:
                state.selected_session_id = cur.session_id
            adjust_top()
            app.invalidate()

    @kb.add("G")
    def _bottom(_event) -> None:
        if selectable:
            state.selected_row = selectable[-1]
            cur = current_session()
            if cur is not None:
                state.selected_session_id = cur.session_id
            adjust_top()
            app.invalidate()

    @kb.add("pageup")
    def _pgup(_event) -> None:
        move(-visible_rows())

    @kb.add("pagedown")
    def _pgdn(_event) -> None:
        move(visible_rows())

    @kb.add("v")
    def _view(_event) -> None:
        idx = VIEW_MODES.index(state.view_mode)
        state.view_mode = VIEW_MODES[(idx + 1) % len(VIEW_MODES)]
        refresh(force_repo=False)
        set_status(f"Switched view: {format_view_mode(state.view_mode)}")

    @kb.add("r")
    def _refresh(_event) -> None:
        refresh(force_repo=True)
        set_status("Refreshed.")

    @kb.add("]")
    def _next_tab(_event) -> None:
        ok, msg = switch_tmux_window(next_window=True)
        set_status(msg if ok else msg)

    @kb.add("[")
    def _prev_tab(_event) -> None:
        ok, msg = switch_tmux_window(next_window=False)
        set_status(msg if ok else msg)

    @kb.add("enter")
    @kb.add("o")
    def _open(_event) -> None:
        cur = current_session()
        if cur is None:
            set_status("No session to resume.")
            return
        ok, msg = run_codex_resume_background(cur.session_id, cur.cwd or "", tab_label=display_title(cur))
        set_status(msg if ok else msg)

    @kb.add("d")
    @kb.add("x")
    @kb.add("delete")
    def _delete(_event) -> None:
        cur = current_session()
        if cur is None:
            set_status("No session to delete.")
            return
        ok = yes_no_dialog(
            title="Delete",
            text=f"Delete {short_session_id(cur.session_id)}: {display_title(cur)}?",
        ).run()
        if not ok:
            set_status("Delete canceled.")
            return
        removed_files, removed_index, _ = execute_delete(
            codex_home=repo.codex_home,
            sessions=repo.sessions,
            target_ids={cur.session_id},
            dry_run=False,
        )
        state.selected_session_id = ""
        refresh(force_repo=True)
        set_status(f"Deleted {short_session_id(cur.session_id)} (files={removed_files}, index={removed_index}).")

    @kb.add("n")
    def _new(_event) -> None:
        cur = current_session()
        default_dir = (cur.cwd if cur is not None else str(Path.cwd())) or str(Path.cwd())
        entered = input_dialog(title="New Session", text=f"Directory (default: {default_dir})").run()
        if entered is None:
            set_status("New session canceled.")
            return
        target_dir = entered.strip() or default_dir
        prompt = input_dialog(title="New Session", text="Initial prompt (optional)").run()
        if prompt is None:
            set_status("New session canceled.")
            return
        app.exit(result=("new", {"cwd": target_dir, "prompt": prompt.strip()}))

    root = HSplit(
        [
            Window(content=summary_ctrl, height=1, style="class:summarybar"),
            VSplit(
                [
                    HSplit(
                        [
                            Window(content=left_title_ctrl, height=1, style="class:panelbar"),
                            Window(content=left_ctrl, wrap_lines=False),
                        ]
                    ),
                    HSplit(
                        [
                            Window(content=right_title_ctrl, height=1, style="class:panelbar"),
                            Window(content=right_ctrl, wrap_lines=False),
                        ]
                    ),
                ],
                padding=1,
            ),
            Window(content=status_ctrl, height=1, style="class:statusbar"),
            Window(content=help_ctrl, height=1, style="class:helpbar"),
        ]
    )

    style = _build_style(theme)

    app = Application(
        layout=Layout(root),
        key_bindings=kb,
        full_screen=True,
        style=style,
    )

    refresh(force_repo=False)
    result = app.run()
    if isinstance(result, tuple) and len(result) == 2:
        return result
    return ("quit", None)
