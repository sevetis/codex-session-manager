from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


def _switch_to_english_input_method() -> None:
    # Try common IM frameworks on Linux. No-op if commands are unavailable.
    switch_cmds = [
        ["fcitx5-remote", "-s", "keyboard-us"],
        ["fcitx-remote", "-s", "keyboard-us"],
        ["ibus", "engine", "xkb:us::eng"],
    ]
    for cmd in switch_cmds:
        try:
            result = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            continue
        if result.returncode == 0:
            return


@dataclass(frozen=True)
class TmuxTabInfo:
    total: int
    managed: int
    current_index: str
    current_name: str


@dataclass(frozen=True)
class TmuxWindowRow:
    window_id: str
    index: str
    name: str
    session_id: str
    manager_flag: str


def _is_managed_tab_name(name: str) -> bool:
    return name.startswith("cdx-") or name.startswith("s-")


def _slugify_tab_label(label: str) -> str:
    s = label.strip().lower()
    if not s:
        return "session"
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9._-]", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if not s:
        return "session"
    return s[:28]


def _window_name_for_session(session_id: str, label: str | None, cwd: str | None) -> str:
    if label and label.strip():
        return _slugify_tab_label(label)
    if cwd:
        base = Path(cwd).name.strip()
        if base:
            return _slugify_tab_label(base)
    return f"session-{session_id[:8]}"


def _parse_tmux_windows(raw: str) -> TmuxTabInfo | None:
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return None

    total = 0
    managed = 0
    current_index = ""
    current_name = ""
    for line in lines:
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        idx, name, active = parts[0], parts[1], parts[2]
        managed_flag = parts[3] if len(parts) >= 4 else ""
        total += 1
        if managed_flag == "1" or _is_managed_tab_name(name):
            managed += 1
        if active == "1":
            current_index = idx
            current_name = name

    if total == 0:
        return None
    return TmuxTabInfo(
        total=total,
        managed=managed,
        current_index=current_index or "?",
        current_name=current_name or "?",
    )


def _parse_tmux_window_rows(raw: str) -> list[TmuxWindowRow]:
    rows: list[TmuxWindowRow] = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split("\t")
        if len(parts) < 3:
            continue
        rows.append(
            TmuxWindowRow(
                window_id=parts[0] if len(parts) >= 1 else "",
                index=parts[1] if len(parts) >= 2 else "",
                name=parts[2] if len(parts) >= 3 else "",
                session_id=parts[3] if len(parts) >= 4 else "",
                manager_flag=parts[4] if len(parts) >= 5 else "",
            )
        )
    return rows


