#!/usr/bin/env python3
"""guard.py: a Claude Code PreToolUse hook with three guards over Bash command strings.

Policy A, blanket_stage_guard: `git add` / `git commit` whose scope is the whole worktree or
all tracked modifications is denied. That means -A, --all and its abbreviations, -u/--update,
`.`, `./`, `..`, `:/`, `*`, the repo root, `$(...)`, and `git commit -a/-am/--all`.
Staging is by NAME. The command is argv-parsed with shlex and split on ; && || | & subshells
AND newlines.

Policy B, hook_bypass_guard: git invocations that disarm git's own hooks are denied whatever
the token order, when git is the direct command word: --no-verify, `commit -n`, -c or
`config` core.hooksPath to anything but .githooks, GIT_CONFIG_* overrides, and the plumbing
commands send-pack / commit-tree / update-ref. `git config core.hooksPath .githooks` and every
read-only form still pass.

Policy C, data_loss_guard: never destroy uncommitted or pushed work. Denied when git is the
direct command word: `reset --hard` (any ref), `clean` with -f in any flag combination,
whole-tree discards (`checkout -- .`, `checkout .`, `restore .`, `restore --staged --worktree .`),
force pushes (--force, -f, --force-with-lease, a +refspec) and `branch -D`. Still allowed:
`reset --soft`, `reset --mixed`, `reset HEAD <file>`, `clean -n`/`--dry-run`, `restore <named
file>`, `restore --staged .`, a normal `push`, `branch -d`. Same tokenizer, same splitting on
; && || | & subshells and newlines, same global-option skipping as policy A.
Motivation: anthropics/claude-code issue 97881, where `git reset --hard` on line 3 of a
multi-line command got past a permission check.

Usage as a hook: reads {"tool_name":"Bash","tool_input":{"command":"..."}} on stdin. Prints a
deny decision with a named reason to block. Prints nothing to allow.
Usage as a library: decide(command) -> ("block"|"allow", reason).

Failure behavior: any internal error is an allow (fail-open), and the hook form says so in a
systemMessage instead of staying silent. A guard must never brick the harness.

BOUND, named not closed: the guard sees the command text only, where the verb stands at the
head of a command. Wrappers (bash -c, sh -c, eval, xargs), a git call inside a committed
script, a binary reached through a variable or backticks, a quoted $(...) argument, shell
aliases, a repo root spelled with ~, and anything run outside the agent's Bash tool are out of
scope. It is a guardrail against an agent retrying a synonym. It is not a boundary against a
deliberate evader. A server-side hook or branch protection is the boundary.
"""
import json
import os
import re
import shlex
import sys


def _root():
    """The repo root a bare `git add <root>` is compared against. Pin it with AGENT_GUARD_ROOT."""
    return (os.environ.get("AGENT_GUARD_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR")
            or os.getcwd())


# ---- blanket_stage_guard (policy A) ----
WRAP = {"sudo", "env", "command", "time", "nohup", "nice", "exec"}
GIT_GLOBAL_VAL = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
OPS = {";", "&&", "||", "|", "&", "(", ")", "{", "}", "<", ">", ">>", "\n"}
BLANKET_LONG = ("--all", "--update", "--no-ignore-removal")
COMMIT_VAL = {"-m", "--message", "-F", "--file", "-C", "--reuse-message",
              "-c", "--reedit-message", "--author", "--date", "--squash",
              "--fixup", "--cleanup", "--trailer", "-t", "--template",
              "--gpg-sign", "--pathspec-from-file"}
SAY = ("blanket_stage_guard: this stages by SCOPE, not by NAME. Whole-worktree staging is "
       "denied as a class, not only the two literal spellings. Name every path: "
       "`git add <path> <path>`. Form seen: ")


def _tokens(text):
    try:
        lx = shlex.shlex(text, posix=True, punctuation_chars=True)
        lx.whitespace_split = True
        lx.commenters = ""
        return list(lx)
    except Exception:
        return None


def _strip_heredocs(cmd):
    """A heredoc BODY is data, not commands (a runbook quoting `git add -A` on its own line).
    Delimiters are found by tokenizing only the lines that carry `<<` (so a quoted "<<EOF"
    inside a string is not one). A body is stripped only when its terminating line exists, so an
    unterminated fake strips nothing and cannot swallow what follows."""
    delims = set()
    for line in cmd.split("\n"):
        if "<<" in line:
            lt = _tokens(line) or []
            delims |= {lt[i + 1].lstrip("-") for i in range(len(lt) - 1) if lt[i] == "<<"}
    if not delims:
        return cmd
    out, lines, i = [], cmd.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
        if m and m.group(1) in delims:
            end = next((j for j in range(i, len(lines)) if lines[j].strip() == m.group(1)), None)
            if end is not None:
                i = end + 1
    return "\n".join(out)


