from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .git import diff_summary
from .store import Store


def task_home(task_id: str) -> Path:
    configured_home = os.environ.get("EVERUN_HOME") or os.environ.get("RELAY_HOME")
    if configured_home:
        return Path(configured_home) / "tasks" / task_id
    everrun_home = Path.home() / ".everrun"
    legacy_home = Path.home() / ".relay"
    if not (everrun_home / "state.sqlite3").exists() and (legacy_home / "state.sqlite3").exists():
        return legacy_home / "tasks" / task_id
    return everrun_home / "tasks" / task_id


def _session_id(value: Any, agent: str) -> str | None:
    if isinstance(value, dict):
        keys = ("thread_id", "threadId") if agent == "codex" else ("session_id", "sessionId")
        for key in keys:
            if isinstance(value.get(key), str):
                return value[key]
        for key, child in value.items():
            if key == "session" and isinstance(child, dict) and isinstance(child.get("id"), str):
                return child["id"]
            found = _session_id(child, agent)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _session_id(child, agent)
            if found:
                return found
    return None


def _event_text(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("result"), str):
        return value["result"]
    item = value.get("item")
    if isinstance(item, dict) and item.get("type") in {"agent_message", "assistant_message"} and isinstance(item.get("text"), str):
        return item["text"]
    part = value.get("part")
    if isinstance(part, dict) and isinstance(part.get("text"), str):
        return part["text"]
    message = value.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), list):
        chunks = [block["text"] for block in message["content"] if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)]
        if chunks:
            return "".join(chunks)
    if value.get("type") in {"text", "text_delta"} and isinstance(value.get("text"), str):
        return value["text"]
    return None


def _write_report(task: dict[str, Any], task_id: str, summary: str, transcript: str) -> Path:
    root = Path(task["worktree"])
    criteria = "\n".join(f"- {item}" for item in task["acceptance"]) or "- No explicit acceptance criteria supplied"
    diff = diff_summary(root, task["base_commit"])
    home = task_home(task_id)
    home.mkdir(parents=True, exist_ok=True)
    path = home / "report.md"
    path.write_text(
        f"# Task {task_id}\n\n## Goal\n{task['goal']}\n\n## Acceptance criteria\n{criteria}\n\n"
        f"## Agent report\n{summary}\n\n## Transcript excerpt\n{transcript[-12000:]}\n\n"
        f"## Diff summary\n```text\n{diff}\n```\n\n"
        "Agent-reported verification is not independently validated by Everrun. Review the diff and rerun checks before merging.\n",
        encoding="utf-8",
    )
    return path


def run_task(task_id: str, *, answer: str | None = None) -> None:
    store = Store()
    task = store.get(task_id)
    if not task:
        raise RuntimeError(f"Unknown task {task_id}")
    if task["status"] == "review_required":
        raise RuntimeError("This task is awaiting review. Start a new task for follow-up work.")

    agent = task["agent"]
    command = {"codex": "codex", "claude": "claude"}.get(agent)
    if not command:
        raise RuntimeError(f"Unsupported agent: {agent}")
    executable = shutil.which(command)
    if not executable:
        hint = "codex login" if agent == "codex" else "run `claude` and sign in"
        raise RuntimeError(f"{command} CLI is not installed. Install it and authenticate with {hint}.")

    prompt = f"""You are working for Everrun, a persistent coding task harness. Work only in this task's current project directory.
Make incremental, reviewable progress. Inspect the repository before editing. Run relevant tests/builds and report the exact commands and outcomes.
If blocked by a consequential ambiguity, destructive action, credentials, or an external side effect, stop and ask the user instead of guessing.
When you stop, end your final response with exactly one marker:
EVERUN_STATUS: COMPLETE
or
EVERUN_STATUS: WAITING_FOR_INPUT
For COMPLETE, summarize changes, map each acceptance criterion to evidence or mark it unverified, and report checks accurately. Do not claim a check passed unless you observed it pass.

Task goal: {task['goal']}
Acceptance criteria:\n""" + "\n".join(f"- {item}" for item in task["acceptance"])
    if task["agent_session"]:
        prompt = "Continue this existing Everrun task session. Inspect the current working tree and latest task state before acting.\n\n" + prompt
    if answer:
        prompt += f"\n\nHuman response to your pending question: {answer}"
        store.event(task_id, "input_answered", {"answer": answer})

    if agent == "codex":
        args = [executable, "exec"]
        if task["agent_session"]:
            args.extend(["resume", task["agent_session"]])
            args.append("--json")
        else:
            # --approve-for-me uses the workspace-write sandbox; this Codex CLI
            # rejects combining it with an explicit --sandbox flag.
            args.extend(["--json", "--approve-for-me", "--cd", task["worktree"]])
        if task["model"]:
            args.extend(["--model", task["model"]])
        args.append(prompt)
    else:
        args = [executable, "-p", "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"]
        if task["agent_session"]:
            args.extend(["--resume", task["agent_session"]])
        if task["model"]:
            args.extend(["--model", task["model"]])
        args.append(prompt)

    store.update(task_id, status="running")
    store.event(task_id, "agent_started", {"agent": agent, "model": task["model"] or "agent default", "session": task["agent_session"]})
    print(f"Everrun task {task_id} running with {agent} in {task['worktree']}", flush=True)
    transcript: list[str] = []
    process = subprocess.Popen(args, cwd=task["worktree"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
    try:
        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = {"type": "output", "text": line}
            session_id = _session_id(event, agent)
            if session_id and session_id != task["agent_session"]:
                task["agent_session"] = session_id
                store.update(task_id, agent_session=session_id)
            text = _event_text(event)
            if text:
                transcript.append(text)
                print(text, end="", flush=True)
            store.event(task_id, "agent_event", {"agent": agent, "event": event})
        code = process.wait()
    except BaseException:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise

    output = "\n".join(transcript)
    if code != 0:
        store.update(task_id, status="paused")
        store.event(task_id, "agent_failed", {"agent": agent, "exit_code": code, "output": output[-4000:]})
        raise RuntimeError(f"{agent} exited with status {code}; task is paused and can be resumed.")

    if "EVERUN_STATUS: WAITING_FOR_INPUT" in output or "RELAY_STATUS: WAITING_FOR_INPUT" in output:
        marker = "EVERUN_STATUS: WAITING_FOR_INPUT" if "EVERUN_STATUS: WAITING_FOR_INPUT" in output else "RELAY_STATUS: WAITING_FOR_INPUT"
        question = output.rsplit(marker, 1)[-1].strip()
        store.update(task_id, status="waiting_for_input", summary=question[:1000])
        store.event(task_id, "input_requested", {"question": question[:1000]})
        print(f"\nTask is waiting for your input. Resume with: everrun resume {task_id} --answer \"...\"")
        return

    summary = output.strip() or f"{agent} completed without returning a text summary."
    report_path = _write_report(task, task_id, summary, output)
    store.update(task_id, status="review_required", summary=summary[:4000])
    store.event(task_id, "finished", {"summary": summary[:4000], "report": str(report_path)})
    print(f"\nTask ready for review. Report: {report_path}")
