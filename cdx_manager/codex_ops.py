from __future__ import annotations

import os
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
