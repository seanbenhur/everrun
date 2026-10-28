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
    # Keep using the earlier state location if one exists so a rename doesn't strand task history.
    everrun_home = Path.home() / ".everrun"
    legacy_home = Path.home() / ".relay"
    if not (everrun_home / "state.sqlite3").exists() and (legacy_home / "state.sqlite3").exists():
        return legacy_home / "state.sqlite3"
    return everrun_home / "state.sqlite3"


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or default_db()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        self.db = sqlite3.connect(self.path, timeout=30)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY, goal TEXT NOT NULL, acceptance TEXT NOT NULL,
              repo TEXT NOT NULL, worktree TEXT NOT NULL, base_commit TEXT NOT NULL,
              status TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
              model TEXT NOT NULL,
              provider TEXT NOT NULL DEFAULT 'openai', auto_approve INTEGER NOT NULL DEFAULT 0,
              created REAL NOT NULL, updated REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
              at REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
              provider TEXT NOT NULL, payload TEXT NOT NULL, checkpoint INTEGER NOT NULL DEFAULT 0,
              created REAL NOT NULL
            );
        """)
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(tasks)")}
        if "provider" not in columns:
            self.db.execute("ALTER TABLE tasks ADD COLUMN provider TEXT NOT NULL DEFAULT 'openai'")
        if "auto_approve" not in columns:
            self.db.execute("ALTER TABLE tasks ADD COLUMN auto_approve INTEGER NOT NULL DEFAULT 0")
        message_columns = {row["name"] for row in self.db.execute("PRAGMA table_info(messages)")}
        if "checkpoint" not in message_columns:
            self.db.execute("ALTER TABLE messages ADD COLUMN checkpoint INTEGER NOT NULL DEFAULT 0")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def create(self, *, goal: str, acceptance: list[str], repo: Path,
               worktree: Path, base_commit: str, model: str = "", provider: str = "openai",
               auto_approve: bool = False) -> str:
        task_id = uuid.uuid4().hex[:10]
        now = time.time()
        self.db.execute("INSERT INTO tasks(id,goal,acceptance,repo,worktree,base_commit,status,model,provider,auto_approve,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (task_id, goal, json.dumps(acceptance), str(repo), str(worktree), base_commit, "running", model, provider, int(auto_approve), now, now))
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
        return [dict(r) for r in self.db.execute("SELECT id,goal,repo,provider,model,status,updated FROM tasks ORDER BY updated DESC")]

    def events(self, task_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT at,kind,payload FROM events WHERE task_id=? ORDER BY seq", (task_id,))]

    def messages(self, task_id: str) -> list[dict[str, Any]]:
        checkpoint = self.db.execute("SELECT MAX(seq) FROM messages WHERE task_id=? AND checkpoint=1", (task_id,)).fetchone()[0]
        if checkpoint:
            rows = self.db.execute("SELECT payload FROM messages WHERE task_id=? AND seq>=? ORDER BY seq", (task_id, checkpoint))
        else:
            rows = self.db.execute("SELECT payload FROM messages WHERE task_id=? ORDER BY seq", (task_id,))
        return [json.loads(r["payload"]) for r in rows]

    def add_message(self, task_id: str, provider: str, payload: dict[str, Any], *, checkpoint: bool = False) -> None:
        self.db.execute("INSERT INTO messages(task_id,provider,payload,checkpoint,created) VALUES(?,?,?,?,?)",
                        (task_id, provider, json.dumps(payload), int(checkpoint), time.time()))
        self.db.commit()

    def append_anthropic_tool_result(self, task_id: str, tool_use_id: str, result: str) -> None:
        row = self.db.execute("SELECT seq,payload FROM messages WHERE task_id=? ORDER BY seq DESC LIMIT 1", (task_id,)).fetchone()
        block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": result}
        if row:
            payload = json.loads(row["payload"])
            content = payload.get("content")
            if payload.get("role") == "user" and isinstance(content, list) and all(item.get("type") == "tool_result" for item in content):
                content.append(block)
                self.db.execute("UPDATE messages SET payload=? WHERE seq=?", (json.dumps(payload), row["seq"]))
                self.db.commit()
                return
        self.add_message(task_id, "anthropic", {"role": "user", "content": [block]})

    def clear_messages(self, task_id: str) -> None:
        self.db.execute("DELETE FROM messages WHERE task_id=?", (task_id,))
        self.db.commit()
