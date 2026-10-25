from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


def default_db() -> Path:
    configured_home = os.environ.get("EVERUN_HOME") or os.environ.get("RELAY_HOME")
    if configured_home:
        return Path(configured_home) / "state.sqlite3"
    # Keep using a prototype database if one exists so a rename doesn't strand task history.
    everrun_home = Path.home() / ".everrun"
    legacy_home = Path.home() / ".relay"
    if not (everrun_home / "state.sqlite3").exists() and (legacy_home / "state.sqlite3").exists():
        return legacy_home / "state.sqlite3"
    return everrun_home / "state.sqlite3"


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or default_db()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY, goal TEXT NOT NULL, acceptance TEXT NOT NULL,
              repo TEXT NOT NULL, worktree TEXT NOT NULL, base_commit TEXT NOT NULL,
              status TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
              model TEXT NOT NULL,
              agent TEXT NOT NULL DEFAULT 'codex', agent_session TEXT NOT NULL DEFAULT '',
              created REAL NOT NULL, updated REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
              at REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL
            );
        """)
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(tasks)")}
        if "agent" not in columns:
            self.db.execute("ALTER TABLE tasks ADD COLUMN agent TEXT NOT NULL DEFAULT 'codex'")
        if "agent_session" not in columns:
            self.db.execute("ALTER TABLE tasks ADD COLUMN agent_session TEXT NOT NULL DEFAULT ''")
        self.db.commit()

    def create(self, *, goal: str, acceptance: list[str], repo: Path,
               worktree: Path, base_commit: str, model: str = "", agent: str = "codex") -> str:
        task_id = uuid.uuid4().hex[:10]
        now = time.time()
        self.db.execute("INSERT INTO tasks(id,goal,acceptance,repo,worktree,base_commit,status,model,agent,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (task_id, goal, json.dumps(acceptance), str(repo), str(worktree), base_commit, "running", model, agent, now, now))
        self.db.commit()
        self.event(task_id, "created", {"goal": goal, "acceptance": acceptance, "base_commit": base_commit})
        return task_id

    def event(self, task_id: str, kind: str, payload: dict[str, Any]) -> None:
        now = time.time()
        self.db.execute("INSERT INTO events(task_id,at,kind,payload) VALUES(?,?,?,?)", (task_id, now, kind, json.dumps(payload)))
        self.db.execute("UPDATE tasks SET updated=? WHERE id=?", (now, task_id))
        self.db.commit()

    def update(self, task_id: str, **values: Any) -> None:
        values["updated"] = time.time()
        fields = ",".join(f"{key}=?" for key in values)
        self.db.execute(f"UPDATE tasks SET {fields} WHERE id=?", (*values.values(), task_id))
        self.db.commit()

    def get(self, task_id: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["acceptance"] = json.loads(result["acceptance"])
        return result

    def list(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT id,goal,repo,agent,status,updated FROM tasks ORDER BY updated DESC")]

    def events(self, task_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT at,kind,payload FROM events WHERE task_id=? ORDER BY seq", (task_id,))]
