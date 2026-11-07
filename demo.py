#!/usr/bin/env python3
"""demo.py: try agent-guard without installing it.

    python3 demo.py

Puts five planted bad commands and one clean command to the real guard.py, the same way Claude Code's hook does: the
command and a working directory as a PreToolUse JSON on the guard's stdin. It runs in a throwaway git repo with
uncommitted work in it. NONE OF THE SIX COMMANDS IS RUN: the guard only reads them. The repo is deleted at the end,
and the guard's undo store is pointed at a temp folder, so the demo writes nothing under your home folder. (A Python
install that keeps a bytecode cache, Apple's python3 for one, writes its own .pyc files there for the modules it imports.)

Exit 0 when every planted command is BLOCKED and the clean one is ALLOWED, and the output is exactly
tools/demo_expected.txt. Any other result prints DEMO FAILED and exits 1.

    python3 demo.py --guard FILE       ask another guard file (tools/demo_check.py plants bad ones to prove this can fail)
    python3 demo.py --expected FILE    compare with another expected file

Blind to: any command beyond these six; the guard's undo layer (the clean command is read-only); tools other than
Bash. It needs python3 and git on the PATH.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = " DO THIS INSTEAD: "

PLANTED = ["git add -A", "git commit --no-verify -m x", "git reset --hard", "git clean -fdx", "rm -rf ."]
CLEAN = ["git status"]
HEADER = ("agent-guard demo: six commands go to the real guard.py. None of them is run.\n"
          "The repo is a throwaway git repo with uncommitted work in it.\n")


def ask(guard, command, cwd, env):
    """The hook call: the PreToolUse JSON on stdin, `python3 guard.py`. -> ("BLOCKED", rule, redirect) or ("ALLOWED",)
    or ("ERROR", why). Any reply that is not a clean deny or a clean silence is an ERROR, never an allow."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})
    p = subprocess.run([sys.executable, guard], input=payload, capture_output=True, text=True, env=env, cwd=cwd,
                       timeout=120)
    if p.returncode != 0:
        return ("ERROR", "the guard exited %d" % p.returncode)
    out = p.stdout.strip()
    if not out:
        return ("ALLOWED",)
    try:
        hook = json.loads(out)["hookSpecificOutput"]
    except Exception:
        return ("ERROR", "the guard printed something that is not a hook decision")
    if hook.get("permissionDecision") != "deny":
        return ("ERROR", "the guard printed a decision that is not a deny")
    reason = hook.get("permissionDecisionReason", "")
    before, mark, after = reason.partition(MARK)
    if not mark:
        return ("ERROR", "the deny carries no DO THIS INSTEAD")
    return ("BLOCKED", before.split(":", 1)[0], after)


def main(argv):
    guard = os.path.join(HERE, "guard.py")
    expected_path = os.path.join(HERE, "tools", "demo_expected.txt")
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--guard" and args:
            guard = os.path.abspath(args.pop(0))
        elif a == "--expected" and args:
            expected_path = os.path.abspath(args.pop(0))
        else:
            print("usage: python3 demo.py [--guard FILE] [--expected FILE]", file=sys.stderr)
            return 2

    work = tempfile.mkdtemp(prefix="agent_guard_demo_")
    try:
        repo = os.path.join(work, "repo")
        os.mkdir(repo)
        env = dict(os.environ)
        for k in [k for k in env if k.startswith("AGENT_GUARD_")] + ["CLAUDE_PROJECT_DIR"]:
            env.pop(k, None)
        env["AGENT_GUARD_STORE"] = os.path.join(work, "store")
        env["AGENT_GUARD_ROOT"] = repo
        git = ["git", "-c", "user.email=demo@example.com", "-c", "user.name=demo", "-C", repo]
        subprocess.run(git + ["init", "-q"], check=True, env=env, capture_output=True)
        app = os.path.join(repo, "app.py")
        notes = os.path.join(repo, "notes.txt")
        with open(app, "w") as fh:
            fh.write("print('hello')\n")
        subprocess.run(git + ["add", "app.py"], check=True, env=env, capture_output=True)
        subprocess.run(git + ["commit", "-q", "-m", "first"], check=True, env=env, capture_output=True)
        with open(app, "a") as fh:
            fh.write("print('unsaved work')\n")
        with open(notes, "w") as fh:
            fh.write("a file git has never seen\n")
        before = (open(app).read(), open(notes).read())

        blocks = []
        failures = []
        blocked = allowed = 0
        for want, commands in (("BLOCKED", PLANTED), ("ALLOWED", CLEAN)):
            for command in commands:
                r = ask(guard, command, repo, env)
                if r[0] == "BLOCKED":
                    blocks.append("BLOCKED  %s\n  rule: %s\n  DO THIS INSTEAD: %s\n" % (command, r[1], r[2]))
                elif r[0] == "ALLOWED":
                    blocks.append("ALLOWED  %s\n" % command)
                else:
                    blocks.append("ERROR    %s\n  %s\n" % (command, r[1]))
                if r[0] != want:
                    failures.append("%s: expected %s, the guard said %s" % (command, want, r[0]))
                elif want == "BLOCKED":
                    blocked += 1
                else:
                    allowed += 1
        intact = (open(app).read(), open(notes).read()) == before
        if not intact:
            failures.append("the work tree changed during the demo")
        tally = ("%d of %d planted commands BLOCKED. %d of %d clean command ALLOWED.\n"
                 % (blocked, len(PLANTED), allowed, len(CLEAN)))
        tail = "The uncommitted work is still on disk.\n" if intact else "The uncommitted work CHANGED.\n"
        text = HEADER + "\n" + "\n".join(blocks) + "\n" + tally + tail
        sys.stdout.write(text)
        if not failures:
            with open(expected_path, encoding="utf-8") as fh:
                want_text = fh.read()
            if text != want_text:
                failures.append("the output differs from the expected output in %s" % os.path.basename(expected_path))
        if failures:
            print("\nDEMO FAILED:")
            for f in failures:
                print("  " + f)
            return 1
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
