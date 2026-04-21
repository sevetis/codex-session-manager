from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import SessionInfo
from .session_store import collect_sessions, sorted_sessions


@dataclass
class SessionRepository:
    codex_home: Path
    sessions: dict[str, SessionInfo]

    @classmethod
    def create(cls, codex_home: Path) -> "SessionRepository":
        return cls(codex_home=codex_home, sessions=collect_sessions(codex_home))

    def refresh(self) -> None:
        self.sessions = collect_sessions(self.codex_home)

    def ordered(self) -> list[SessionInfo]:
        return sorted_sessions(self.sessions)
