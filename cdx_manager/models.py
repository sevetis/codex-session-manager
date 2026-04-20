from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SessionInfo:
    session_id: str
    files: list[Path]
    thread_name: str | None = None
    updated_at: str | None = None
    cwd: str | None = None
    first_prompt: str | None = None