def blanket_stage_guard(cmd_nohd, root):
    """Return a deny reason, or None."""
    # a newline separates commands exactly as `;` does, but shlex consumes it as whitespace:
    # normalize first, or every blanket form on line 2+ of a multi-line command walks past.
    norm = re.sub(r"[\r\n]+", " ; ", cmd_nohd)
    toks_all = _tokens(norm)
    if toks_all is None:
        # unparseable quoting must not become a silent allow: fall back to the literal forms
        if re.search(r"(?:^|[;&|(]\s*)(?:\S*/)?git\s+(?:-\S+\s+\S+\s+)*add\s+"
                     r"(?:[^;&|)\n]*\s)?(?:-\w*[Au]\w*|--a\w*|--u\w*|\.|\./|:/)(?:\s|$)", norm):
            return SAY + "a blanket `git add` inside an unparseable command line."
        toks_all = []
    segs, cur = [], []
    for t in toks_all:
        if t in OPS:
            segs.append(cur)
            cur = []
        else:
            cur.append(t)
    segs.append(cur)
    for toks in segs:
        i = 0
        while i < len(toks) and (toks[i] in WRAP
                                 or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[i])):
            i += 1
        if i >= len(toks) or (toks[i] != "git" and not toks[i].endswith("/git")):
            continue
        i += 1
        while i < len(toks) and toks[i].startswith("-"):
            i += 2 if toks[i] in GIT_GLOBAL_VAL else 1
        if i >= len(toks):
            continue
        sub, args, endopts = toks[i], toks[i + 1:], False

        if sub == "add":
            for a in args:
                if a == "--" and not endopts:
                    endopts = True
                    continue
                if not endopts and a.startswith("--"):
                    name = a.split("=", 1)[0]
                    if len(name) > 2 and any(L.startswith(name) for L in BLANKET_LONG):
                        return SAY + "git add " + a
                    continue
                if not endopts and a.startswith("-") and a != "-":
                    if "A" in a[1:] or "u" in a[1:]:
                        return SAY + "git add " + a
                    continue
                core = a.rstrip("/")
                if core in ("", ".", "..", ":", "*", "$", root) or a.startswith("`"):
                    return SAY + "git add " + (a or "<empty>")

        elif sub == "commit":
            skip = False
            for a in args:
                if skip:
                    skip = False
                    continue
                if a == "--":
                    break
                if a in COMMIT_VAL:
                    skip = True
                    continue
                if a[:2] in ("-m", "-F", "-C", "-c", "-t") and len(a) > 2:
                    continue   # a value glued to its flag (-m'msg'), not an option cluster
                if a == "--all" or (a.startswith("-") and not a.startswith("--")
                                    and "a" in a[1:]):
                    return (SAY + "git commit " + a
                            + " (stages every tracked modification, then commits, in one step).")
    return None


# ---- hook_bypass_guard (policy B) ----
ASSIGN = r"(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*"
HOOKED = ("push", "commit", "merge", "rebase", "am", "cherry-pick", "revert")
PLUMB = ("send-pack", "commit-tree", "update-ref")
BYPASS_TAIL = (". Git's own hooks are the safety checks that run before a commit or push. "
               "Bypassing them is an act for a human in their own terminal. Stop and ask.")