def _list_tmux_window_rows() -> list[TmuxWindowRow]:
    listed = subprocess.run(
        ["tmux", "list-windows", "-F", "#{window_id}\t#{window_index}\t#{window_name}\t#{@cdx_session_id}\t#{@cdx_manager}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if listed.returncode != 0:
        return []
    return _parse_tmux_window_rows(listed.stdout)


def _find_tmux_windows_by_session(session_id: str) -> list[TmuxWindowRow]:
    return [row for row in _list_tmux_window_rows() if row.session_id == session_id and row.manager_flag != "1"]


def get_tmux_tab_info() -> TmuxTabInfo | None:
    if not os.environ.get("TMUX"):
        return None
    if not shutil.which("tmux"):
        return None

    completed = subprocess.run(
        ["tmux", "list-windows", "-F", "#{window_index}\t#{window_name}\t#{window_active}\t#{@cdx_managed}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    return _parse_tmux_windows(completed.stdout)


def close_managed_tmux_tabs() -> tuple[bool, str]:
    if not os.environ.get("TMUX"):
        return (False, "Not in tmux session.")
    if not shutil.which("tmux"):
        return (False, "tmux command not found.")

    listed = subprocess.run(
        ["tmux", "list-windows", "-F", "#{window_index}\t#{window_name}\t#{@cdx_managed}\t#{@cdx_manager}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if listed.returncode != 0:
        return (False, "Failed to list tmux windows.")

    targets: list[str] = []
    for ln in listed.stdout.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split("\t")
        if len(parts) < 2:
            continue
        idx, name = parts[0], parts[1]
        managed_flag = parts[2] if len(parts) >= 3 else ""
        manager_flag = parts[3] if len(parts) >= 4 else ""
        is_managed = managed_flag == "1" or _is_managed_tab_name(name)
        if is_managed and manager_flag != "1":
            targets.append(idx)

    closed = 0
    for idx in targets:
        completed = subprocess.run(
            ["tmux", "kill-window", "-t", f":{idx}"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if completed.returncode == 0:
            closed += 1

    return (True, f"Closed {closed} managed tab(s).")


def run_codex_resume(session_id: str, cwd: str | None) -> int:
    cmd = ["codex", "resume", session_id]
    run_cwd = cwd if cwd and Path(cwd).exists() else None
    where = run_cwd or os.getcwd()
    print(f"Launching: {' '.join(cmd)} (cwd={where})")
    try:
        completed = subprocess.run(cmd, cwd=run_cwd, check=False)
    except FileNotFoundError:
        print("Failed: `codex` command not found in PATH.")
        return 127
    _switch_to_english_input_method()
    return completed.returncode


def run_codex_resume_background(session_id: str, cwd: str | None, tab_label: str = "") -> tuple[bool, str]:
    run_cwd = cwd if cwd and Path(cwd).exists() else os.getcwd()

    # Preferred path: tmux window when currently inside tmux.
    if os.environ.get("TMUX") and shutil.which("tmux"):
        matched = _find_tmux_windows_by_session(session_id)
        if matched:
            target = matched[0].window_id or f":{matched[0].index}"
            switched = subprocess.run(
                ["tmux", "select-window", "-t", target],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if switched.returncode == 0:
                return (True, f"Switched to existing tab {matched[0].name or matched[0].index}")

        cmd = f"codex resume {shlex.quote(session_id)}"
        win_name = _window_name_for_session(session_id, tab_label, run_cwd)
        completed = subprocess.run(
            ["tmux", "new-window", "-P", "-F", "#{window_id}", "-n", win_name, "-c", str(run_cwd), cmd],
            check=False,
            stdout=subprocess.PIPE,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        if completed.returncode == 0:
            window_id = (completed.stdout or "").strip()
            if window_id:
                subprocess.run(
                    ["tmux", "set-option", "-w", "-t", window_id, "@cdx_managed", "1"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                subprocess.run(
                    ["tmux", "set-option", "-w", "-t", window_id, "@cdx_manager", "0"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                subprocess.run(
                    ["tmux", "set-option", "-w", "-t", window_id, "@cdx_session_id", session_id],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            return (True, f"Opened tab {win_name}")

    # Fallback path: open an external terminal window if available.
    # No trailing shell; window should close automatically when codex exits.
    shell_cmd = f"cd {shlex.quote(str(run_cwd))} && codex resume {shlex.quote(session_id)}"
    launchers: list[list[str]] = []
    if shutil.which("gnome-terminal"):
        launchers.append(["gnome-terminal", "--maximize", "--", "bash", "-lc", shell_cmd])
    if shutil.which("x-terminal-emulator"):
        launchers.append(["x-terminal-emulator", "-e", "bash", "-lc", shell_cmd])
    if shutil.which("kitty"):
        launchers.append(["kitty", "--start-as=maximized", "bash", "-lc", shell_cmd])
    if shutil.which("alacritty"):
        launchers.append(["alacritty", "--option", "window.startup_mode=Maximized", "-e", "bash", "-lc", shell_cmd])
    if shutil.which("wezterm"):
        launchers.append(["wezterm", "start", "--maximized", "--", "bash", "-lc", shell_cmd])
    if shutil.which("konsole"):
        launchers.append(["konsole", "--fullscreen", "-e", "bash", "-lc", shell_cmd])

    for launcher in launchers:
        try:
            subprocess.Popen(launcher, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return (True, f"Opened in new terminal window: {session_id}")
        except Exception:
            continue

    return (
        False,
        "Background open failed: no supported terminal launcher found. "
        "Use tmux, or install one of gnome-terminal/x-terminal-emulator/kitty/alacritty/wezterm/konsole.",
    )


def switch_tmux_window(next_window: bool) -> tuple[bool, str]:
    if not os.environ.get("TMUX"):
        return (False, "Not in tmux session.")
    if not shutil.which("tmux"):
        return (False, "tmux command not found.")

    cmd = ["tmux", "next-window"] if next_window else ["tmux", "previous-window"]
    completed = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if completed.returncode != 0:
        return (False, "Failed to switch tmux window.")
    return (True, "Switched tmux window.")


def close_tmux_tabs_for_session(session_id: str) -> tuple[bool, str]:
    if not os.environ.get("TMUX"):
        return (False, "Not in tmux session.")
    if not shutil.which("tmux"):
        return (False, "tmux command not found.")

    matched = _find_tmux_windows_by_session(session_id)
    if not matched:
        return (True, "No open tab for this session.")

    closed = 0
    for row in matched:
        target = row.window_id or f":{row.index}"
        completed = subprocess.run(
            ["tmux", "kill-window", "-t", target],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if completed.returncode == 0:
            closed += 1
    if closed == 0:
        return (False, "Failed to close tab for this session.")
    return (True, f"Closed {closed} tab(s) for this session.")


def ensure_tmux_tab_keybindings() -> tuple[bool, str]:
    if not os.environ.get("TMUX"):
        return (False, "Not in tmux session.")
    if not shutil.which("tmux"):
        return (False, "tmux command not found.")

    cmds = [
        ["tmux", "bind-key", "-n", "]", "next-window"],
        ["tmux", "bind-key", "-n", "[", "previous-window"],
    ]
    for cmd in cmds:
        completed = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if completed.returncode != 0:
            return (False, "Failed to configure tmux tab keybindings.")
    return (True, "Configured tmux tab keybindings for [ and ].")


def ensure_tmux_statusline() -> tuple[bool, str]:
    if not os.environ.get("TMUX"):
        return (False, "Not in tmux session.")
    if not shutil.which("tmux"):
        return (False, "tmux command not found.")

    cmds = [
        ["tmux", "set-option", "-g", "status", "on"],
        ["tmux", "set-option", "-g", "status-position", "top"],
        ["tmux", "set-option", "-g", "status-style", "fg=colour255,bg=colour238"],
        ["tmux", "set-option", "-g", "status-left-length", "80"],
        ["tmux", "set-option", "-g", "status-right-length", "140"],
        ["tmux", "set-option", "-g", "status-left", "#[bold,fg=colour231,bg=colour242] CDX #[default]"],
        [
            "tmux",
            "set-option",
            "-g",
            "status-right",
            "#[fg=colour252]tabs #[bold]#{session_windows}#[default] #[fg=colour245]| %H:%M",
        ],
        ["tmux", "set-window-option", "-g", "window-status-separator", ""],
        ["tmux", "set-window-option", "-g", "window-status-format", " #[fg=colour252,bg=colour236] #W #[default] "],
        ["tmux", "set-window-option", "-g", "window-status-current-format", " #[bold,fg=colour235,bg=colour180] #W #[default] "],
    ]
    for cmd in cmds:
        completed = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if completed.returncode != 0:
            return (False, "Failed to configure tmux statusline.")
    return (True, "Configured tmux statusline.")


def ensure_tmux_manager_window_name() -> tuple[bool, str]:
    if not os.environ.get("TMUX"):
        return (False, "Not in tmux session.")
    if not shutil.which("tmux"):
        return (False, "tmux command not found.")
    cmds = [
        ["tmux", "rename-window", "HOME"],
        ["tmux", "set-option", "-w", "@cdx_manager", "1"],
        ["tmux", "set-option", "-w", "@cdx_managed", "0"],
        ["tmux", "set-option", "-w", "@cdx_session_id", ""],
    ]
    for cmd in cmds:
        completed = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if completed.returncode != 0:
            return (False, "Failed to configure manager window.")
    return (True, "Configured manager window.")


def run_codex_new(target_dir: str | Path, prompt: str = "") -> int:
    target = Path(target_dir).expanduser()
    cmd = ["codex", "-C", str(target)]
    if prompt.strip():
        cmd.append(prompt.strip())
    run_cwd = str(target) if target.exists() else os.getcwd()
    where = run_cwd or os.getcwd()
    print(f"Launching: {' '.join(cmd)} (cwd={where})")
    try:
        completed = subprocess.run(cmd, cwd=run_cwd, check=False)
    except FileNotFoundError:
        print("Failed: `codex` command not found in PATH.")
        return 127
    _switch_to_english_input_method()
    return completed.returncode
