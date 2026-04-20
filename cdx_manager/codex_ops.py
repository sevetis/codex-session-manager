from __future__ import annotations

import os
import subprocess
from pathlib import Path


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
    return completed.returncode