def hook_bypass_guard(cmd_nohd):
    """Per shell segment whose command word is git, resolve the SUBCOMMAND (so a path or --grep
    term containing "commit" is not mistaken for one) and scan the unquoted remainder."""
    for seg in re.split(r"\|\||&&|[;|\n]", cmd_nohd):
        m = re.match(r"\s*" + ASSIGN + r"(?:(?:command|env)\s+" + ASSIGN + r")*(?:/\S*/)?git\b", seg)
        if not m:
            continue
        tail = seg[m.end():]
        rest = re.sub(r"'[^']*'|\"[^\"]*\"", " ", tail).split("<<")[0]
        bare = tail.replace("'", "").replace('"', "").split("<<")[0]
        sub, skip = "", False
        for t in rest.split():
            if skip:
                skip = False
                continue
            if t in ("-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path"):
                skip = True
                continue
            if t.startswith("-"):
                continue
            sub = t
            break
        why = ""
        if re.search(r"GIT_CONFIG_(COUNT|KEY_|VALUE_)", seg[:m.end()]):
            why = "GIT_CONFIG_* env override (a core.hooksPath flip in disguise)"
        elif re.search(r"-c\s*core\.hooksPath\s*=(?!\s*\.githooks(?:\s|$))", bare):
            why = "-c core.hooksPath=<not .githooks> disarms the hooks for this one command"
        elif sub == "config" and re.search(r"core\.hooksPath", bare) \
                and not re.search(r"--get|--list", rest):
            val = re.search(r"core\.hooksPath\s+(\S+)", tail.split("<<")[0])
            if (val and val.group(1) != ".githooks") or re.search(r"--unset", rest):
                why = "git config core.hooksPath <not .githooks> disarms the hooks for the clone"
        elif sub in PLUMB:
            why = "git plumbing that writes commits/refs without ever invoking pre-push or commit-msg"
        elif sub in HOOKED and re.search(r"--no-verify\b", rest):
            why = "--no-verify on a hook-carrying git command"
        elif sub == "push" and re.search(r"--no-verify\b", bare):
            why = "--no-verify (quoted) on a hook-carrying git command"
        elif sub == "commit" and re.search(r"(?:^|\s)-[A-Za-z]*n[A-Za-z]*(?=\s|$)", rest):
            why = "git commit -n (= --no-verify)"
        if why:
            return "hook_bypass_guard: " + why + BYPASS_TAIL
    return None


# ---- data_loss_guard (policy C) ----
FORCE_PUSH_LONG = ("--force", "--force-with-lease", "--force-if-includes")
PUSH_VAL = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
LOSS_TAIL = (". That destroys uncommitted or pushed work that the repo may not be able to give "
             "back. Stop and ask. Name the paths or refs, and let a human run it.")
_LOSS_LITERAL = re.compile(
    r"(?:^|[;&|(]\s*)(?:\S*/)?git\s+(?:[^;&|)\n]*\s)?(?:"
    r"reset\s+(?:[^;&|)\n]*\s)?--ha\w*"
    r"|clean\s+(?:[^;&|)\n]*\s)?(?:-\w*f\w*|--f\w*)"
    r"|push\s+(?:[^;&|)\n]*\s)?(?:-\w*f\w*|--for\w*|\+\S+)"
    r"|branch\s+(?:[^;&|)\n]*\s)?-\w*D\w*"
    r"|(?:checkout|restore)\s+(?:[^;&|)\n]*\s)?(?:\.|\./|:/)(?:\s|$))")


def _git_calls(cmd_nohd):
    """Every (subcommand, args) whose command word is git, one per shell segment, or None when the
    quoting does not parse. Same normalization, tokenizer, segment split, wrapper skipping and
    global-option skipping as blanket_stage_guard."""
    toks_all = _tokens(re.sub(r"[\r\n]+", " ; ", cmd_nohd))
    if toks_all is None:
        return None
    segs, cur = [], []
    for t in toks_all:
        if t in OPS:
            segs.append(cur)
            cur = []
        else:
            cur.append(t)
    segs.append(cur)
    calls = []
    for toks in segs:
        i = 0
        while i < len(toks) and (toks[i] in WRAP
                                 or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[i])):
            i += 1
        if i >= len(toks) or (toks[i] != "git" and not toks[i].endswith("/git")):
            continue
        i += 1
        while i < len(toks) and toks[i].startswith("-"):
            i += 2 if toks[i] in GIT_GLOBAL_VAL else 1
        if i < len(toks):
            calls.append((toks[i], toks[i + 1:]))
    return calls


def _whole_tree(a, root):
    return a.rstrip("/") in ("", ".", "..", ":", "*", "$", root) or a.startswith("`")


