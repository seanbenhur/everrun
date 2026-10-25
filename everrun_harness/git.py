from __future__ import annotations

import subprocess
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or "git command failed")
    return p.stdout.strip()


def prepare_worktree(repo: Path, task_id: str) -> tuple[Path, str]:
    root = Path(git(repo, "rev-parse", "--show-toplevel")).resolve()
    base = git(root, "rev-parse", "HEAD")
    git_dir = Path(git(root, "rev-parse", "--git-common-dir"))
    if not git_dir.is_absolute():
        git_dir = (root / git_dir).resolve()
    path = git_dir / "everrun-worktrees" / task_id
    path.parent.mkdir(parents=True, exist_ok=True)
    git(root, "worktree", "add", "-b", f"everrun/{task_id}", str(path), base)
    return path, base


def diff_summary(worktree: Path, base: str) -> str:
    p = subprocess.run(["git", "diff", "--stat", base], cwd=worktree, text=True, capture_output=True)
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=worktree, text=True, capture_output=True)
    parts = [p.stdout.strip()]
    if untracked.stdout.strip():
        parts.append("Untracked files:\n" + untracked.stdout.strip())
    return "\n".join(x for x in parts if x) or "No changes yet."
