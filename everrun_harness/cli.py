from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from .git import prepare_worktree
from .runner import run_task, task_home
from .store import Store


def _git_root(repo: Path) -> Path:
    p = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=repo, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(f"Not inside a Git repository: {repo}")
    return Path(p.stdout.strip()).resolve()


def main() -> None:
    parser = argparse.ArgumentParser(prog="everrun", description="Persistent local coding task harness")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("run", help="Create an isolated task and start the agent")
    start.add_argument("goal", help="Task goal")
    start.add_argument("--repo", default=".", help="Git repository (default: current directory)")
    start.add_argument("--accept", action="append", default=[], help="Acceptance criterion; repeat as needed")
    start.add_argument("--agent", choices=["codex", "claude"], default=os.environ.get("EVERUN_AGENT", os.environ.get("RELAY_AGENT", "codex")), help="Installed coding agent CLI to run")
    start.add_argument("--model", default=os.environ.get("EVERUN_MODEL", os.environ.get("RELAY_MODEL")), help="Optional model name understood by the selected agent")
    resume = sub.add_parser("resume", help="Resume a paused or input-waiting task")
    resume.add_argument("task_id")
    resume.add_argument("--answer", help="Answer the task's pending question")
    resume.add_argument("--model", help="Switch to a model supported by the task's selected agent")
    status = sub.add_parser("status", help="Show task state")
    status.add_argument("task_id", nargs="?")
    report = sub.add_parser("report", help="Print the final review report")
    report.add_argument("task_id")
    sub.add_parser("agents", help="Show supported coding agent CLIs found on PATH")
    sub.add_parser("list", help="List tasks")
    args = parser.parse_args()
    store = Store()
    try:
        if args.command == "run":
            repo = _git_root(Path(args.repo).resolve())
            # Reserve the ID before creating a worktree so its branch and directory are stable.
            task_id = uuid.uuid4().hex[:10]
            worktree, base = prepare_worktree(repo, task_id)
            store.db.execute("INSERT INTO tasks(id,goal,acceptance,repo,worktree,base_commit,status,model,agent,created,updated) VALUES(?,?,?,?,?,?,?,?,?,strftime('%s','now'),strftime('%s','now'))",
                             (task_id, args.goal, json.dumps(args.accept), str(repo), str(worktree), base, "running", args.model or "", args.agent))
            store.db.commit()
            store.event(task_id, "created", {"goal": args.goal, "acceptance": args.accept, "base_commit": base})
            print(f"Created task {task_id}")
            try:
                run_task(task_id)
            except KeyboardInterrupt:
                store.update(task_id, status="paused")
                store.event(task_id, "interrupted", {})
                print(f"Paused. Resume with: everrun resume {task_id}")
            except Exception as e:
                store.update(task_id, status="paused")
                store.event(task_id, "runtime_error", {"error": str(e)})
                raise
        elif args.command == "resume":
            task = store.get(args.task_id)
            if not task:
                raise RuntimeError(f"Unknown task {args.task_id}")
            if args.model:
                store.update(args.task_id, model=args.model)
            try:
                run_task(args.task_id, answer=args.answer)
            except KeyboardInterrupt:
                store.update(args.task_id, status="paused")
                store.event(args.task_id, "interrupted", {})
                print(f"Paused. Resume with: everrun resume {args.task_id}")
            except Exception as e:
                store.update(args.task_id, status="paused")
                store.event(args.task_id, "runtime_error", {"error": str(e)})
                raise
        elif args.command == "status":
            tasks = [store.get(args.task_id)] if args.task_id else store.list()
            for task in tasks:
                if not task:
                    raise RuntimeError("Task not found")
                if args.task_id:
                    print(f"{task['id']}  {task['status']}  {task['goal']}\nagent: {task['agent']}  model: {task['model'] or 'default'}\nagent session: {task['agent_session'] or 'not started'}\nrepo: {task['repo']}\nworktree: {task['worktree']}\nbase: {task['base_commit']}")
                    for event in store.events(task["id"])[-8:]:
                        print(f"  {event['kind']}: {event['payload']}")
                else:
                    print(f"{task['id']}  {task['status']}  {task['agent']}  {task['goal']}  [{task['repo']}]")
        elif args.command == "list":
            for task in store.list():
                print(f"{task['id']}  {task['status']}  {task['goal']}")
        elif args.command == "report":
            path = task_home(args.task_id) / "report.md"
            if not path.exists():
                raise RuntimeError(f"No report exists for {args.task_id}")
            print(path.read_text(encoding="utf-8"))
        elif args.command == "agents":
            for agent, executable in (("codex", "codex"), ("claude", "claude")):
                location = shutil.which(executable)
                print(f"{agent}: {location or 'not found'}")
    except Exception as e:
        print(f"everrun: {e}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