def _loss_reason(sub, args, root):
    """Return the named form that destroys work, or None."""
    if sub == "reset":
        for a in args:
            if a == "--":
                break
            name = a.split("=", 1)[0]
            if a.startswith("--") and len(name) >= 4 and "--hard".startswith(name):
                return "git reset --hard throws away every uncommitted change in the worktree and index"
    elif sub == "clean":
        skip = False
        for a in args:
            if skip:
                skip = False
                continue
            if a == "--":
                break
            if a == "-e" or a == "--exclude":
                skip = True
                continue
            name = a.split("=", 1)[0]
            if a.startswith("--"):
                if len(name) >= 3 and "--force".startswith(name):
                    return "git clean --force deletes untracked files for good"
            elif a.startswith("-") and not a.startswith("-e") and "f" in a[1:]:
                return "git clean with -f deletes untracked files for good"
    elif sub == "checkout" or sub == "restore":
        staged = worktree = whole = endopts = False
        for a in args:
            if a == "--" and not endopts:
                endopts = True
            elif not endopts and a.startswith("--"):
                staged = staged or a == "--staged"
                worktree = worktree or a == "--worktree"
            elif not endopts and a.startswith("-") and a != "-":
                staged = staged or "S" in a[1:]
                worktree = worktree or "W" in a[1:]
            elif _whole_tree(a, root):
                whole = True
        if whole and (sub == "checkout" or worktree or not staged):
            return "git %s over the whole tree discards every uncommitted change" % sub
    elif sub == "push":
        skip = endopts = False
        for a in args:
            if skip:
                skip = False
                continue
            if a == "--" and not endopts:
                endopts = True
            elif not endopts and a in PUSH_VAL:
                skip = True
            elif not endopts and a.startswith("--"):
                name = a.split("=", 1)[0]
                if len(name) >= 5 and any(L.startswith(name) for L in FORCE_PUSH_LONG):
                    return "git push " + a + " is a force push and can overwrite remote history"
            elif not endopts and a.startswith("-") and len(a) > 1:
                if "f" in a[1:]:
                    return "git push " + a + " is a force push and can overwrite remote history"
            elif a.startswith("+") and len(a) > 1:
                return "git push with a +refspec (" + a + ") is a force push of that ref"
    elif sub == "branch":
        dele = force = False
        for a in args:
            if a == "--":
                break
            name = a.split("=", 1)[0]
            if a.startswith("--"):
                dele = dele or (len(name) >= 5 and "--delete".startswith(name))
                force = force or (len(name) >= 6 and "--force".startswith(name))
            elif a.startswith("-") and len(a) > 1:
                if "D" in a[1:]:
                    return "git branch -D deletes a branch whether or not it is merged"
                dele = dele or "d" in a[1:]
                force = force or "f" in a[1:]
        if dele and force:
            return "git branch --delete --force deletes a branch whether or not it is merged"
    return None


def data_loss_guard(cmd_nohd, root):
    """Return a deny reason, or None."""
    calls = _git_calls(cmd_nohd)
    if calls is None:
        # unparseable quoting must not become a silent allow: fall back to the literal forms
        if _LOSS_LITERAL.search(re.sub(r"[\r\n]+", " ; ", cmd_nohd)):
            return ("data_loss_guard: a work-destroying git form inside an unparseable command line"
                    + LOSS_TAIL)
        return None
    for sub, args in calls:
        why = _loss_reason(sub, args, root)
        if why:
            return "data_loss_guard: " + why + LOSS_TAIL
    return None


def decide(command):
    """Return ("block", reason) or ("allow", reason). An allow carries an empty reason, except a
    fail-open, whose reason names the exception."""
    try:
        cmd = command or ""
        nohd = _strip_heredocs(cmd)
        why = blanket_stage_guard(nohd, _root())
        if why:
            return "block", why
        why = hook_bypass_guard(nohd)
        if why:
            return "block", why
        why = data_loss_guard(nohd, _root())
        if why:
            return "block", why
        return "allow", ""
    except Exception as exc:  # fail-open, but never silently
        return "allow", "fail-open: %s: %s" % (type(exc).__name__, str(exc)[:160])


def main(stdin=None):
    try:
        payload = json.load(stdin or sys.stdin)
        if payload.get("tool_name", "") != "Bash":
            return 0
        command = (payload.get("tool_input", {}) or {}).get("command", "") or ""
    except Exception as exc:
        print(json.dumps({"systemMessage": "GUARD FAIL-OPEN: %s: %s. The guard did NOT evaluate "
                          "this call." % (type(exc).__name__, str(exc)[:160])}))
        return 0
    verdict, reason = decide(command)
    if verdict == "block":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason}}))
    elif reason.startswith("fail-open"):
        print(json.dumps({"systemMessage": "GUARD " + reason[:200]
                          + ". The guard did NOT evaluate this call."}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
