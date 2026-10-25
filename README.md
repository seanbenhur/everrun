# Everrun

Everrun is a local-first harness for coding tasks that should survive a terminal disconnect, a process restart, or a fresh model context. It runs an installed coding agent in an isolated Git worktree and persists task state and events in SQLite.

This is an early prototype. The final state is always `review_required`; Everrun does not merge changes or independently certify the agent's claims.

## Install

Requires Python 3.11+, Git, and either the Codex CLI or Claude Code CLI. Everrun delegates coding to an installed agent, which uses its own login, subscription, model access, tools, and session format. Everrun does not handle model-provider credentials.

```sh
cd everrun
python -m pip install -e .
codex login       # or authenticate with Claude Code
everrun agents
```

## Start a task

Run from any Git repository, or specify one:

```sh
everrun run "Add pagination to the projects API" \
  --repo ~/code/my-project \
  --agent codex \
  --accept "Existing API behavior remains compatible" \
  --accept "Pagination has tests for first, middle, and final pages"
```

Choose the installed agent with `--agent codex` or `--agent claude`. Optionally pass a model name understood by that agent with `--model`; otherwise its own configured default is used:

```sh
everrun run "Add pagination" --repo ~/code/my-project --agent claude --model sonnet
```

Authenticate directly with the selected CLI (`codex login` or Claude Code's sign-in flow). Everrun doesn't ask for or copy those credentials.

Everrun creates a branch and worktree under the repository's Git metadata directory at `.git/everrun-worktrees/<task-id>` (or the common Git directory for linked worktrees). Task metadata and event history live in `~/.everrun/state.sqlite3` (or `$EVERUN_HOME`); reports live under `~/.everrun/tasks/<task-id>/`. Existing installations can continue using `$RELAY_HOME` to access their earlier task state. The selected agent's session ID is stored with each task and reused on resume.

```sh
everrun list
everrun status <task-id>
everrun resume <task-id>
everrun resume <task-id> --answer "Use cursor pagination"
everrun report <task-id>
```

Ctrl-C pauses the run. A model-step limit also pauses it. Resume reconstructs context from the task definition and latest checkpoint, then asks the model to inspect the current worktree before continuing.

## Safety and limitations

- Codex and Claude Code execute their own file and shell tools. Everrun asks them to work in the task worktree, but this is not a security sandbox.
- Model-reported checks are not independently validated. Review the diff and report yourself.
- Codex runs in its workspace-write sandbox with `--approve-for-me`; Claude Code runs with `--dangerously-skip-permissions` so unattended work can proceed. Review each CLI's permission model and use a disposable clone for untrusted repositories.
- This prototype supports Codex CLI and Claude Code CLI. It has no background daemon, automatic retry policy, multi-agent support, or UI yet.
- If Everrun is interrupted, run `everrun resume <task-id>`. Everrun state and the agent's own session transcript are preserved and the same session is continued.
- Worktrees and branches are intentionally retained for review. Remove them manually after merging or discarding a task.

## Current architecture

```text
CLI -> task controller / SQLite event store -> selected agent CLI (Codex / Claude Code)
                                      |      -> agent session in isolated Git worktree
                                      |      -> Everrun task events / report
```

The current code is split into the CLI, agent process runner, Git worktree helper, and SQLite store under `everrun_harness/`. See the [Codex CLI](https://developers.openai.com/codex/cli/) and [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code/cli-usage) documentation for agent login and options.
