# Install agent-guard

This page is for a person, or for a coding agent following [llms.txt](../llms.txt). Both do the same four things in the same order: look at the hook, install, prove it blocks, know how to remove it.

## What it is

agent-guard is a Claude Code hook. Before each Bash tool call it reads the command and denies the ones that stage the whole git tree, switch off git hooks or destroy uncommitted work. Every deny ends with `DO THIS INSTEAD:` and a safe command that finishes the same task. It covers that one class. It does not look for leaked secrets, check MCP tool calls or stop prompt injection. It reads the command text and runs nothing. It needs `python3` installed (the `python3` command works in your terminal). If the hook cannot run, Claude Code lets the command through.

The result is in the [README](../README.md). It denied 98.5% of 1,124 dangerous commands and wrongly denied 2.8% of 1,305 safe ones on a blind set (blind_v31), with the misses listed.

## Step 1: look at the hook before anything is installed

An agent doing this for you must print this to you, word for word, and wait for your yes before it runs step 2. This is the file `hooks/hooks.json`, the whole of what the plugin adds:

```json
{
  "description": "agent-guard: reads each Bash command before it runs and denies blanket staging, switched-off git hooks and destroyed work.",
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3",
            "args": ["${CLAUDE_PLUGIN_ROOT}/guard.py"],
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

In words: before every Bash tool call, run `python3 guard.py` from the plugin's folder, give it the call on stdin, and wait up to 30 seconds. The guard prints a deny, or prints nothing. `tools/demo_check.py --self-test` fails if this block and `hooks/hooks.json` ever differ.

## Step 2: install

```
claude plugin marketplace add CASEY-OS/agent-guard-bench
claude plugin install agent-guard@agent-guard-bench
```

The plugin is the whole repository, about 30 MB, because the guard, its undo layer and its tests live together. These commands change two things in your Claude Code settings file (`~/.claude/settings.json` for the user scope): `enabledPlugins` gains `agent-guard@agent-guard-bench`, and `extraKnownMarketplaces` gains `agent-guard-bench`. The hook above is not copied into your settings; it stays in the plugin.

Check what was installed with `claude plugin list` (it names the version and says enabled) and `claude plugin details agent-guard@agent-guard-bench` (it reports one PreToolUse hook).

## Step 3: prove it blocks a planted command

Use a throwaway git repo, never your own. The plugin's folder is the `installPath` of `agent-guard@agent-guard-bench` in `~/.claude/plugins/installed_plugins.json`.

```
mkdir /tmp/guard-try && cd /tmp/guard-try && git init -q
echo '{"tool_name":"Bash","tool_input":{"command":"git add -A"},"cwd":"/tmp/guard-try"}' | python3 <installPath>/guard.py
```

The output must contain `"permissionDecision": "deny"` and `DO THIS INSTEAD:`. A clean command, `git status` in place of `git add -A`, prints nothing. If the planted command prints nothing, the guard is not working: remove it and open an issue.

Then start a new Claude Code session in that throwaway repo and ask it to run `git add -A`. It must be refused, with the same text.

To see the same thing with nothing installed, clone the repository and run `python3 demo.py`.

## Step 4: remove it

```
claude plugin uninstall agent-guard@agent-guard-bench
claude plugin marketplace remove agent-guard-bench
```

Then `claude plugin list` no longer names it, and `enabledPlugins` and `extraKnownMarketplaces` no longer hold its entries.

Claude Code may keep a copy in `~/.claude/plugins/cache/agent-guard-bench/`; delete it if you want the space back.

When the guard allows a command that could change a repo, it first takes an undo point, a snapshot under `~/.local/state/agent-guard` (or the folder in `AGENT_GUARD_STORE`). Uninstalling does not delete those snapshots. Delete that folder yourself once you no longer want them. `AGENT_GUARD_UNDO=0` turns undo points off.

## What it reads, and what it sends

The import lines of `guard.py` and `undo.py` name no network library (read on 2026-11-07). `undo.py` runs `git` on your repo. The optional judge, `judge.py`, is off unless you set `AGENT_GUARD_JUDGE`; when it is on, it asks `claude -p` about commands the guard cannot read to the end. That import check does not cover code run through `exec` or `__import__`.
