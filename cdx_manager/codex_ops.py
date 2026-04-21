from __future__ import annotations

import os
import shlex
import shutil
import subprocess
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


def run_codex_resume_background(session_id: str, cwd: str | None) -> tuple[bool, str]:
    run_cwd = cwd if cwd and Path(cwd).exists() else os.getcwd()

    # Preferred path: tmux window when currently inside tmux.
    if os.environ.get("TMUX") and shutil.which("tmux"):
        cmd = f"codex resume {shlex.quote(session_id)}"
        win_name = f"s-{session_id[:8]}"
        completed = subprocess.run(
            ["tmux", "new-window", "-n", win_name, "-c", str(run_cwd), cmd],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if completed.returncode == 0:
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
