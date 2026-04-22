from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .codex_ops import close_managed_tmux_tabs, close_tmux_tabs_for_session, run_codex_resume_background, switch_tmux_window
from .session_store import execute_delete
from .textutil import clip_text_cells, display_title, pad_text_cells, short_session_id
from .tui_controller import sync_selection
from .tui_repo import SessionRepository
from .tui_state import VIEW_MODES, UiState, build_entries, format_view_mode, session_from_entry

try:
    from prompt_toolkit.application import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.formatted_text import StyleAndTextTuples
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Float, FloatContainer, HSplit, Layout, VSplit, Window
    from prompt_toolkit.layout.containers import ConditionalContainer
    from prompt_toolkit.layout.controls import FormattedTextControl
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
                "confirm": "bg:#f8fbff #10324f",
                "confirm_title": "bg:#2c6ea3 #ffffff bold",
                "confirm_label": "#2a6f9f bold",
                "confirm_value": "#12344f",
                "confirm_warn": "#9b2c2c bold",
                "confirm_hint": "#3d4f63",
                "new": "bg:#f4f9ff #0f324f",
                "new_title": "bg:#2c6ea3 #ffffff bold",
                "new_label": "#2a6f9f bold",
                "new_value": "#12344f",
                "new_hint": "#3d4f63",
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
            "confirm": "bg:#1c2632 #dce8f2",
            "confirm_title": "bg:#2a4b6f #ffffff bold",
            "confirm_label": "#8fd0ff bold",
            "confirm_value": "#eef3f8",
            "confirm_warn": "#ff9f9f bold",
            "confirm_hint": "#9ab0c8",
            "new": "bg:#1a2430 #dce8f2",
            "new_title": "bg:#2a4b6f #ffffff bold",
            "new_label": "#8fd0ff bold",
            "new_value": "#eef3f8",
            "new_hint": "#9ab0c8",
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
    pending_delete_session_id = ""
    new_mode = False
    new_step = "cwd"
    new_default_dir = str(Path.cwd())
    new_cwd_value = ""
    new_prompt_value = ""
    new_input_value = ""

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

    def clear_pending_delete() -> None:
        nonlocal pending_delete_session_id
        pending_delete_session_id = ""

    def has_pending_delete() -> bool:
        return bool(pending_delete_session_id)

    def clear_new_mode() -> None:
        nonlocal new_mode, new_step, new_default_dir, new_cwd_value, new_prompt_value, new_input_value
        new_mode = False
        new_step = "cwd"
        new_default_dir = str(Path.cwd())
        new_cwd_value = ""
        new_prompt_value = ""
        new_input_value = ""

    def has_pending_new() -> bool:
        return new_mode

    def start_new_mode() -> None:
        nonlocal new_mode, new_step, new_default_dir, new_input_value
        cur = current_session()
        new_default_dir = (cur.cwd if cur is not None else str(Path.cwd())) or str(Path.cwd())
        new_mode = True
        new_step = "cwd"
        new_input_value = ""
        set_status("New session: enter directory path, Enter to continue, Esc to cancel.")

    def require_modal_idle() -> bool:
        if has_pending_delete():
            set_status("Delete confirmation is active. Press y to confirm, c/Esc to cancel.")
            return True
        if has_pending_new():
            set_status("New session input is active. Enter to continue, Esc to cancel.")
            return True
        return False

    def request_delete_confirm() -> None:
        nonlocal pending_delete_session_id
        cur = current_session()
        if cur is None:
            set_status("No session to delete.")
            return
        pending_delete_session_id = cur.session_id
        set_status(
            "Confirm delete: press y to delete, c/Esc to cancel "
            f"({short_session_id(cur.session_id)} {display_title(cur)})."
        )

    def confirm_delete_now() -> None:
        nonlocal pending_delete_session_id
        if not pending_delete_session_id:
            return
        sid = pending_delete_session_id
        clear_pending_delete()
        cur = repo.sessions.get(sid)
        if cur is None:
            set_status("Session not found. Refresh and try again.")
            return
        close_ok, close_msg = close_tmux_tabs_for_session(cur.session_id)
        removed_files, removed_index, _ = execute_delete(
            codex_home=repo.codex_home,
            sessions=repo.sessions,
            target_ids={cur.session_id},
            dry_run=False,
        )
        state.selected_session_id = ""
        refresh(force_repo=True)
        close_note = ""
        if close_ok and "Closed " in close_msg:
            close_note = f", {close_msg.lower()}"
        set_status(
            f"Deleted {short_session_id(cur.session_id)} "
            f"(files={removed_files}, index={removed_index}{close_note})."
        )

    def handle_new_submit() -> tuple[str, dict[str, str] | None] | None:
        nonlocal new_step, new_cwd_value, new_prompt_value, new_input_value
        if not new_mode:
            return None
        if new_step == "cwd":
            new_cwd_value = new_input_value.strip() or new_default_dir
            new_input_value = ""
            new_step = "prompt"
            set_status("New session: enter initial prompt (optional), Enter to create, Esc to cancel.")
            app.invalidate()
            return None
        new_prompt_value = new_input_value.strip()
        payload = {"cwd": new_cwd_value, "prompt": new_prompt_value}
        clear_new_mode()
        return ("new", payload)

    def new_dialog_text() -> StyleAndTextTuples:
        if not new_mode:
            return [("class:new_title", " New Session "), ("", "\n"), ("class:new_value", " ")]
        if new_step == "cwd":
            label = "Directory"
            hint = f"Default: {fit(new_default_dir, 68)}"
        else:
            label = "Prompt"
            hint = "Optional initial prompt."
        cur_val = new_input_value if new_input_value else ""
        return [
            ("class:new_title", " New Session "),
            ("", "\n"),
            ("class:new_label", f"{label}\n"),
            ("class:new_value", cur_val or " "),
            ("", "\n"),
            ("class:new_hint", hint),
            ("", "\n"),
            ("class:new_hint", "[Enter] next/create    [Esc] cancel"),
        ]

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

    def delete_dialog_text() -> StyleAndTextTuples:
        cur = repo.sessions.get(pending_delete_session_id) if pending_delete_session_id else None
        if cur is None:
            return [
                ("class:confirm_title", " Delete Session "),
                ("", "\n"),
                ("class:confirm_value", "Session not found."),
            ]
        return [
            ("class:confirm_title", " Delete Session "),
            ("", "\n"),
            ("class:confirm_label", "title  "),
            ("class:confirm_value", fit(display_title(cur), 70)),
            ("", "\n"),
            ("class:confirm_label", "id     "),
            ("class:confirm_value", short_session_id(cur.session_id)),
            ("", "\n"),
            ("class:confirm_label", "cwd    "),
            ("class:confirm_value", fit(cur.cwd or "-", 70)),
            ("", "\n"),
            ("", "\n"),
            ("class:confirm_warn", "This action cannot be undone."),
            ("", "\n"),
            ("class:confirm_hint", "[y] Delete    [c] Cancel    [Esc] Cancel"),
        ]

    summary_ctrl = FormattedTextControl(lambda: summary_text(), show_cursor=False)
    left_title_ctrl = FormattedTextControl(lambda: [("class:panel", " Sessions ")], show_cursor=False)
    right_title_ctrl = FormattedTextControl(lambda: [("class:panel", " Detail ")], show_cursor=False)
    left_ctrl = FormattedTextControl(lambda: left_text(), show_cursor=False)
    right_ctrl = FormattedTextControl(lambda: detail_text(), show_cursor=False)
    delete_ctrl = FormattedTextControl(lambda: delete_dialog_text(), show_cursor=False)
    new_ctrl = FormattedTextControl(lambda: new_dialog_text(), show_cursor=False)
    status_ctrl = FormattedTextControl(lambda: [("class:status", f"Status: {status}")], show_cursor=False)
    help_ctrl = FormattedTextControl(
        lambda: [
            (
                "class:help",
                "j/k move  g/G jump  PgUp/PgDn page  Enter/o open  n new  d delete  y confirm  c cancel  v view  r refresh  [ ] tab  q quit",
            )
        ],
        show_cursor=False,
    )

    kb = KeyBindings()

    @kb.add("q")
    def _quit(_event) -> None:
        if has_pending_delete():
            clear_pending_delete()
            set_status("Delete canceled.")
            return
        if has_pending_new():
            clear_new_mode()
            set_status("New session canceled.")
            return
        close_managed_tmux_tabs()
        app.exit(result=("quit", None))

    @kb.add("j")
    @kb.add("down")
    def _down(_event) -> None:
        if require_modal_idle():
            return
        move(1)

    @kb.add("k")
    @kb.add("up")
    def _up(_event) -> None:
        if require_modal_idle():
            return
        move(-1)

    @kb.add("g")
    def _top(_event) -> None:
        if require_modal_idle():
            return
        if selectable:
            state.selected_row = selectable[0]
            cur = current_session()
            if cur is not None:
                state.selected_session_id = cur.session_id
            adjust_top()
            app.invalidate()

    @kb.add("G")
    def _bottom(_event) -> None:
        if require_modal_idle():
            return
        if selectable:
            state.selected_row = selectable[-1]
            cur = current_session()
            if cur is not None:
                state.selected_session_id = cur.session_id
            adjust_top()
            app.invalidate()

    @kb.add("pageup")
    def _pgup(_event) -> None:
        if require_modal_idle():
            return
        move(-visible_rows())

    @kb.add("pagedown")
    def _pgdn(_event) -> None:
        if require_modal_idle():
            return
        move(visible_rows())

    @kb.add("v")
    def _view(_event) -> None:
        if require_modal_idle():
            return
        idx = VIEW_MODES.index(state.view_mode)
        state.view_mode = VIEW_MODES[(idx + 1) % len(VIEW_MODES)]
        refresh(force_repo=False)
        set_status(f"Switched view: {format_view_mode(state.view_mode)}")

    @kb.add("r")
    def _refresh(_event) -> None:
        if require_modal_idle():
            return
        refresh(force_repo=True)
        set_status("Refreshed.")

    @kb.add("]")
    def _next_tab(_event) -> None:
        if require_modal_idle():
            return
        ok, msg = switch_tmux_window(next_window=True)
        set_status(msg if ok else msg)

    @kb.add("[")
    def _prev_tab(_event) -> None:
        if require_modal_idle():
            return
        ok, msg = switch_tmux_window(next_window=False)
        set_status(msg if ok else msg)

    @kb.add("enter")
    @kb.add("o")
    def _open_or_submit(_event) -> None:
        if has_pending_new():
            result = handle_new_submit()
            if result is not None:
                app.exit(result=result)
            return
        if require_modal_idle():
            return
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
        if has_pending_new():
            set_status("Finish/cancel new session input first.")
            return
        request_delete_confirm()

    @kb.add("y")
    @kb.add("Y")
    def _confirm_delete(_event) -> None:
        confirm_delete_now()

    @kb.add("c")
    @kb.add("C")
    def _cancel_delete(_event) -> None:
        if pending_delete_session_id:
            clear_pending_delete()
            set_status("Delete canceled.")
            return

    @kb.add("n")
    def _new(_event) -> None:
        if has_pending_delete():
            set_status("Finish/cancel delete confirmation first.")
            return
        start_new_mode()

    @kb.add("escape")
    def _escape_modal(_event) -> None:
        if has_pending_delete():
            clear_pending_delete()
            set_status("Delete canceled.")
            return
        if has_pending_new():
            clear_new_mode()
            set_status("New session canceled.")
            return

    @kb.add("backspace")
    def _backspace_new(_event) -> None:
        nonlocal new_input_value
        if not has_pending_new():
            return
        if new_input_value:
            new_input_value = new_input_value[:-1]
            app.invalidate()

    @kb.add(Keys.Any)
    def _type_new(event) -> None:
        nonlocal new_input_value
        if not has_pending_new():
            return
        text = event.data
        if text and text.isprintable() and text not in ("\n", "\r"):
            new_input_value += text
            app.invalidate()

    base_root = HSplit(
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
    root = FloatContainer(
        content=base_root,
        floats=[
            Float(
                left=8,
                right=8,
                top=4,
                bottom=4,
                content=ConditionalContainer(
                    content=Window(content=delete_ctrl, wrap_lines=True, style="class:confirm"),
                    filter=Condition(lambda: bool(pending_delete_session_id)),
                ),
            )
            ,
            Float(
                left=8,
                right=8,
                top=5,
                bottom=5,
                content=ConditionalContainer(
                    content=Window(content=new_ctrl, wrap_lines=True, style="class:new"),
                    filter=Condition(lambda: new_mode),
                ),
            ),
        ],
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
