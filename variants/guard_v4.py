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

Usage as a hook: reads {"tool_name":"Bash","tool_input":{"command":"..."},"cwd":"..."} on stdin.
Prints a deny decision whose reason ends with a redirect ("DO THIS INSTEAD: ..."), or nothing to
allow. Version 4 never prints an ask decision. On an allow it hands the command to undo.py, which
takes a snapshot of the repo at "cwd" first when the command could change it (see undo.py).
Usage as a library: decide(command) -> ("block"|"allow", reason). decide_full(command) -> a dict
with the verdict, its origin (a v3 block or a v3 fail-closed ask), the redirect shape, the redirect
text and the safe alternative commands it names.

VERSION 4. NEVER ASK. Every v3 "ask" is now a deny, and every deny ends with a redirect: a concrete
step the agent can take to finish its task safely, chosen per shape of violation (REDIRECTS below),
with every alternative written as a command the guard itself allows. What v3 stopped, v4 stops; what
v3 allowed, v4 allows. Detection is v3's, unchanged (_decide3). The "Stop and ask" and "A human
decides" tails of v3 reasons are removed, because no human is asked.

Failure behavior (version 3): an internal error in the version 3 reader is an "ask" that names the
exception. Stdin that is not valid hook JSON is still a visible fail-open systemMessage, because
then there is no command to ask about.

VERSION 2 (this file). Before any policy runs, the command is normalized and every VIEW of it is
checked, so the verdict is a union and nothing v1 blocked is allowed now. A view is the text as
written, the text after normalization, and any text a shell would run that is spelled out as a
literal inside the command. Normalization: backslash-newline is joined, $'..' is decoded,
$IFS and ${IFS} become a space, NAME=literal assigned earlier in the SAME string is substituted
into later $NAME, and a $(...) or backtick whose content is a literal echo / printf / decode
pipeline is replaced by its output. Literal shell text: `sh|bash|zsh -c '<lit>'`, `eval <lit>`,
`<literal pipeline> | sh`, `source <(<literal pipeline>)`. A decode pipeline is echo or printf of a
literal into base64 -d, xxd -r -p, rev or tr, at most 4 KB. The decoded text goes back through the
whole guard, at most 3 levels deep. Policy B also reads flags after quote removal and folds the
case of config keys. Nothing is ever executed.

VERSION 3. The design idea is FAIL CLOSED. A string reader cannot see runtime state, so when it
cannot prove a risky git command safe it asks a human. decide() runs the version 2 check first and
unchanged, so every v2 block stays a block. Then it reads further: variables assigned in the same
string (with ${X:-w} and the other operators, arrays, read, printf -v, set --, literal for-loops,
a custom IFS), brace expansion, aliases and shell functions defined then called, git aliases from
-c or git config, wrappers (sudo, env, command, exec, nohup, time, nice, timeout, xargs, find -exec,
parallel, watch, su, script, trap, ssh, docker exec), keywords (if, then, do, !), inline
interpreter code, a heredoc or here-string or process substitution fed to a shell, a script written
and run in the same string, git settings whose value git runs as a command, and the plumbing and
file routes to the same effects (checkout -f, switch --discard-changes, branch -f, stash drop and
clear, reflog expire, push --delete and :ref and --mirror, update-ref, symbolic-ref -d, read-tree
--reset -u, checkout-index -f -a, rm or mv or chmod -x or a truncating write on a hooks path, rm of
.git, HUSKY=0 and SKIP=). Whatever it still cannot resolve, where it could make the command a
policy violation, becomes "ask" with a reason that starts with fail_closed. Where the unresolved
part provably cannot matter (git log -n $N, a quoted -m value, a reset pathspec after --, a dry run)
it allows.

BOUND, named not closed: the guard sees the command text only. A value the shell fills in at run
time is invisible: a variable set outside the command, `git add $TARGETS`, a `$(...)` that runs a
program, a file or a network fetch piped into a shell, a git call inside a committed script,
aliases, xargs, a heredoc fed to a shell, a repo root spelled with ~, and anything run outside the
agent's Bash tool. A guard that reads strings cannot see runtime state. It is a guardrail
against an agent retrying a synonym. It is not a boundary against a deliberate evader. A
server-side hook or branch protection is the boundary.
"""
import base64
import binascii
import json
import os
import posixpath
import re
import shlex
import sys


def _root():
    """The repo root a bare `git add <root>` is compared against. Pin it with AGENT_GUARD_ROOT."""
    return (os.environ.get("AGENT_GUARD_ROOT") or os.environ.get("CLAUDE_PROJECT_DIR")
            or os.getcwd())


# ---- blanket_stage_guard (policy A) ----
WRAP = {"sudo", "env", "command", "time", "nohup", "nice", "exec"}
GIT_GLOBAL_VAL = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
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
        elif re.search(r"-c\s*(?i:core\.hooksPath)\s*=(?!\s*\.githooks(?:\s|$))", bare):
            why = "-c core.hooksPath=<not .githooks> disarms the hooks for this one command"
        elif sub == "config" and re.search(r"core\.hooksPath", bare, re.I) \
                and not re.search(r"--get|--list", rest):
            val = re.search(r"core\.hooksPath\s+(\S+)", tail.split("<<")[0], re.I)
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


def _git_calls_full(cmd_nohd):
    """Every git call, one per shell segment whose command word is git, as a dict with the env
    assignments before it, the global options (as (flag, value-or-None) pairs), the subcommand and
    its args. None when the quoting does not parse. Same normalization, tokenizer, segment split,
    wrapper skipping and global-option skipping as blanket_stage_guard."""
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
        i, env = 0, []
        while i < len(toks) and (toks[i] in WRAP
                                 or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[i])):
            if toks[i] not in WRAP:
                env.append(toks[i])
            i += 1
        if i >= len(toks) or (toks[i] != "git" and not toks[i].endswith("/git")):
            continue
        i += 1
        gopts = []
        while i < len(toks) and toks[i].startswith("-"):
            if toks[i] in GIT_GLOBAL_VAL:
                gopts.append((toks[i], toks[i + 1] if i + 1 < len(toks) else None))
                i += 2
            else:
                gopts.append((toks[i], None))
                i += 1
        if i < len(toks):
            calls.append({"env": env, "gopts": gopts, "sub": toks[i], "args": toks[i + 1:]})
    return calls


def _git_calls(cmd_nohd):
    """Every (subcommand, args) whose command word is git, or None when the quoting does not parse."""
    calls = _git_calls_full(cmd_nohd)
    return None if calls is None else [(c["sub"], c["args"]) for c in calls]


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


# ---- policy B, token form (version 2) ----
GLUED_COMMIT = ("-m", "-F", "-C", "-c", "-t", "-u", "-S")
VALUE_OPTS = COMMIT_VAL | PUSH_VAL


def _hook_reason(c):
    """Policy B over parsed tokens, so a flag is compared AFTER quote removal and a config key is
    compared without case. Returns a reason or None."""
    for a in c["env"]:
        if re.match(r"GIT_CONFIG_(COUNT|KEY_|VALUE_)", a):
            return "GIT_CONFIG_* env override (a core.hooksPath flip in disguise)"
    for flag, val in c["gopts"]:
        if flag.startswith("--config-env"):    # --config-env=core.hooksPath=VAR: the value is read from the environment
            pair = flag.split("=", 1)[1] if "=" in flag else (val or "")
            if pair.partition("=")[0].strip().casefold() == "core.hookspath":
                return "--config-env core.hooksPath=<an environment variable> disarms the hooks for this one command"
            continue
        v = val if flag == "-c" else (flag[2:] if flag.startswith("-c") and not flag.startswith("--") else None)
        if v is not None and "=" in v:
            key, _, setting = v.partition("=")
            if key.strip().casefold() == "core.hookspath" and setting.strip() != ".githooks":
                return "-c core.hooksPath=<not .githooks> disarms the hooks for this one command"
    sub, args = c["sub"], c["args"]
    for k, a in enumerate(args):       # a here-string or heredoc ends the arguments (as in version 1)
        if a.startswith("<<"):
            args = args[:k]
            break
    if sub == "config":
        if any(a.startswith("--get") or a.startswith("--list") for a in args):
            return None
        for k, a in enumerate(args):
            if a.casefold() == "core.hookspath":
                val = args[k + 1] if k + 1 < len(args) else None
                if (val and val != ".githooks") or any(x.startswith("--unset") for x in args):
                    return "git config core.hooksPath <not .githooks> disarms the hooks for the clone"
        return None
    if sub in PLUMB:
        return "git plumbing that writes commits/refs without ever invoking pre-push or commit-msg"
    if sub in HOOKED:
        skip = False
        for a in args:
            if skip:
                skip = False
                continue
            if a == "--":
                break
            if a in VALUE_OPTS:
                skip = True
                continue
            if len(a) >= 8 and "--no-verify".startswith(a):     # git accepts a unique abbreviation
                return "--no-verify on a hook-carrying git command"
            if (sub == "commit" and re.match(r"^-[A-Za-z]+$", a) and a[:2] not in GLUED_COMMIT
                    and "n" in a[1:]):
                return "git commit -n (= --no-verify)"
    return None


def hook_bypass_tokens(cmd_nohd):
    for c in _git_calls_full(cmd_nohd) or []:
        why = _hook_reason(c)
        if why:
            return "hook_bypass_guard: " + why + BYPASS_TAIL
    return None


# ---- normalization and literal evaluation (version 2) ----
MAX_LITERAL = 4096     # bytes of literal input or decoded output the guard will evaluate
MAX_DEPTH = 3          # how many times decoded or wrapped text goes back through the guard
MAX_PAYLOADS = 24      # per level
MAX_SUBST = 64         # most $(..) and backtick pairs one command may have and still be evaluated
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "ash"}
_ANSI = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b",
         "f": "\f", "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?"}


def _ctx(text):
    """For each character: 0 unquoted, 1 inside single quotes, 2 inside double quotes, 3 escaped."""
    st, q, esc = [], 0, False
    for c in text:
        if esc:
            st.append(3)
            esc = False
        elif q == 1:
            st.append(1)
            if c == "'":
                q = 0
        elif c == "\\":
            st.append(q)
            esc = True
        elif c == "'" and q == 0:
            st.append(0)
            q = 1
        elif c == '"':
            st.append(0)
            q = 2 if q == 0 else 0
        else:
            st.append(q)
    return st


def _unescape(s, zero=False):
    """Backslash escapes as echo -e, printf and $'..' read them. zero=True is the echo -e and
    printf %b form, where an octal escape is \\0 and up to three digits (version 3)."""
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c != "\\" or i + 1 >= len(s):
            out.append(c)
            i += 1
            continue
        d = s[i + 1]
        if d in _ANSI:
            out.append(_ANSI[d])
            i += 2
        elif d == "x":
            m = re.match(r"[0-9A-Fa-f]{1,2}", s[i + 2:])
            out.append(chr(int(m.group(), 16)) if m else "\\x")
            i += 2 + (len(m.group()) if m else 0)
        elif d == "0" and zero:
            m = re.match(r"[0-7]{0,3}", s[i + 2:])
            out.append(chr(int(m.group() or "0", 8)))
            i += 2 + len(m.group())
        elif d in "01234567":
            m = re.match(r"[0-7]{1,3}", s[i + 1:])
            out.append(chr(int(m.group(), 8)))
            i += 1 + len(m.group())
        elif d in "uU":
            m = re.match(r"[0-9A-Fa-f]{1,%d}" % (4 if d == "u" else 8), s[i + 2:])
            out.append(chr(int(m.group(), 16)) if m else "\\" + d)
            i += 2 + (len(m.group()) if m else 0)
        else:
            out.append("\\" + d)
            i += 2
    return "".join(out)


def _join_pass(text):
    """backslash-newline is a line continuation (not inside single quotes): remove it."""
    if "\\\n" not in text and "\\\r\n" not in text:
        return text
    st, out, i = _ctx(text), [], 0
    while i < len(text):
        if text[i] == "\\" and st[i] in (0, 2):
            if text.startswith("\n", i + 1):
                i += 2
                continue
            if text.startswith("\r\n", i + 1):
                i += 3
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _ansi_pass(text):
    """$'..' ANSI-C quoting becomes a plain single-quoted string with the escapes decoded."""
    if "$'" not in text:
        return text
    out, i, q, n = [], 0, 0, len(text)
    while i < n:
        c = text[i]
        if q == 1:
            out.append(c)
            if c == "'":
                q = 0
            i += 1
        elif c == "\\" and i + 1 < n:
            out.append(text[i:i + 2])
            i += 2
        elif q == 0 and c == "$" and text.startswith("$'", i):
            j = i + 2
            while j < n and text[j] != "'":
                j += 2 if text[j] == "\\" else 1
            if j < n:
                out.append("'" + _unescape(text[i + 2:j]).replace("'", "'\\''") + "'")
                i = j + 1
            else:
                out.append(c)
                i += 1
        else:
            if c == "'" and q == 0:
                q = 1
            elif c == '"':
                q = 2 if q == 0 else 0
            out.append(c)
            i += 1
    return "".join(out)


_IFS = re.compile(r"(?:\$\{IFS(?:[:#%/^,@*][^}]*)?\}|\$IFS)(?:\$[1-9]|\$\{[1-9]\})?")


def _ifs_pass(text):
    """An unquoted $IFS or ${IFS} separates words: it stands for a space."""
    if "IFS" not in text:
        return text
    st = _ctx(text)
    return _IFS.sub(lambda m: " " if st[m.start()] == 0 else m.group(), text)


def _ins(value, dq):
    """Text that puts `value` back into a command as data, the way the shell would see it."""
    value = value.replace("\r", "").replace("\n", " ")
    if dq:
        return re.sub(r'(["\\$`])', r"\\\1", value)
    return re.sub(r"([;&|()<>$`\"'\\*?\[\]{}!#~])", r"\\\1", value)


def _split_top(text):
    """[(segment, separator)] split at ; && || | & and newline outside quotes."""
    st, out, last, i, n = _ctx(text), [], 0, 0, len(text)
    while i < n:
        if st[i] == 0 and text[i] in ";&|\n":
            j = i
            while j < n and st[j] == 0 and text[j] in ";&|\n":
                j += 1
            out.append((text[last:i], text[i:j]))
            last, i = j, j
        else:
            i += 1
    out.append((text[last:], ""))
    return out


_VAR = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
_DECL = r"^\s*(?:(?:export|declare|typeset|local|readonly)\s+(?:-[A-Za-z]+\s+)*)?"
_ASSIGN_HEAD = re.compile(_DECL + r"([A-Za-z_][A-Za-z0-9_]*)=")


def _subst_vars(text):
    """Substitute NAME=literal assigned earlier in THIS string into later $NAME and ${NAME}.
    A variable set outside the string is never known, and stays as it is."""
    if "$" not in text or "=" not in text:
        return text
    known, out = {}, []
    for seg, sep in _split_top(text):
        if known and "$" in seg:
            st = _ctx(seg)
            seg = _VAR.sub(lambda m: _ins(known[m.group(1) or m.group(2)], st[m.start()] == 2)
                           if (m.group(1) or m.group(2)) in known and st[m.start()] in (0, 2)
                           else m.group(), seg)
        if _ASSIGN_HEAD.match(seg):
            toks = _tokens(re.sub(_DECL, "", seg))
            if toks and all(re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t) for t in toks) \
                    and "$(" not in seg and "`" not in seg:
                for t in toks:
                    k, _, v = t.partition("=")
                    known[k] = v
            else:
                known.pop(_ASSIGN_HEAD.match(seg).group(1), None)
        out.append(seg + sep)
    return "".join(out)


def _match_close(text, j):
    """text[j-1] is an open paren. Index of its matching close paren, or -1."""
    depth, q, k = 1, 0, j
    while k < len(text):
        c = text[k]
        if q == 1:
            q = 0 if c == "'" else 1
        elif c == "\\":
            k += 1
        elif c == "'" and q == 0:
            q = 1
        elif c == '"':
            q = 2 if q == 0 else 0
        elif q == 0 and c == "(":
            depth += 1
        elif q == 0 and c == ")":
            depth -= 1
            if depth == 0:
                return k
        k += 1
    return -1


def _subst_cmds(text):
    """Replace $(...) and `...` whose content is a literal echo / printf / decode pipeline with the
    output. Anything else (a program, a variable, a file) is left exactly as written."""
    if ("$(" not in text and "`" not in text) or text.count("$(") + text.count("`") > MAX_SUBST:
        return text
    st, out, i, n = _ctx(text), [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "$" and text.startswith("$(", i) and not text.startswith("$((", i) \
                and st[i] in (0, 2):
            j = _match_close(text, i + 2)
            if j > 0:
                inner = _subst_cmds(text[i + 2:j])
                lit = _eval_pipeline(inner)
                out.append(_ins(lit.rstrip("\n"), st[i] == 2) if lit is not None
                           else "$(" + inner + ")")
                i = j + 1
                continue
        elif c == "`" and st[i] in (0, 2):
            j = i + 1
            while j < n and text[j] != "`":
                j += 2 if text[j] == "\\" else 1
            if j < n:
                inner = _subst_cmds(re.sub(r"\\([`$\\])", r"\1", text[i + 1:j]))
                lit = _eval_pipeline(inner)
                out.append(_ins(lit.rstrip("\n"), st[i] == 2) if lit is not None
                           else "`" + inner + "`")
                i = j + 1
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _normalize(text):
    t = _join_pass(text)
    t = _ansi_pass(t)
    t = _ifs_pass(t)
    for _ in range(3):
        u = _subst_cmds(_subst_vars(t))
        if u == t:
            break
        t = u
    return t


# ---- literal pipelines: echo / printf into decoders (version 2) ----
def _pipelines(toks):
    """Token list -> list of pipelines, each a list of stages {argv, here, out, file_in}.
    Redirections are consumed. None when a process substitution makes the shape unreadable."""
    pls, cur = [[]], None
    new = lambda: {"argv": [], "here": None, "out": False, "file_in": False}
    cur = new()
    k, n = 0, len(toks)
    while k < n:
        t = toks[k]
        if t.startswith("<(") or t.startswith(">("):
            return None
        if t in ("|", "|&"):
            pls[-1].append(cur)
            cur = new()
        elif t == "<<<":
            cur["here"] = toks[k + 1] if k + 1 < n else ""
            k += 1
        elif t in (">", ">>", ">|", "&>", "&>>", ">&", "<&"):
            if cur["argv"] and re.match(r"^[0-9]$", cur["argv"][-1]) and cur["argv"][-1] != "1" \
                    and t in (">", ">>", ">&", ">|"):
                cur["argv"].pop()
            else:
                if cur["argv"] and cur["argv"][-1] == "1":
                    cur["argv"].pop()
                cur["out"] = True
            k += 1
        elif t in ("<", "<<", "<>"):
            cur["file_in"] = True
            k += 1
        elif t in OPS:
            pls[-1].append(cur)
            pls.append([])
            cur = new()
        else:
            cur["argv"].append(t)
        k += 1
    pls[-1].append(cur)
    return [[s for s in pl if s["argv"] or s["here"] is not None] for pl in pls if pl]


def _lit(s):
    return "$" not in s and "`" not in s


def _tr_set(s):
    out, i = [], 0
    classes = {"[:lower:]": "abcdefghijklmnopqrstuvwxyz", "[:upper:]": "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
               "[:digit:]": "0123456789", "[:alpha:]": "abcdefghijklmnopqrstuvwxyz"
                                                     "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
    s = _unescape(s)
    while i < len(s):
        cls = next((k for k in classes if s.startswith(k, i)), None)
        if cls:
            out.extend(classes[cls])
            i += len(cls)
        elif i + 2 < len(s) and s[i + 1] == "-":
            lo, hi = ord(s[i]), ord(s[i + 2])
            if hi < lo or hi - lo > 512:
                return None
            out.extend(chr(x) for x in range(lo, hi + 1))
            i += 3
        else:
            out.append(s[i])
            i += 1
    return out


def _printf(fmt, args):
    """printf with only %s and %% conversions, else None."""
    parts = re.split(r"(%.)", fmt)
    if any(p.startswith("%") and p not in ("%s", "%b", "%%") for p in parts):
        return None
    nconv = sum(1 for p in parts if p in ("%s", "%b"))
    out, ai = [], 0
    while True:
        for p in parts:
            if p in ("%s", "%b"):
                a = args[ai] if ai < len(args) else ""
                out.append(_unescape(a, True) if p == "%b" else a)
                ai += 1
            elif p == "%%":
                out.append("%")
            else:
                out.append(_unescape(p))
        if nconv == 0 or ai >= len(args) or sum(map(len, out)) > MAX_LITERAL:
            return "".join(out)


def _decode_bytes(raw):
    return None if len(raw) > MAX_LITERAL else raw.decode("utf-8", "replace")


def _stage(argv, data):
    """Run one stage over `data` (str or None). Returns the output string, or None if the stage is
    not a literal producer or decoder we can evaluate."""
    if not argv or not all(_lit(a) for a in argv):
        return None
    if argv[0] in ("command", "builtin") and len(argv) > 1 and argv[1] != "-v":
        argv = argv[1:]
    head, rest = os.path.basename(argv[0]), argv[1:]
    if head in ("which", "command", "type") and len(rest) >= 1 and rest[-1] == "git" \
            and all(a in ("-v", "-p", "-P", "-a") for a in rest[:-1]):
        return "/usr/bin/git\n"       # a path to git: the command word is git
    if head == "echo":
        nl, esc = True, False
        while rest and re.match(r"^-[neE]+$", rest[0]):
            nl = nl and "n" not in rest[0]
            esc = (esc or "e" in rest[0]) and "E" not in rest[0]
            rest = rest[1:]
        s = " ".join(rest)
        return (_unescape(s, True) if esc else s) + ("\n" if nl else "")
    if head == "printf":
        if rest[:1] == ["--"]:
            rest = rest[1:]                 # printf -- FORMAT: -- ends the options (version 3)
        return _printf(rest[0], rest[1:]) if rest else None
    if data is None:
        return None
    if head == "cat" and not rest:
        return data
    if head == "rev" and not rest:
        return "\n".join(l[::-1] for l in data.split("\n"))
    if head in ("base64", "base32", "openssl"):
        flags = [a for a in rest if a.startswith("-")]
        words = [a for a in rest if not a.startswith("-")]
        if head == "openssl":
            ok = ({"base64", "enc"} >= set(words) and "base64" in words + [f.lstrip("-") for f in flags]
                  and "-d" in flags)
            if not ok:
                return None
        elif words or not any(f in ("-d", "-D", "--decode", "-di", "-id") for f in flags) \
                or any(f not in ("-d", "-D", "--decode", "-di", "-id", "-i", "--ignore-garbage")
                       for f in flags):
            return None
        body = re.sub(r"\s+", "", data)
        if head != "base32" and not re.match(r"^[A-Za-z0-9+/]*={0,2}$", body):
            # invalid input: GNU base64 -d prints the valid prefix, then fails; FreeBSD prints
            # nothing. Read the prefix, the larger of the two (version 3).
            m = re.match(r"^(?:[A-Za-z0-9+/]{4})*", body)
            body = m.group(0)
        try:
            if head == "base32":
                body += "=" * (-len(body) % 8)
                return _decode_bytes(base64.b32decode(body))
            body += "=" * (-len(body) % 4)
            return _decode_bytes(base64.b64decode(body, validate=True))
        except (binascii.Error, ValueError):
            if head == "base32":
                return None
            m = re.match(r"^(?:[A-Za-z0-9+/]{4})*", body)     # the valid prefix (version 3)
            try:
                return _decode_bytes(base64.b64decode(m.group(0), validate=True))
            except (binascii.Error, ValueError):
                return None
    if head == "xxd":
        if not rest or any(a not in ("-r", "-p", "-ps", "-rp", "-pr", "-plain", "-rps", "-psr")
                           for a in rest) or not any("r" in a for a in rest) \
                or not any(a in ("-p", "-ps", "-rp", "-pr", "-plain", "-rps", "-psr") for a in rest):
            return None
        try:
            return _decode_bytes(bytes.fromhex(re.sub(r"\s+", "", data)))
        except ValueError:
            return None
    if head == "tr":
        flags = [a for a in rest if a.startswith("-") and len(a) > 1]
        sets = [a for a in rest if not (a.startswith("-") and len(a) > 1)]
        if flags and flags != ["-d"]:
            return None
        a = _tr_set(sets[0]) if sets else None
        if a is None or len(sets) != (1 if flags else 2):
            return None
        if flags:
            return "".join(c for c in data if c not in set(a))
        b = _tr_set(sets[1])
        if not b:
            return None
        b = b + [b[-1]] * (len(a) - len(b))
        table = {}
        for x, y in zip(a, b):
            table.setdefault(x, y)
        return "".join(table.get(c, c) for c in data)
    return None


def _eval_stages(stages):
    data = None
    for s in stages:
        if s["out"] or s["file_in"]:
            return None
        inp = (s["here"] + "\n") if s["here"] is not None else data
        data = _stage(s["argv"], inp)
        if data is None or len(data) > MAX_LITERAL:
            return None
    return data


def _eval_pipeline(inner):
    """The literal output of a pipeline of echo / printf / decoders, or None."""
    if len(inner) > MAX_LITERAL or "\n" in inner.strip() or not inner.strip():
        return None
    toks = _tokens(inner)
    pls = _pipelines(toks) if toks else None
    if not pls or len(pls) != 1 or not pls[0]:
        return None
    return _eval_stages(pls[0])


# ---- text a shell would run (version 2) ----
_SHELL_WORD = re.compile(r"\b(?:sh|bash|zsh|dash|ksh|ash|eval|source)\b|(?:^|[;&|\s])\.\s")
_PROCSUB = re.compile(r"(?:^|[;&|(\n]\s*)(?:\S*/)?(?:sh|bash|zsh|dash|ksh|ash|source|\.)\s+"
                      r"(?:-[A-Za-z]+\s+)*(?:<\s*)?<\(")


def _head(argv):
    i = 0
    while i < len(argv) and (argv[i] in WRAP or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[i])):
        i += 1
    return argv[i:]


def _payloads(text):
    """Literal text that a shell in this command will run: -c strings, eval arguments, a literal
    pipeline or here-string fed to a shell, a literal process substitution fed to a shell."""
    if not _SHELL_WORD.search(text):
        return []
    out = []
    for m in _PROCSUB.finditer(text):
        j = _match_close(text, m.end())
        if j > 0:
            lit = _eval_pipeline(text[m.end():j])
            if lit is not None:
                out.append(lit)
    toks = _tokens(re.sub(r"[\r\n]+", " ; ", text))
    pls = _pipelines(toks) if toks else None
    for pl in pls or []:
        for idx, st in enumerate(pl):
            argv = _head(st["argv"])
            if not argv:
                continue
            word, rest = os.path.basename(argv[0]), argv[1:]
            if word == "eval":
                out.append(" ".join(rest))
            elif word in SHELLS:
                has_c, k = False, 0
                while k < len(rest):
                    a = rest[k]
                    if a in ("-o", "+o", "-O", "+O"):
                        k += 2
                        continue
                    if a.startswith("-") and not a.startswith("--") and len(a) > 1 and "n" in a[1:]:
                        break               # sh -n only checks syntax and runs nothing
                    if a.startswith("-") and not a.startswith("--") and len(a) > 1 and "c" in a[1:]:
                        has_c = True
                        k += 1 if rest[k + 1:k + 2] == ["--"] else 0
                        if k + 1 < len(rest):
                            out.append(rest[k + 1])
                        break
                    if a.startswith("-") or a.startswith("+"):
                        k += 1
                        continue
                    break
                else:
                    k = len(rest)
                if not has_c and (k >= len(rest) or rest[k] in ("-", "--")):
                    if st["here"] is not None:
                        out.append(st["here"])
                    elif idx == len(pl) - 1 and idx > 0:
                        lit = _eval_stages(pl[:idx])
                        if lit is not None:
                            out.append(lit)
            elif word in ("source", ".") and rest[:1] in (["/dev/stdin"], ["-"], ["/dev/fd/0"]):
                if st["here"] is not None:          # a here-string feeds it (version 3)
                    out.append(st["here"])
                elif idx == len(pl) - 1 and idx > 0:
                    lit = _eval_stages(pl[:idx])
                    if lit is not None:
                        out.append(lit)
    return [p for p in out if p and len(p) <= MAX_LITERAL][:MAX_PAYLOADS]


def _guards(view, root, as_written=True):
    """Every policy over one view of the command. A deny reason, or None. Policy B has two forms:
    the version 1 regex, which splits on | even inside quotes, and the token form. The regex runs
    only on text as written (what version 1 saw). Text that normalization built gets the token
    form, because a substituted value can carry a quoted | that the regex would misread."""
    return (blanket_stage_guard(view, root) or (hook_bypass_guard(view) if as_written else None)
            or hook_bypass_tokens(view) or data_loss_guard(view, root))


def _check(cmd, root, depth):
    nohd = _strip_heredocs(cmd)
    views = [nohd]
    why = _guards(nohd, root)          # the text as written: exactly what version 1 checked
    if why:
        return why
    norm = _normalize(nohd)
    if norm != nohd:
        views.append(norm)
        why = _guards(norm, root, as_written=False)
        if why:
            return why
    if depth < MAX_DEPTH:
        seen = set()
        for v in views:
            for p in _payloads(v):
                if p in seen:
                    continue
                seen.add(p)
                why = _check(p, root, depth + 1)
                if why:
                    return why + " (found in text the shell would run)"
    return None


# =====================================================================================
# VERSION 3: resolve more of the shell, unwrap every wrapper, and FAIL CLOSED.
# A string reader cannot see runtime state. When a git command (or a wrapper or shell that
# would run one) carries a part the guard cannot resolve, and that part could make it a
# policy A, B or C violation, the verdict is "ask": a human decides. Every v2 block stays a
# block, because decide() runs the version 2 check first, unchanged.
# =====================================================================================
U, Q = "\x01", "\x02"      # an expansion the guard could not resolve: U unquoted (may split), Q quoted
PSUB = "\x03"              # marks a process substitution <(...) in resolved text: PSUB + index + PSUB
KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "(", "time", "coproc"}
NUMERIC_VARS = {"RANDOM", "LINENO", "SECONDS", "UID", "EUID", "PPID", "BASHPID", "SRANDOM", "OPTIND"}
HOOKED3 = ("commit", "push", "merge", "rebase", "am", "cherry-pick", "revert", "pull")
KNOWN_GIT = set((
    "add am annotate apply archimport archive backfill bisect blame branch bugreport bundle cat-file "
    "check-attr check-ignore check-mailmap check-ref-format checkout checkout-index cherry cherry-pick "
    "citool clean clone column commit commit-graph commit-tree config count-objects credential "
    "credential-cache credential-netrc credential-osxkeychain credential-store cvsexportcommit cvsimport "
    "cvsserver daemon describe diagnose diff diff-files diff-index diff-pairs diff-tree difftool "
    "fast-export fast-import fetch fetch-pack filter-branch fmt-merge-msg for-each-ref for-each-repo "
    "format-patch fsck fsck-objects gc get-tar-commit-id grep gui hash-object help history hook "
    "http-backend http-fetch http-push imap-send index-pack init init-db instaweb interpret-trailers jump "
    "last-modified lfs log ls-files ls-remote ls-tree mailinfo mailsplit maintenance merge merge-base "
    "merge-file merge-index merge-octopus merge-one-file merge-ours merge-recursive merge-recursive-ours "
    "merge-recursive-theirs merge-resolve merge-subtree merge-tree mergetool mktag mktree multi-pack-index "
    "mv name-rev notes p4 pack-objects pack-redundant pack-refs patch-id pickaxe prune prune-packed pull "
    "push quiltimport range-diff read-tree rebase receive-pack reflog refs remote remote-ext remote-fd "
    "remote-ftp remote-ftps remote-http remote-https repack replace replay repo request-pull rerere reset "
    "restore rev-list rev-parse revert rm send-email send-pack shell shortlog show show-branch show-index "
    "show-ref sparse-checkout stage stash status stripspace submodule subtree switch symbolic-ref tag "
    "unpack-file unpack-objects update-index update-ref update-server-info upload-archive upload-pack var "
    "verify-commit verify-pack verify-tag version whatchanged worktree write-tree").split())
RISKY = {"add", "stage", "commit", "push", "reset", "clean", "checkout", "restore", "switch", "branch",
         "stash", "config", "merge", "rebase", "am", "cherry-pick", "revert", "pull", "rm", "mv",
         "worktree", "reflog", "symbolic-ref", "read-tree", "checkout-index", "update-index",
         "submodule", "bisect", "update-ref", "send-pack", "commit-tree"}
PATH_SENS = {"add", "stage", "commit", "checkout", "restore", "rm", "mv", "checkout-index", "update-index"}
REWRITERS = {"filter-branch", "history", "replay", "fast-import", "http-push"}
VAL3 = {
    "commit": {"-m", "--message", "-F", "--file", "-C", "--reuse-message", "-c", "--reedit-message",
               "--author", "--date", "--cleanup", "--trailer", "-t", "--template", "--fixup", "--squash"},
    "push": {"-o", "--push-option", "--repo", "--receive-pack", "--exec"},
    "checkout": {"-b", "-B", "--orphan"}, "switch": {"-c", "-C", "--orphan"},
    "branch": {"--set-upstream-to", "-u", "--format", "--contains", "--no-contains", "--merged",
               "--no-merged", "--points-at", "--sort"},
    "merge": {"-m", "-F", "-s", "-X", "--strategy", "--strategy-option", "--message", "--file",
              "--into-name"},
    "rebase": {"--onto", "-s", "-X", "--strategy", "--strategy-option", "-x", "--exec"},
    "cherry-pick": {"-m", "--mainline", "-X", "--strategy-option", "--strategy"},
    "revert": {"-m", "--mainline", "-X", "--strategy-option", "--strategy"},
    "pull": {"-s", "-X", "--strategy", "--strategy-option", "--depth"},
    "clean": {"-e", "--exclude"}, "restore": {"-s", "--source"}, "worktree": {"-b", "-B", "--reason"},
    "add": {"--chmod"}, "stash": {"-m", "--message"}, "am": {"--directory"}, "reset": set(), "rm": set(),
}
SHELLS3 = SHELLS | {"fish"}
READONLY = {"cat", "less", "more", "head", "tail", "ls", "stat", "file", "wc", "grep", "egrep", "fgrep",
            "rg", "ag", "diff", "cmp", "md5", "md5sum", "shasum", "sha1sum", "sha256sum", "tree", "du",
            "echo", "printf", "test", "[", "[[", "realpath", "readlink", "basename", "dirname", "bat",
            "od", "hexdump", "strings", "sort", "uniq", "cut", "true", "false", ":", "cd", "pushd",
            "popd", "git", "which", "type", "command", "file", "view", "nl", "column", "shellcheck"}
_HOOKS_RE = re.compile(r"(?:^|/)(?:\.git/hooks|\.githooks|\.husky)(?:/|$)")
_GITDIR_RE = re.compile(r"(?:^|/)\.git(?:/(?:refs|objects|logs|HEAD|index|packed-refs|config|\*)(?:/.*)?)?/?$")
_GITLOCK_RE = re.compile(r"(?:^|/)\.git/.*\.lock$")
_GITANY_RE = re.compile(r"(?:^|/)\.git/")
_GITCONFIG_RE = re.compile(r"(?:^|/)\.git/config$")
_CMD_KEY = re.compile(r"^(?:core\.(?:fsmonitor|sshcommand|pager|editor|askpass|alternaterefscommand)|"
                      r"sequence\.editor|diff\.external|diff\..+\.(?:textconv|command)|merge\..+\.driver|"
                      r"filter\..+\.(?:clean|smudge|process)|credential\.helper|credential\..+\.helper|"
                      r"gpg\.program|gpg\..+\.program|pager\..+|uploadpack\.packobjectshook|"
                      r"(?:diff|merge)tool\..+\.cmd|browser\..+\.cmd|sendemail\..+\.cmd)$")
CMD_ENV = ("GIT_SSH_COMMAND", "GIT_SSH", "GIT_EXTERNAL_DIFF", "GIT_PAGER", "PAGER", "GIT_EDITOR", "EDITOR",
           "VISUAL", "GIT_SEQUENCE_EDITOR", "GIT_ASKPASS", "SSH_ASKPASS", "GIT_PROXY_COMMAND")
FAIL = "fail_closed: "
ASK_TAIL = (". A string reader cannot see this until run time, so it cannot prove the command safe. "
            "A human decides.")


def _dyn(s):
    return U in s or Q in s


def _lit3(s):
    return not (U in s or Q in s or PSUB in s)


def _esc_word(w):
    """One word, escaped so the shell (and shlex) read it back as exactly one word."""
    w = w.replace("\r", "").replace("\n", " ")
    return re.sub(r"([\s;&|()<>$`\"'\\*?\[\]{}!#~])", r"\\\1", w)


def _dq_esc(v):
    return re.sub(r'(["\\$`])', r"\\\1", v.replace("\r", "").replace("\n", " "))


def _unq(text):
    """Text with shell quoting removed, for use as a pattern. Approximate."""
    t = _tokens(text)
    return "".join(t) if t else text


def _close_brace(text, j):
    """text[j-1] is the '{' of '${'. Index of the matching '}', or -1."""
    depth, q, k = 1, 0, j
    while k < len(text):
        c = text[k]
        if q == 1:
            q = 0 if c == "'" else 1
        elif c == "\\":
            k += 1
        elif c == "'" and q == 0:
            q = 1
        elif c == '"':
            q = 2 if q == 0 else 0
        elif q == 0 and c == "{":
            depth += 1
        elif q == 0 and c == "}":
            depth -= 1
            if depth == 0:
                return k
        k += 1
    return -1


def _skip_construct(text, i):
    """If text[i:] opens $( $(( ${ <( >( or a backtick, the index just past its close, else None."""
    if text.startswith("$(", i) or ((text.startswith("<(", i) or text.startswith(">(", i))):
        j = _match_close(text, i + 2)
        return j + 1 if j > 0 else None
    if text.startswith("${", i):
        j = _close_brace(text, i + 2)
        return j + 1 if j > 0 else None
    if text[i] == "`":
        j = i + 1
        while j < len(text) and text[j] != "`":
            j += 2 if text[j] == "\\" else 1
        return j + 1 if j < len(text) else None
    return None


def _segments3(text):
    """[(segment, separator)] at top-level ; & | && || and newline, outside quotes and outside
    $( ), ${ }, <( ), backticks. `2>&1` and `&>` are redirections, not separators."""
    out, last, i, n, q = [], 0, 0, len(text), 0
    while i < n:
        c = text[i]
        if q == 1:
            q = 0 if c == "'" else 1
            i += 1
            continue
        if c == "\\":
            i += 2
            continue
        if c == "'" and q == 0:
            q = 1
            i += 1
            continue
        if c == '"':
            q = 2 if q == 0 else 0
            i += 1
            continue
        if c in "$<>`":
            j = _skip_construct(text, i) if (q == 0 or c in "$`") else None
            if j:
                i = j
                continue
        if q == 0 and c in ";&|\n":
            if c == "&" and ((i > 0 and text[i - 1] in "<>") or text.startswith(">", i + 1)):
                i += 1
                continue
            j = i
            while j < n and text[j] in ";&|\n":
                j += 1
            out.append((text[last:i], text[i:j]))
            last = i = j
            continue
        i += 1
    out.append((text[last:], ""))
    return out


def _glob_re(pat, anchor_start=False, anchor_end=False):
    rx, i = [], 0
    while i < len(pat):
        c = pat[i]
        if c == "*":
            rx.append(".*")
        elif c == "?":
            rx.append(".")
        elif c == "[":
            j = pat.find("]", i + 2)
            if j > 0:
                rx.append("[" + pat[i + 1:j].replace("!", "^", 1) + "]")
                i = j
            else:
                rx.append(re.escape(c))
        elif c == "\\" and i + 1 < len(pat):
            rx.append(re.escape(pat[i + 1]))
            i += 1
        else:
            rx.append(re.escape(c))
        i += 1
    return ("^" if anchor_start else "") + "".join(rx) + ("$" if anchor_end else "")


class _R(object):
    """Resolves one command string: variables assigned literally earlier in the SAME string,
    parameter operators, arrays, read and printf -v, literal for-loops, aliases and functions,
    literal command substitutions. Anything else becomes a U or Q sentinel."""

    def __init__(self, known=None, pos=None, mode="main", choice=None, funcs=None):
        self.known = dict(known or {})
        self.pos = pos
        self.mode = mode
        self.choice = choice or {}
        self.loops, self.payloads, self.psubs = [], [], []
        self.alt = False
        self.aliases = {}
        self.funcs = dict(funcs or {})
        self.assigned = {}
        self.nloop = 0

    # ---- values ----
    def ifs(self):
        if "IFS" not in self.known:
            return None
        v = self.known["IFS"]
        if not isinstance(v, str) or _dyn(v):
            return U
        return None if v == " \t\n" else v

    def sentinel(self, q, multi=False):
        return U if (q == 0 or multi) else Q

    def ins(self, value, q):
        if q == 2:
            return _dq_esc(value.replace(U, Q))
        value = value.replace(Q, U)
        ifs = self.ifs()
        if ifs == U:
            return U if value else ""
        if ifs is None:
            words = value.split()
        elif ifs == "":
            words = [value] if value else []
        else:
            words = [w for w in re.split("[" + re.escape(ifs) + "]+", value) if w != ""]
        return " ".join(_esc_word(w) for w in words)

    def ins_list(self, vals, q, at):
        if q == 2 and at:
            return '" "'.join(_dq_esc(v.replace(U, Q)) for v in vals)
        if q == 2:
            return _dq_esc(" ".join(vals).replace(U, Q))
        return " ".join(self.ins(v, 0) for v in vals)

    def lookup(self, name, idx=None):
        if name in ("@", "*"):
            return list(self.pos) if self.pos is not None else None
        if name.isdigit():
            if name == "0":
                return "bash"
            if self.pos is None:
                return None
            k = int(name) - 1
            return self.pos[k] if k < len(self.pos) else ""
        if name in ("#", "?", "$", "!") or name in NUMERIC_VARS:
            return "0"
        if name == "-":
            return "hB"
        if name not in self.known:
            return None
        v = self.known[name]
        if idx:
            if idx in ("[@]", "[*]"):
                return v if isinstance(v, list) else [v]
            m = re.match(r"^\[(\d+)\]$", idx)
            if not m:
                return None
            k = int(m.group(1))
            if isinstance(v, list):
                return v[k] if k < len(v) else ""
            return v if k == 0 else ""
        if isinstance(v, list):
            return v[0] if v else ""
        return v

    def positional(self, which, q):
        v = self.lookup(which)
        if v is None:
            return self.sentinel(q, which in "@*")
        if isinstance(v, list):
            return self.ins_list(v, q, which == "@")
        return self.ins(v, q)

    def param(self, body, q):
        if body.startswith("#") and len(body) > 1:
            return "0"
        indirect = body.startswith("!")
        if indirect:
            body = body[1:]
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*|[0-9]+|[@*#?$!-])(\[[^\]]*\])?", body)
        if not m:
            return self.sentinel(q)
        name, idx, rest = m.group(1), m.group(2), body[m.end():]
        val = self.lookup(name, idx)
        if indirect:
            val = (self.lookup(val) if isinstance(val, str) and re.match(r"^[A-Za-z_]\w*$", val)
                   and not rest else None)
        multi = idx in ("[@]", "[*]") or name in ("@", "*")
        mo = re.match(r"(:-|:=|:\+|:\?|-|=|\+|\?|##|#|%%|%|//|/#|/%|/|\^\^|\^|,,|,|@[QEPAaUuLK]|:)", rest)
        if rest and not mo:
            return self.sentinel(q, multi)
        op, word = (mo.group(1), rest[mo.end():]) if mo else (None, "")
        if val is None:
            if op in (":-", ":=", "-", "="):
                self.alt = True
                if self.mode == "default":
                    if op in (":=", "="):
                        self.known[name] = _unq(self.expand(word, 0))
                    return self.expand(word, q)
            return self.sentinel(q, multi)
        if isinstance(val, list):
            if op is None:
                return self.ins_list(val, q, idx == "[@]" or name == "@")
            val = " ".join(val)
        if op is None:
            return self.ins(val, q)
        if _dyn(val) and op not in (":-", ":=", "-", "=", "?", ":?"):
            return self.sentinel(q, multi)
        if op in (":-", ":="):
            if val != "":
                return self.ins(val, q)
            if op == ":=":
                self.known[name] = _unq(self.expand(word, 0))
            return self.expand(word, q)
        if op in ("-", "=", "?", ":?"):
            return self.ins(val, q)
        if op == ":+":
            return self.expand(word, q) if val != "" else ""
        if op == "+":
            return self.expand(word, q)
        if op == ":":
            mm = re.match(r"^\s*(-?\d+)\s*(?::\s*(-?\d+)\s*)?$", word)
            if not mm:
                return self.sentinel(q)
            off = int(mm.group(1))
            if off < 0:
                off = max(0, len(val) + off)
            res = val[off:]
            if mm.group(2) is not None:
                ln = int(mm.group(2))
                res = res[:ln] if ln >= 0 else res[:max(0, len(res) + ln)]
            return self.ins(res, q)
        if op in ("#", "##", "%", "%%"):
            pat = _unq(self.expand(word, 0))
            if _dyn(pat):
                return self.sentinel(q)
            rng = range(len(val) + 1) if op in ("#", "%") else range(len(val), -1, -1)
            res = val
            for k in rng:
                part = val[:k] if op in ("#", "##") else val[len(val) - k:]
                if re.match(_glob_re(pat, True, True), part, re.S):
                    res = val[k:] if op in ("#", "##") else val[:len(val) - k]
                    break
            return self.ins(res, q)
        if op in ("/", "//", "/#", "/%"):
            parts = re.split(r"(?<!\\)/", word, 1)
            pat, rep = _unq(self.expand(parts[0], 0)), _unq(self.expand(parts[1], 0)) if len(parts) > 1 else ""
            if _dyn(pat) or _dyn(rep) or not pat:
                return self.sentinel(q) if (_dyn(pat) or _dyn(rep)) else self.ins(val, q)
            rx = _glob_re(pat, op == "/#", op == "/%")
            res = re.sub(rx, lambda _m: rep, val, count=0 if op == "//" else 1, flags=re.S)
            return self.ins(res, q)
        if op in ("^", "^^", ",", ",,"):
            res = {"^": val[:1].upper() + val[1:], "^^": val.upper(), ",": val[:1].lower() + val[1:],
                   ",,": val.lower()}[op]
            return self.ins(res, q)
        if op in ("@U", "@u", "@L", "@E", "@Q", "@P", "@A", "@a", "@K"):
            res = {"@U": val.upper(), "@u": val[:1].upper() + val[1:], "@L": val.lower(),
                   "@E": _unescape(val)}.get(op, val)
            return self.ins(res, q)
        return self.sentinel(q, multi)

    def cmdsub(self, inner, q):
        sub = _R(self.known, self.pos, self.mode, None, self.funcs)
        inner_r = sub.resolve(inner)
        self.payloads.extend(sub.payloads)
        self.alt = self.alt or sub.alt
        lit = _eval_pipeline(inner_r) if _lit3(inner_r) else None
        if lit is not None:
            return self.ins(lit.rstrip("\n"), q)
        self.payloads.append((inner_r, None, None))
        return self.sentinel(q)

    def dollar(self, text, i, q):
        nxt = text[i + 1]
        if text.startswith("$((", i):
            j = _match_close(text, i + 2)
            if j > 0:
                self.expand(text[i + 3:j - 1], 2)   # arithmetic is digits, but a $(...) inside it runs
                return "0", j + 1
        if nxt == "(":
            j = _match_close(text, i + 2)
            return (self.cmdsub(text[i + 2:j], q), j + 1) if j > 0 else None
        if nxt == "[":
            j = text.find("]", i)
            return ("0", j + 1) if j > 0 else None
        if nxt == "{":
            j = _close_brace(text, i + 2)
            return (self.param(text[i + 2:j], q), j + 1) if j > 0 else None
        if nxt == '"' and q == 0:
            return "", i + 1
        m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", text[i + 1:])
        if m:
            name = m.group()
            v = self.lookup(name)
            if v is None:
                return self.sentinel(q), i + 1 + m.end()
            return self.ins(v if isinstance(v, str) else (v[0] if v else ""), q), i + 1 + m.end()
        if nxt in "@*" or nxt.isdigit():
            return self.positional(nxt, q), i + 2
        if nxt in "#?$!":
            return "0", i + 2
        if nxt == "-":
            return "hB", i + 2
        return None

    def expand(self, text, q=0):
        out, i, n = [], 0, len(text)
        while i < n:
            c = text[i]
            if q == 1:
                out.append(c)
                if c == "'":
                    q = 0
                i += 1
                continue
            if c == "\\" and i + 1 < n:
                out.append(text[i:i + 2])
                i += 2
                continue
            if c == "'" and q == 0:
                q = 1
                out.append(c)
                i += 1
                continue
            if c == '"':
                q = 2 if q == 0 else 0
                out.append(c)
                i += 1
                continue
            if c == "$" and i + 1 < n:
                r = self.dollar(text, i, q)
                if r is not None:
                    out.append(r[0])
                    i = r[1]
                    continue
            if c == "~" and q == 0 and (i == 0 or text[i - 1] in " \t\n=:;&|(") and \
                    (i + 1 == n or text[i + 1] in "/ \t\n;&|)"):
                out.append(U)                   # ~ is $HOME, which the guard cannot see
                i += 1
                continue
            if c == "`":
                j = i + 1
                while j < n and text[j] != "`":
                    j += 2 if text[j] == "\\" else 1
                if j < n:
                    out.append(self.cmdsub(re.sub(r"\\([`$\\])", r"\1", text[i + 1:j]), q))
                    i = j + 1
                    continue
            if q == 0 and c in "<>" and text.startswith("(", i + 1):
                j = _match_close(text, i + 2)
                if j > 0:
                    sub = _R(self.known, self.pos, self.mode, None, self.funcs)
                    inner = sub.resolve(text[i + 2:j])
                    self.payloads.extend(sub.payloads)
                    self.payloads.append((inner, None, None))
                    self.psubs.append(inner)
                    out.append(PSUB + str(len(self.psubs) - 1) + PSUB)
                    i = j + 1
                    continue
            out.append(c)
            i += 1
        return "".join(out)

    # ---- statements ----
    def strip_funcs(self, text):
        """Shell function definitions are recorded and replaced by ':'. A call runs the body."""
        if "(" not in text and "function" not in text:
            return text
        head = re.compile(r"(?:^|(?<=[;&|\n(){}]))\s*(?:function\s+([A-Za-z_][\w:.-]*)\s*(?:\(\s*\))?"
                          r"|([A-Za-z_][\w:.-]*)\s*\(\s*\))\s*\{")
        for _ in range(8):
            st = _ctx(text)
            m = next((m for m in head.finditer(text) if st[m.end() - 1] == 0), None)
            if not m:
                break
            k, depth, q = m.end(), 1, 0
            while k < len(text):
                c = text[k]
                if q == 1:
                    q = 0 if c == "'" else 1
                elif c == "\\":
                    k += 1
                elif c == "'" and q == 0:
                    q = 1
                elif c == '"':
                    q = 2 if q == 0 else 0
                elif q == 0 and text.startswith("${", k):
                    j = _close_brace(text, k + 2)
                    k = j if j > 0 else k
                elif q == 0 and c == "{":
                    depth += 1
                elif q == 0 and c == "}":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            if k >= len(text):
                break
            self.funcs[m.group(1) or m.group(2)] = text[m.end():k]
            text = text[:m.start()] + " :" + text[k + 1:]
        return text

    def apply_alias(self, seg):
        for _ in range(3):
            m = re.match(r"^(\s*(?:(?:then|do|else|elif|if|while|until|!|\{|\()\s+)*)([^\s;|&<>()=]+)(.*)$",
                         seg, re.S)
            if not m or m.group(2) not in self.aliases:
                return seg
            seg = m.group(1) + self.aliases[m.group(2)] + m.group(3)
        return seg

    def effects(self, seg):
        toks = _tokens(seg)
        if not toks:
            return
        while toks and toks[0] in KEYWORDS:
            toks = toks[1:]
        if not toks:
            return
        if toks[0] in ("for", "select") and len(toks) >= 2 and re.match(r"^[A-Za-z_]\w*$", toks[1]):
            name = toks[1]
            vals = [t for t in toks[3:] if t != "do"] if len(toks) > 2 and toks[2] == "in" else None
            if vals and len(vals) <= 16 and all(_lit3(v) for v in vals):
                k = self.nloop
                self.nloop += 1
                self.loops.append((k, vals))
                self.known[name] = vals[min(self.choice.get(k, 0), len(vals) - 1)]
            else:
                self.known[name] = U
            return
        prefix = []
        while toks and toks[0] in ("export", "declare", "typeset", "local", "readonly"):
            toks = toks[1:]
            while toks and re.match(r"^[-+][A-Za-z]+$", toks[0]):
                toks = toks[1:]
            prefix.append("decl")
        env = {}
        k = 0
        while k < len(toks) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*\+?=", toks[k]):
            name, _, v = toks[k].partition("=")
            if v == "" and k + 1 < len(toks) and toks[k + 1] == "(":
                j = toks.index(")", k + 1) if ")" in toks[k + 1:] else len(toks)
                env[name] = toks[k + 2:j]
                k = j + 1
                continue
            env[name] = v
            k += 1
        rest = toks[k:]
        if not rest or (prefix and all(re.match(r"^[A-Za-z_]\w*$", t) for t in rest)):
            for name, v in env.items():
                if name.endswith("+"):
                    name = name[:-1]
                    old = self.known.get(name, "")
                    v = (old if isinstance(old, list) else [old]) + v if isinstance(v, list) \
                        else (old if isinstance(old, str) else " ".join(old)) + v
                self.known[name] = v
                self.assigned[name] = v
            for t in rest:
                self.known.setdefault(t, "")
            return
        for name, v in env.items():
            self.assigned[name.rstrip("+")] = v if isinstance(v, str) else " ".join(v)
        cmd, args = rest[0], rest[1:]
        if cmd == "set" and "--" in args:
            self.pos = list(args[args.index("--") + 1:])
        elif cmd == "unset":
            for t in args:
                if not t.startswith("-"):
                    self.known[t] = ""
        elif cmd == "read":
            self.read(args, env.get("IFS"))
        elif cmd in ("mapfile", "readarray", "getopts"):
            names = [a for a in args if re.match(r"^[A-Za-z_]\w*$", a)]
            for nm in (names[-1:] or (["MAPFILE"] if cmd != "getopts" else [])):
                self.known[nm] = U
        elif cmd == "printf" and len(args) >= 3 and args[0] == "-v":
            out = _printf(args[2], args[3:]) if all(_lit3(a) and _lit(a) for a in args) else None
            self.known[args[1]] = out if out is not None else U
        elif cmd == "alias":
            for a in args:
                if "=" in a:
                    nm, _, v = a.partition("=")
                    self.aliases[nm] = v
        elif cmd == "unalias":
            for a in args:
                self.aliases.pop(a, None)
        elif cmd in self.funcs:
            self.payloads.append((self.funcs[cmd], dict(self.known), list(args)))

    def read(self, args, ifs_env):
        names, arr, k, here = [], None, 0, None
        while k < len(args):
            a = args[k]
            if a == "<<<":
                here = args[k + 1] if k + 1 < len(args) else ""
                break
            if a in ("<", "<<", "|"):
                break
            if a.startswith("-") and len(a) > 1:
                for j, ch in enumerate(a[1:]):
                    if ch in "adpnNtu":
                        val = a[j + 2:] or (args[k + 1] if k + 1 < len(args) else "")
                        if not a[j + 2:]:
                            k += 1
                        if ch == "a":
                            arr = val
                        break
                k += 1
                continue
            names.append(a)
            k += 1
        if arr is None and not names:
            names = ["REPLY"]
        if here is None or _dyn(here):
            for nm in names + ([arr] if arr else []):
                self.known[nm] = U
            return
        ifs = ifs_env if ifs_env is not None else self.known.get("IFS", " \t\n")
        ifs = ifs if isinstance(ifs, str) and not _dyn(ifs) else " \t\n"
        rx = "[" + re.escape(ifs) + "]+" if ifs else None
        fields = [f for f in (re.split(rx, here.strip()) if rx else [here]) if f != ""]
        if arr:
            self.known[arr] = fields
        for j, nm in enumerate(names):
            if j == len(names) - 1 and rx:
                rest = re.split(rx, here.strip(), maxsplit=j) if j else [here.strip()]
                self.known[nm] = rest[-1] if len(rest) > j else ""
            else:
                self.known[nm] = fields[j] if j < len(fields) else ""

    def resolve(self, text):
        text = self.strip_funcs(text)
        out = []
        for seg, sep in _segments3(text):
            r = self.apply_alias(self.expand(seg))
            self.effects(r)
            out.append(r + sep)
        return "".join(out)


def _brace_word(w, budget):
    st = _ctx(w)
    for i, c in enumerate(w):
        if c != "{" or st[i] != 0 or (i > 0 and w[i - 1] == "$"):
            continue
        depth, j, commas = 0, i, []
        while j < len(w):
            if st[j] == 0 and w[j] == "{":
                depth += 1
            elif st[j] == 0 and w[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            elif st[j] == 0 and w[j] == "," and depth == 1:
                commas.append(j)
            j += 1
        if j >= len(w):
            return [w]
        inner = w[i + 1:j]
        if commas:
            cuts = [i] + commas + [j]
            alts = [w[cuts[k] + 1:cuts[k + 1]] for k in range(len(cuts) - 1)]
        else:
            m = re.match(r"^(-?\d+|[A-Za-z])\.\.(-?\d+|[A-Za-z])$", inner)
            if not m:
                continue
            a, b = m.group(1), m.group(2)
            if a.lstrip("-").isdigit() and b.lstrip("-").isdigit():
                lo, hi = int(a), int(b)
                rng = range(lo, hi + 1) if lo <= hi else range(lo, hi - 1, -1)
                alts = [str(x) for x in rng][:64]
            elif len(a) == 1 and len(b) == 1 and a.isalpha() and b.isalpha():
                lo, hi = ord(a), ord(b)
                alts = [chr(x) for x in (range(lo, hi + 1) if lo <= hi else range(lo, hi - 1, -1))]
            else:
                continue
        out = []
        for a in alts:
            if len(out) >= budget:
                break
            out.extend(_brace_word(w[:i] + a + w[j + 1:], budget))
        return out[:budget]
    return [w]


def _brace_pass(text):
    """Unquoted brace expansion: --{hard,soft} becomes --hard --soft. At most 64 words each."""
    if "{" not in text or ("," not in text and ".." not in text):
        return text
    st, out, i, n = _ctx(text), [], 0, len(text)
    while i < n:
        if st[i] == 0 and text[i] in " \t\n;&|()<>":
            out.append(text[i])
            i += 1
            continue
        j = i
        while j < n and not (st[j] == 0 and text[j] in " \t\n;&|()<>"):
            j += 1
        word = text[i:j]
        out.append(" ".join(_brace_word(word, 64)) if "{" in word else word)
        i = j
    return "".join(out)


def _heredoc_bodies(cmd):
    """[(delimiter, body)] for every terminated heredoc, in order."""
    if "<<" not in cmd:
        return []
    lines, out, i = cmd.split("\n"), [], 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if "<<" not in line:
            continue
        lt = _tokens(line) or []
        for k in range(len(lt) - 1):
            if lt[k] == "<<":
                d = lt[k + 1].lstrip("-")
                end = next((j for j in range(i, len(lines)) if lines[j].strip() == d), None)
                if end is not None:
                    quoted = bool(re.search(r"<<-?\s*(?:\\|['\"])\s*" + re.escape(d) + r"|<<-?\s*" +
                                            re.escape(d) + r"['\"]", line)) or "\\" in lt[k + 1]
                    out.append((d, "\n".join(lines[i:end]), quoted))
                    i = end + 1
    return out


def _parse3(text, bodies):
    """Resolved text -> pipelines of stages {argv, here, out, file_in, redirs, pipe_in}."""
    toks = _tokens(re.sub(r"[\r\n]+", " ; ", text))
    if toks is None:
        return None
    used = set()
    new = lambda pipe_in: {"argv": [], "here": None, "out": False, "file_in": False, "redirs": [],
                           "pipe_in": pipe_in}
    pls, cur, k, n = [[]], new(False), 0, len(toks)
    while k < n:
        t = toks[k]
        if t and all(ch in ";&|()" for ch in t):
            pls[-1].append(cur)
            if t.endswith("|") or t.endswith("|&"):
                cur = new(True)
            else:
                pls.append([])
                cur = new(False)
        elif t in ("<", ">", ">>", ">|", "<>", "&>", "&>>", ">&", "<&", "<<", "<<<", "<<-"):
            tgt = toks[k + 1] if k + 1 < n else ""
            if cur["argv"] and re.match(r"^[0-9]$", cur["argv"][-1]):
                cur["argv"].pop()
            if t in ("<<", "<<-"):
                d = tgt.lstrip("-")
                j = next((j for j, bd in enumerate(bodies) if bd[0] == d and j not in used), None)
                if j is not None:
                    used.add(j)
                    cur["here"] = bodies[j][1]
                    cur["heredoc"] = True
            elif t == "<<<":
                cur["here"] = tgt
            elif t in (">&", "<&") and re.match(r"^(\d+|-)$", tgt):
                pass
            else:
                cur["redirs"].append((t, tgt))
                if t in ("<", "<>"):
                    cur["file_in"] = True
                else:
                    cur["out"] = True
            k += 1
        else:
            cur["argv"].append(t)
        k += 1
    pls[-1].append(cur)
    return [[s for s in pl if s["argv"] or s["here"] is not None or s["redirs"]] for pl in pls]


class _St(object):
    """What one walk over one view collects."""

    def __init__(self, root, r, bodies, depth):
        self.root, self.r, self.bodies, self.depth = root, r, bodies, depth
        self.cwd = root
        self.asks, self.payloads, self.canon = [], [], []
        self.git_aliases = {}
        self.files = {}             # a file written earlier in this string: path -> text (or U)

    def script(self, path, what):
        """A script file run by a shell or by path. Known only if this string wrote it."""
        a = _abs(path, self.cwd)
        if a in self.files:
            if _lit3(self.files[a]):
                self.run(self.files[a])
            else:
                self.ask(what + " a script this command wrote with text the guard cannot compute")

    def ask(self, why):
        self.asks.append(FAIL + why + ASK_TAIL)

    def run(self, text):
        self.payloads.append((text, None, None))


# ---- paths ----
def _abs(p, cwd):
    if not p or _dyn(p) or p.startswith("~") or PSUB in p:
        return None
    if p.startswith("/"):
        return posixpath.normpath(p)
    return posixpath.normpath(posixpath.join(cwd, p)) if cwd else posixpath.normpath(p)


def _pclass(p, cwd):
    if p and (_dyn(p) or PSUB in p):
        pre = re.split("[" + U + Q + PSUB + "]", p)[0]
        if "/" not in pre:
            return None
        a = _abs(pre.rsplit("/", 1)[0] + "/x", cwd)
        return "hooks" if a and _HOOKS_RE.search(a) else ("gitdir" if a and re.search(
            r"(?:^|/)\.git/(?:refs|objects|logs)(?:/|$)", a) else None)
    a = _abs(p, cwd)
    if a is None:
        return None
    if _HOOKS_RE.search(a) or _HOOKS_RE.search(p):
        return "hooks"
    if _GITLOCK_RE.search(a):
        return "lock"
    if _GITDIR_RE.search(a):
        return "gitdir"
    if _GITANY_RE.search(a):
        return "git"
    return "path"


def _is_root_or_above(a, root):
    a = a.rstrip("/") or "/"
    return a == root or a == "/" or root.startswith(a + "/")


def _pathspec_whole(arg, cwd, root):
    """Does this git pathspec name the whole tree (or the tree minus some paths)?
    -> "whole", "exclude" (an exclusion pathspec), or None."""
    if _dyn(arg):
        return None
    path, top, excl = arg, False, False
    if arg.startswith(":("):
        j = arg.find(")")
        if j > 0:
            magic = [m.strip().split(":")[0].lower() for m in arg[2:j].split(",")]
            path, top, excl = arg[j + 1:], "top" in magic, "exclude" in magic
    elif arg.startswith(":") and len(arg) > 1 and arg[1] in "/!^":
        k = 1
        while k < len(arg) and arg[k] in "/!^":
            top = top or arg[k] == "/"
            excl = excl or arg[k] in "!^"
            k += 1
        if k < len(arg) and arg[k] == ":":
            k += 1
        path = arg[k:]
    if excl:
        return "exclude"
    if _whole_tree(path, root) and not top:
        return "whole"
    base = root if top else cwd
    if base is None:
        return "whole" if path.rstrip("/") in ("./*", "**", "**/*", "*/**") else None
    a = posixpath.normpath(posixpath.join(base, path)) if path else base
    while posixpath.basename(a) in ("*", "**"):
        a = posixpath.dirname(a)
    return "whole" if _is_root_or_above(a, root) else None


def _lead_safe(tok):
    """A dynamic word whose first character is literal and not - + : cannot become a flag or a
    delete/force refspec."""
    return bool(tok) and tok[0] not in (U, Q, PSUB, "-", "+", ":")


# ---- the judge ----
def _peel(argv, stage, upstream, st):
    """Strip assignments, keywords and wrapper programs. Returns [(env, argv)] for the commands
    that really run (find -exec can give several)."""
    env, i, guard = [], 0, 0
    argv = list(argv)
    while i < len(argv) and guard < 24:
        guard += 1
        t = argv[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\+?=", t):
            env.append(t)
            i += 1
            continue
        if (t in KEYWORDS and t != "time") or t in ("then", "do", "else"):
            i += 1
            continue
        b = posixpath.basename(t) if _lit3(t) else t
        rest = argv[i + 1:]
        if b in ("nohup", "builtin", "chronic", "unbuffer", "catchsegv", "setsid", "caffeinate",
                 "time", "nice", "ionice", "stdbuf", "command", "exec", "sudo", "doas", "timeout",
                 "flock", "runuser"):
            j = 0
            vals = {"sudo": "CDghprRtTUu", "doas": "uC", "nice": "n", "ionice": "cnp", "stdbuf": "ioe",
                    "time": "fo", "exec": "a", "timeout": "sk", "flock": "wEc", "caffeinate": "tw",
                    "runuser": "ugGs", "setsid": ""}.get(b, "")
            while j < len(rest) and rest[j].startswith("-") and rest[j] != "-":
                a = rest[j]
                if a == "--":
                    j += 1
                    break
                if b == "command" and a in ("-v", "-V"):
                    return []
                if b == "flock" and a in ("-c", "--command") and j + 1 < len(rest):
                    st.run(rest[j + 1])
                    return []
                if b == "runuser" and a in ("-c", "--command") and j + 1 < len(rest):
                    st.run(rest[j + 1])
                    return []
                if b == "nice" and re.match(r"^-\d+$", a):
                    j += 1
                    continue
                if a.startswith("--"):
                    j += 1 if "=" in a or a in ("--preserve-status", "--foreground", "--verbose",
                                                "--login", "--preserve-env", "--non-interactive") \
                        else (2 if b in ("sudo", "timeout", "nice", "stdbuf", "runuser") else 1)
                    continue
                last = a[-1]
                j += 2 if (last in vals and len(a) == 2) else 1
            rest = rest[j:]
            if b == "timeout" and rest and re.match(r"^[0-9.]+[smhd]?$", rest[0]):
                rest = rest[1:]
            if b == "flock" and rest:
                if len(rest) >= 3 and rest[1] in ("-c", "--command"):
                    st.run(rest[2])
                    return []
                rest = rest[1:]
            argv = rest
            i = 0
            continue
        if b == "busybox" and rest:
            argv = rest
            i = 0
            continue
        if b in ("ssh", "docker", "podman", "kubectl", "oc") and rest:
            j = 0
            if b == "ssh":
                sv = set("BbcDEeFIiJLlmOoPpQRSWw")
                while j < len(rest) and rest[j].startswith("-"):
                    a = rest[j]
                    j += 2 if (len(a) == 2 and a[1] in sv) else 1
                cmd = rest[j + 1:]
                if cmd:
                    st.run(" ".join(cmd))
                return []
            if rest[0] not in ("exec", "run"):
                return [(env, argv[i:])]
            j = 1
            dv = {"-u", "--user", "-w", "--workdir", "-e", "--env", "-v", "--volume", "--name", "-p",
                  "--publish", "--mount", "--entrypoint", "--network", "-l", "--label", "-c", "--container",
                  "-n", "--namespace", "--env-file", "--platform", "-h", "--hostname"}
            while j < len(rest) and rest[j].startswith("-") and rest[j] != "--":
                j += 2 if rest[j] in dv else 1
            if j < len(rest) and rest[j] == "--":
                j += 1
            j += 1                              # the container, pod or image
            if j < len(rest) and rest[j] == "--":
                j += 1
            if rest[j:]:
                argv = rest[j:]
                i = 0
                continue
            return []
        if b == "env":
            j = 0
            while j < len(rest):
                a = rest[j]
                if a == "--":
                    j += 1
                    break
                if a in ("-u", "-C", "--unset", "--chdir", "-P"):
                    j += 2
                    continue
                if a in ("-S", "--split-string") or a.startswith("--split-string=") or \
                        (a.startswith("-S") and len(a) > 2):
                    s = a.split("=", 1)[1] if "=" in a else (a[2:] if a.startswith("-S") and len(a) > 2
                                                              else (rest[j + 1] if j + 1 < len(rest) else ""))
                    nxt = j + (1 if ("=" in a or (a.startswith("-S") and len(a) > 2)) else 2)
                    rest = rest[:j] + (_tokens(s) or []) + rest[nxt:]
                    continue
                if a.startswith("-") and len(a) > 1:
                    j += 1
                    continue
                break
            argv = rest[j:]
            i = 0
            continue
        if b in ("xargs", "parallel"):
            j, repl, delim = 0, None, None
            xv = {"-a", "-d", "-E", "-I", "-L", "-n", "-P", "-s", "-j", "-S", "--arg-file", "--delimiter",
                  "--eof", "--replace", "--max-lines", "--max-args", "--max-procs", "--max-chars",
                  "--process-slot-var", "--jobs", "--colsep"}
            while j < len(rest) and rest[j].startswith("-"):
                a = rest[j]
                if a == "--":
                    j += 1
                    break
                if a in ("-0", "--null"):
                    delim = "\0"
                elif a in ("-d", "--delimiter") and j + 1 < len(rest):
                    delim = _unescape(rest[j + 1])
                elif a.startswith("--delimiter="):
                    delim = _unescape(a.split("=", 1)[1])
                elif a in ("-L", "--max-lines") or a.startswith("-l"):
                    delim = delim or "\n"
                if a == "-I" or a == "--replace":
                    delim = delim or "\n"
                    repl = rest[j + 1] if j + 1 < len(rest) else "{}"
                elif a.startswith("-I") and len(a) > 2:
                    delim = delim or "\n"
                    repl = a[2:]
                elif a.startswith("-i") or a.startswith("--replace="):
                    repl = a.split("=", 1)[1] if "=" in a else (a[2:] or "{}")
                j += 2 if a in xv else 1
            inner = rest[j:] or ["echo"]
            words = None
            if b == "parallel" and ":::" in inner:
                k = inner.index(":::")
                inner, words = inner[:k], [w for w in inner[k + 1:] if w not in (":::", "::::")]
            elif stage["pipe_in"] and upstream:
                lit = _eval_stages(upstream)
                if lit is not None:     # xargs splits on blanks unless -0, -d, -I or -L says otherwise
                    words = lit.split() if delim is None else [w for w in lit.rstrip("\n").split(delim) if w]
            if words is None:
                words = [U]
            if b == "parallel" and repl is None and any("{}" in a for a in inner):
                repl = "{}"
            if repl:
                inner = [a.replace(repl, " ".join(words)) for a in inner]
            else:
                inner = inner + words
            argv = inner
            i = 0
            continue
        if b in ("find", "fd", "fdfind"):
            outs = []
            starts = []
            for a in rest:
                if a.startswith("-") or a in ("(", "!", ")"):
                    break
                starts.append(a)
            stub = (starts[0].rstrip("/") + "/" + U) if (b == "find" and len(starts) == 1
                                                        and starts[0] not in (".", "./")) else U
            j = 0
            while j < len(rest):
                a = rest[j]
                if (b == "find" and a in ("-exec", "-execdir", "-ok", "-okdir")) or \
                        (b != "find" and a in ("-x", "--exec", "-X", "--exec-batch")):
                    k = j + 1
                    while k < len(rest) and rest[k] not in (";", "+", "\\;"):
                        k += 1
                    cmd = [x.replace("{}", stub) if b == "find" else re.sub(r"\{[^}]*\}", U, x)
                           for x in rest[j + 1:k]]
                    if b != "find" and not any(U in x for x in cmd):
                        cmd.append(U)
                    if cmd:
                        outs.extend(_peel(cmd, {"pipe_in": False}, [], st))
                    j = k + 1
                    continue
                j += 1
            outs.append((env, argv[i:]))
            return outs
        if b == "watch":
            j, xflag = 0, False
            while j < len(rest) and rest[j].startswith("-"):
                a = rest[j]
                xflag = xflag or a in ("-x", "--exec")
                j += 2 if a in ("-n", "--interval", "-q", "--equexit") else 1
            if xflag:
                argv = rest[j:]
                i = 0
                continue
            if rest[j:]:
                st.run(" ".join(rest[j:]))
            return []
        if b in ("su", "script"):
            for j, a in enumerate(rest):
                if a in ("-c", "--command") and j + 1 < len(rest):
                    st.run(rest[j + 1])
                    return []
                if a.startswith("--command="):
                    st.run(a.split("=", 1)[1])
                    return []
            if b == "script":
                pos = [a for a in rest if not a.startswith("-")]
                if len(pos) >= 2:
                    argv = pos[1:]
                    i = 0
                    continue
            return [(env, argv[i:])]
        if b == "trap":
            pos = [a for a in rest if a != "--" and not a.startswith("-")]
            if len(pos) >= 2 and pos[0] not in ("-", ""):
                st.run(pos[0])
            return []
        break
    return [(env, argv[i:])]


def _stdin_code(stage, upstream, st):
    """The text a command reads on stdin: (text, known) or (None, reason-it-is-unknown) or
    (None, None) when nothing is fed."""
    if stage.get("here") is not None:
        h = stage["here"]
        return (h, True) if _lit3(h) else (None, "a here-string the guard cannot resolve")
    if stage.get("pipe_in") and upstream:
        lit = _eval_stages(upstream)
        if lit is not None and _lit3(lit):
            return lit, True
        return None, "a pipe from a program whose output the guard cannot compute"
    for op, tgt in stage.get("redirs", []):
        if op == "<" and PSUB in tgt:
            return _psub_out(tgt, st)
    return None, None


def _psub_out(tok, st):
    m = re.search(PSUB + r"(\d+)" + PSUB, tok)
    if not m or int(m.group(1)) >= len(st.r.psubs):
        return None, "a process substitution the guard cannot read"
    inner = st.r.psubs[int(m.group(1))]
    lit = _eval_pipeline(inner) if _lit3(inner) else None
    if lit is not None:
        return lit, True
    return None, "a process substitution whose output the guard cannot compute"


_SPAWN = re.compile(r"os\.system|os\.popen|os\.exec|os\.spawn|subprocess|pty\.spawn|commands\.get|"
                    r"\b(?:system|exec)\s*[(\"'\[]|execSync|execFileSync|spawnSync|\bspawn\s*\(|child_process|"
                    r"\bpopen|shell_exec|passthru|proc_open|IO\.popen|Open3|%x|\bqx|do shell script|"
                    r"os\.execute|io\.popen|Runtime\.getRuntime|`")
_OBFUSC = re.compile(r"b64decode|base64|fromhex|unhexlify|codecs|rot13|rot_13|\bchr\s*\(|\[::-1\]|reverse|"
                     r"decode\s*\(|atob|Buffer\.from|\bpack\s*\(|unpack|\beval\s*\(|\bexec\s*\(|getenv|environ|"
                     r"ENV\[|process\.env|sys\.argv|ARGV|\binput\s*\(|STDIN|readline|\.read\s*\(|\bjoin\s*\(|"
                     r"\.format\s*\(|\bf['\"]|%\s*\(|\bsprintf|\.replace\s*\(|translate|maketrans")
_STR = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"|`((?:[^`\\]|\\.)*)`")
_INTERP = re.compile(r"^(?:python[0-9.]*|pypy[0-9.]*|perl[0-9.]*|ruby[0-9.]*|node|nodejs|bun|deno|php[0-9.]*|"
                     r"osascript|lua[0-9.]*|Rscript|awk|gawk|mawk|nawk)$")


def _interp_code(code, st):
    """Inline interpreter code. Literal command strings it would hand to a shell are checked as
    shell text. Code that spawns a process from parts the guard cannot read is asked about."""
    if not code:
        return
    if not _lit3(code):
        if code.strip() in (U, Q) or _SPAWN.search(code):
            st.ask("interpreter code the guard cannot resolve")
        return
    spawn = _SPAWN.search(code)
    if not spawn:
        if re.search(r"\.git/hooks|\.githooks|\.git/config|['\"]\.git['\"/]|\.husky", code):
            st.ask("interpreter code that touches .git or a hooks directory")
        return
    joined = re.sub(r"(['\"])\s*\+\s*(['\"])", "", code)
    strs = [_unescape(next((g for g in grp if g), "")) for grp in _STR.findall(joined)]
    cands = [s for s in strs if re.search(r"\bgit\b|\brm\b|\bchmod\b|\bmv\b", s)]
    flat = re.sub(r"\[\s*|\s*\]|\(\s*|\s*\)", " ", joined)
    run_rx = r"(?:'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")"
    for run in re.finditer(run_rx + r"(?:\s*,\s*" + run_rx + r")+", flat):
        items = [_unescape(next((g for g in grp if g), "")) for grp in _STR.findall(run.group())]
        if items and re.search(r"\bgit\b", items[0]):
            cands.append(" ".join(items))
    for lst in re.findall(r"\[([^\[\]]*)\]", joined):
        items = [x.strip() for x in lst.split(",") if x.strip()]
        if items and any(re.match(r"^['\"]git['\"]$", x) for x in items):
            if all(_STR.fullmatch(x) for x in items):
                cands.append(" ".join(_unescape(next((g for g in _STR.fullmatch(x).groups() if g), ""))
                                      for x in items))
            else:
                st.ask("interpreter code builds a git argument list from values it computes")
    for s in strs:
        if len(s) >= 8 and re.match(r"^[A-Za-z0-9+/=\s]+$", s):
            try:
                d = base64.b64decode(s + "=" * (-len(s) % 4), validate=False).decode("utf-8")
                if d.isprintable() or "\n" in d:
                    cands.append(d)
            except Exception:
                pass
        if len(s) >= 8 and re.match(r"^(?:[0-9a-fA-F]{2})+$", s):
            try:
                cands.append(bytes.fromhex(s).decode("utf-8"))
            except Exception:
                pass
    for c in cands[:MAX_PAYLOADS]:
        st.run(c)
    if _OBFUSC.search(code) or re.search(r"(['\"])[^'\"]*\bgit\b[^'\"]*\1\s*[+%]", joined):
        st.ask("interpreter code builds the command it runs at run time")


def _judge(env, argv, stage, upstream, st):
    """One command that really runs. Returns a block reason, or None (asks go to st.asks)."""
    if not argv:
        return None
    head = argv[0]
    if not _lit3(head):
        tail = head.rsplit("/", 1)[-1] if "/" in head else ""
        if tail and _lit3(tail):
            head = tail
        else:
            st.ask("the command word itself is unknown until run time (it could be git)")
            return None
    b = posixpath.basename(head)
    args = argv[1:]
    if "/" in head and _lit3(head):
        st.script(head, "this runs")
    if b == "git":
        return _git3(env, argv, stage, st, 0)
    if b in SHELLS3:
        k, has_c, script, stdin = 0, False, None, False
        while k < len(args):
            a = args[k]
            if a in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
                k += 2
                continue
            if a == "--":
                k += 1
                break
            if a.startswith("--"):
                k += 1
                continue
            if (a.startswith("-") or a.startswith("+")) and len(a) > 1:
                if a.startswith("-") and "n" in a[1:]:
                    return None
                has_c = has_c or "c" in a[1:]
                stdin = stdin or "s" in a[1:]
                k += 1
                if has_c:
                    break
                continue
            break
        if has_c:
            if k < len(args) and args[k] == "--":
                k += 1
            code = args[k] if k < len(args) else ""
            if not _lit3(code):
                st.ask("a shell runs -c text the guard cannot resolve")
            elif code:
                st.run(code)
            return None
        script = args[k] if k < len(args) and not stdin else None
        if script is not None and script not in ("-", "/dev/stdin", "/dev/fd/0"):
            st.script(script, "a shell runs")
            if PSUB in script:
                txt, why = _psub_out(script, st)
                if txt is not None:
                    st.run(txt)
                else:
                    st.ask("a shell runs " + why)
            return None
        txt, why = _stdin_code(stage, upstream, st)
        if txt is not None:
            st.run(txt)
        elif why:
            st.ask("a shell runs " + why)
        return None
    if b in ("source", "."):
        a0 = args[0] if args else ""
        if a0 in ("/dev/stdin", "-", "/dev/fd/0"):
            txt, why = _stdin_code(stage, upstream, st)
            if txt is not None:
                st.run(txt)
            elif why:
                st.ask("source runs " + why)
        elif PSUB in a0:
            txt, why = _psub_out(a0, st)
            if txt is not None:
                st.run(txt)
            else:
                st.ask("source runs " + why)
        elif a0:
            st.script(a0, "source runs")
        return None
    if b == "eval":
        code = " ".join(args)
        if not _lit3(code):
            st.ask("eval of text the guard cannot resolve")
        elif code:
            st.run(code)
        return None
    if _INTERP.match(b):
        code = None
        if b in ("awk", "gawk", "mawk", "nawk"):
            j = 0
            while j < len(args) and args[j].startswith("-"):
                if args[j] in ("-f", "--file"):
                    return None
                j += 2 if args[j] in ("-F", "-v") else 1
            code = args[j] if j < len(args) else None
        else:
            for j, a in enumerate(args):
                if re.match(r"^-[A-Za-z]*[ceEr]$", a) or a in ("--eval", "--print", "-p"):
                    code = (code or "") + "\n" + (args[j + 1] if j + 1 < len(args) else "")
            if code is None and (not args or args[0] == "-" or all(a.startswith("-") for a in args)):
                txt, why = _stdin_code(stage, upstream, st)
                if txt is not None:
                    code = txt
                elif why:
                    st.ask("an interpreter runs " + why)
        _interp_code(code, st)
        return _fs_rules(b, args, stage, st)
    if b in ("pre-commit", "prek", "husky", "lefthook") and "uninstall" in args:
        return "hook_bypass_guard: " + b + " uninstall removes the git hooks" + BYPASS_TAIL
    if b in ("at", "batch"):
        txt, why = _stdin_code(stage, upstream, st)
        if txt is not None:
            st.run(txt)
        elif why:
            st.ask(b + " schedules " + why)
        return None
    if b in ("cd", "pushd"):
        pos = [a for a in args if not a.startswith("-")]
        st.cwd = _abs(pos[0], st.cwd) if pos and pos[0] != "-" else None
        return None
    if b == "popd":
        st.cwd = None
        return None
    return _fs_rules(b, args, stage, st)


def _redir_rules(b, args, stage, st):
    """Redirections in one stage that overwrite a hook or write .git/config."""
    cwd = st.cwd
    for op, tgt in stage.get("redirs", []):
        c = _pclass(tgt, cwd)
        if op in (">", ">|", "&>") and c == "hooks":
            content = " ".join(args) if b in ("echo", "printf") else None
            if not stage["argv"] or b in (":", "true") or (b == "cat" and args == ["/dev/null"]) or \
                    (content is not None and re.sub(r"#![^\s\\]*|\\n|\s", "", content) in ("", "exit0", "exit", "true", ":")):
                return ("hook_bypass_guard: overwrites a git hook with nothing that runs (" + tgt + ")"
                        + BYPASS_TAIL)
            st.ask("a write over a git hook file (" + tgt + ")")
        elif c == "hooks" and op in (">>", "&>>"):
            st.ask("a write into a git hook file (" + tgt + ")")
        elif op in (">", ">>", ">|", "&>", "&>>") and _GITCONFIG_RE.search(_abs(tgt, cwd) or tgt):
            if re.search(r"hookspath", " ".join(stage["argv"]), re.I):
                return "hook_bypass_guard: writes core.hooksPath into .git/config directly" + BYPASS_TAIL
            st.ask("a direct write to .git/config")
    return None


def _fs_rules(b, args, stage, st):
    """Non-git routes to the same effects: hooks removed or overwritten, .git deleted."""
    cwd = st.cwd
    pos = []
    endopts = False
    for a in args:
        if a == "--" and not endopts:
            endopts = True
        elif endopts or not a.startswith("-") or a == "-":
            pos.append(a)
    if b in ("rm", "unlink", "shred", "srm", "trash", "rmdir"):
        rec = any(re.match(r"^-[A-Za-z]*[rR]", a) or a == "--recursive" for a in args if a.startswith("-"))
        for p in pos:
            c = _pclass(p, cwd)
            if c == "hooks":
                return "hook_bypass_guard: deletes a git hook (" + p + ")" + BYPASS_TAIL
            if c == "gitdir":
                return "data_loss_guard: deletes the repository's own history (" + p + ")" + LOSS_TAIL
            if c == "git":
                st.ask("a delete inside .git (" + p + ")")
            a = _abs(p, cwd)
            while a and posixpath.basename(a) in ("*", ".*"):
                a = posixpath.dirname(a)
            if a and rec and _is_root_or_above(a, st.root):
                st.ask("a recursive delete of the whole worktree (" + p + ")")
            elif rec and p in (".", "./", "*", "./*") and cwd is None:
                st.ask("a recursive delete of the current directory (" + p + ")")
        return None
    if b == "mv":
        tdir = next((args[j + 1] for j, a in enumerate(args) if a in ("-t", "--target-directory")
                     and j + 1 < len(args)), None)
        srcs, dest = (pos, tdir) if tdir else (pos[:-1], pos[-1] if pos else None)
        for p in srcs:
            c = _pclass(p, cwd)
            if c == "hooks":
                return "hook_bypass_guard: moves a git hook out of the way (" + p + ")" + BYPASS_TAIL
            if c == "gitdir":
                return "data_loss_guard: moves the repository's own history away (" + p + ")" + LOSS_TAIL
        if dest and _pclass(dest, cwd) == "hooks":
            st.ask("a file moved over a git hook (" + dest + ")")
        return None
    if b == "chmod":
        mode, targets = None, []
        for a in args:
            if mode is None and (re.match(r"^[ugoa]*[-+=][rwxXst]*(,[ugoa]*[-+=][rwxXst]*)*$", a)
                                 or re.match(r"^[0-7]{3,4}$", a)):
                mode = a
            elif not a.startswith("-") or mode is not None:
                targets.append(a)
        if any(_pclass(t, cwd) == "hooks" for t in targets):
            if mode and re.match(r"^[0-7]{3,4}$", mode):
                if not int(mode, 8) & 0o100:
                    return "hook_bypass_guard: chmod " + mode + " turns a git hook off" + BYPASS_TAIL
                return None
            if mode and any(re.match(r"^([ugoa]*)-[rwXst]*x", c) and (re.match(r"^([ugoa]*)", c).group(1) in ("", "a")
                                                                    or "u" in re.match(r"^([ugoa]*)", c).group(1))
                            for c in mode.split(",")):
                return "hook_bypass_guard: chmod " + mode + " turns a git hook off" + BYPASS_TAIL
            if mode and any(re.match(r"^([ugoa]*)=", c) and "x" not in c for c in mode.split(",")):
                return "hook_bypass_guard: chmod " + mode + " turns a git hook off" + BYPASS_TAIL
            if mode and "+" in mode:
                return None
            st.ask("a mode change on a git hook")
        return None
    if b in ("cp", "install", "ln", "rsync", "tee", "truncate", "dd", "sed", "perl", "touch"):
        if b == "dd":
            outs = [a[3:] for a in args if a.startswith("of=")]
            if any(_pclass(o, cwd) == "hooks" for o in outs):
                if "if=/dev/null" in args:
                    return "hook_bypass_guard: dd empties a git hook" + BYPASS_TAIL
                st.ask("dd writes a git hook")
            return None
        if b == "truncate":
            if any(_pclass(p, cwd) == "hooks" for p in pos):
                return "hook_bypass_guard: truncate empties a git hook" + BYPASS_TAIL
            return None
        if b in ("sed", "perl") and not any(a.startswith("-i") or a.startswith("--in-place") or
                                            (b == "perl" and re.match(r"^-[a-z]*i", a)) for a in args):
            return None
        if b == "touch":
            return None
        tdir = next((args[j + 1] for j, a in enumerate(args) if a in ("-t", "--target-directory")
                     and j + 1 < len(args)), None)
        if b in ("tee", "sed", "perl"):
            dests = pos
        else:
            dests = [tdir] if tdir else pos[-1:]
        for d in dests:
            c = _pclass(d, cwd)
            if c == "hooks":
                if b in ("cp", "install", "ln") and "/dev/null" in pos[:-1]:
                    return "hook_bypass_guard: replaces a git hook with /dev/null" + BYPASS_TAIL
                st.ask("a write over a git hook (" + d + ")")
            elif _GITCONFIG_RE.search(_abs(d, cwd) or d):
                if re.search(r"hookspath", " ".join(args), re.I):
                    return "hook_bypass_guard: writes core.hooksPath into .git/config directly" + BYPASS_TAIL
                st.ask("a direct write to .git/config")
        return None
    if b == "find":
        starts = []
        for a in args:
            if a.startswith("-") or a in ("(", "!", ")"):
                break
            starts.append(a)
        if "-delete" in args:
            for s in starts:
                c = _pclass(s, cwd)
                if c == "hooks":
                    return "hook_bypass_guard: find -delete removes git hooks" + BYPASS_TAIL
                if c == "gitdir":
                    return "data_loss_guard: find -delete removes the repository's history" + LOSS_TAIL
        return None
    if b not in READONLY and not _INTERP.match(b):
        for a in args:
            v = a.split("=", 1)[1] if (a.startswith("-") and "=" in a) or a.startswith("of=") else a
            if _pclass(v, cwd) == "hooks":
                st.ask(b + " acts on a git hook (" + v + ")")
                break
    return None


def _git3(env, argv, stage, st, depth):
    """One git invocation, after every wrapper is stripped. Block reasons for the new routes; asks
    for parts the guard cannot resolve."""
    i, gopts = 1, []
    while i < len(argv):
        a = argv[i]
        if U in a:
            st.ask("git has a word before its subcommand that the guard cannot resolve")
            return None
        if not a.startswith("-") and Q not in a:
            break
        if Q in a and not a.startswith("-"):
            st.ask("the git subcommand is unknown until run time")
            return None
        if a in GIT_GLOBAL_VAL or a == "--super-prefix":
            v = argv[i + 1] if i + 1 < len(argv) else ""
            if U in v:
                st.ask("a git global option value the guard cannot resolve (" + a + ")")
                return None
            gopts.append((a, v))
            i += 2
        else:
            gopts.append((a, None))
            i += 1
    if i >= len(argv):
        return None
    sub, args = argv[i], argv[i + 1:]
    for k, a in enumerate(args):
        if a.startswith("<<"):
            args = args[:k]
            break
    cwd = st.cwd
    cfg = {}
    for flag, val in gopts:
        if flag == "-C" and val is not None and cwd is not None:
            cwd = _abs(val, cwd) if not _dyn(val) else None
        v = val if flag == "-c" else (flag[2:] if flag.startswith("-c") and not flag.startswith("--") else None)
        if v is not None:
            if _dyn(v):
                if sub in RISKY:
                    st.ask("a git -c setting the guard cannot resolve")
                continue
            key, _, setting = v.partition("=")
            cfg[key.strip().lower()] = setting
    # git aliases: -c alias.X=V on this call, or `git config alias.X V` earlier in this string
    aliases = dict(st.git_aliases)
    aliases.update({k[6:]: v for k, v in cfg.items() if k.startswith("alias.")})
    if sub not in KNOWN_GIT and sub in aliases and depth < 3:
        val = aliases[sub]
        gtoks = []
        for flag, v in gopts:
            gtoks += [flag] + ([v] if v is not None else [])
        if val.startswith("!"):
            st.run(val[1:] + " " + " ".join(shlex.quote(a) for a in args))
            return None
        return _git3(env, ["git"] + gtoks + (_tokens(val) or []) + args, stage, st, depth + 1)
    if sub not in KNOWN_GIT:
        st.ask("`git " + sub + "` is not a git command the guard knows; a git alias can stand for anything")
        return None
    for k, v in cfg.items():                # a setting whose value git runs as a shell command
        if _CMD_KEY.match(k) and not (k.startswith("credential") and not v.strip().startswith("!")):
            code = v.strip().lstrip("!")
            if _lit3(code):
                st.run(code)
            else:
                st.ask("a git setting that runs a command the guard cannot resolve (" + k + ")")
    for e in env:
        k, _, v = e.partition("=")
        if k in CMD_ENV:
            if _lit3(v):
                st.run(v)
            else:
                st.ask("an environment variable git runs as a command, with a value the guard cannot resolve (" + k + ")")
    canon_sub = "add" if sub == "stage" else sub
    gtoks = []
    for flag, v in gopts:
        gtoks += [flag] + ([v] if v is not None else [])
    st.canon.append(" ".join(shlex.quote(t) for t in env + ["git"] + gtoks + [canon_sub] + args))
    # environment: hook runners switched off, config injected from outside
    envd = {}
    for e in env:
        k, _, v = e.partition("=")
        envd[k.rstrip("+")] = v
    for k, v in st.r.assigned.items():
        envd.setdefault(k, v)
    if sub in HOOKED3:
        for k, off in (("HUSKY", ("0", "false")), ("HUSKY_SKIP_HOOKS", None), ("LEFTHOOK", ("0", "false")),
                       ("SKIP", None), ("PRE_COMMIT_SKIP", None)):
            if k in envd:
                v = envd[k]
                if _dyn(v):
                    st.ask("a hook-runner switch the guard cannot resolve (" + k + ")")
                elif (off is None and v not in ("", "0", "false")) or (off is not None and v in off):
                    return ("hook_bypass_guard: " + k + "=" + v + " switches the hook runner off"
                            + BYPASS_TAIL)
        gcp = envd.get("GIT_CONFIG_PARAMETERS")
        if gcp is not None:
            if re.search(r"hookspath", gcp, re.I):
                return "hook_bypass_guard: GIT_CONFIG_PARAMETERS sets core.hooksPath" + BYPASS_TAIL
            st.ask("GIT_CONFIG_PARAMETERS injects config the guard does not read")
        if any(k in envd for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG")):
            st.ask("a config file swapped in through the environment could set core.hooksPath")
        if any(k == "include.path" or k.startswith("includeif.") for k in cfg):
            st.ask("-c include.path loads a config file the guard does not read")
    if sub == "push":
        for k, v in cfg.items():
            if k.startswith("remote.") and k.endswith(".push") and v.strip().startswith("+"):
                return "data_loss_guard: -c remote.*.push=+... makes this push a force push" + LOSS_TAIL
            if k.startswith("remote.") and k.endswith(".mirror") and v.strip().lower() in ("true", "1", "yes", "on", ""):
                return "data_loss_guard: -c remote.*.mirror makes this push overwrite and delete remote refs" + LOSS_TAIL
    if sub == "clean" and cfg.get("clean.requireforce", "").strip().lower() in ("false", "0", "no", "off") \
            and not any(a in ("-n", "--dry-run", "-i", "--interactive") or re.match(r"^-[A-Za-z]*n", a) for a in args):
        return "data_loss_guard: git clean with clean.requireForce=false deletes untracked files" + LOSS_TAIL
    why = _git_rules3(sub, args, cwd, st)
    if why:
        return why
    _git_dyn3(sub, args, st)
    return None


def _opts_and_pos(sub, args):
    """[(token, kind)] where kind is opt, val (the value of the option before it), pos or path
    (after --)."""
    vals = VAL3.get(sub, set())
    out, k, endopts = [], 0, False
    while k < len(args):
        a = args[k]
        if endopts:
            out.append((a, "path"))
        elif a == "--":
            endopts = True
            out.append((a, "opt"))
        elif a.startswith("-") and len(a) > 1 and not _dyn(a[:2]):
            out.append((a, "opt"))
            if a in vals and k + 1 < len(args):
                out.append((args[k + 1], "val"))
                k += 1
            elif not a.startswith("--"):
                for j, ch in enumerate(a[1:]):
                    if "-" + ch in vals:
                        if j + 2 == len(a) and k + 1 < len(args):
                            out.append((args[k + 1], "val"))
                            k += 1
                        break
        else:
            out.append((a, "pos"))
        k += 1
    return out


def _git_rules3(sub, args, cwd, st):
    """Block reasons for the routes version 3 adds."""
    root = st.root
    tp = _opts_and_pos(sub, args)
    opts = [t for t, k in tp if k == "opt"]
    pos = [t for t, k in tp if k in ("pos", "path")]
    shorts = "".join(o[1:] for o in opts if not o.startswith("--"))
    longs = [o.split("=", 1)[0] for o in opts if o.startswith("--")]

    def has_long(full, minlen):
        return any(len(n) >= minlen and full.startswith(n) for n in longs)

    def whole(ps):
        kinds = [_pathspec_whole(p, cwd, root) for p in ps if _lit3(p)]
        if "whole" in kinds:
            return True
        return bool(kinds) and all(k == "exclude" for k in kinds) and len(kinds) == len(ps)

    if sub in ("add", "stage"):
        if whole(pos):
            return SAY + "git " + sub + " " + " ".join(pos) + " (the pathspec resolves to the whole tree)"
        if any(o.startswith("--pathspec-from-file") for o in opts):
            st.ask("git add --pathspec-from-file reads its paths from a file at run time")
    elif sub == "commit":
        k = 0
        while k < len(args):
            a = args[k]
            if a == "--":
                break
            if a.startswith("--"):
                if a in VAL3["commit"]:
                    k += 2
                    continue
                if a == "--all":
                    return SAY + "git commit --all (stages every tracked modification, then commits, in one step)."
            elif a.startswith("-") and len(a) > 1:
                for j, ch in enumerate(a[1:]):
                    if ch in "mFCct":
                        if j + 2 == len(a):
                            k += 1
                        break
                    if ch in "Su":
                        break
                    if ch == "a":
                        return SAY + "git commit " + a + " (stages every tracked modification, then commits, in one step)."
                    if ch == "n":
                        return "hook_bypass_guard: git commit -n (= --no-verify)" + BYPASS_TAIL
            k += 1
        if whole(pos):
            return SAY + "git commit " + " ".join(pos) + " (commits every tracked change under the whole tree)"
        if any(o.startswith("--pathspec-from-file") for o in opts):
            st.ask("git commit --pathspec-from-file reads its paths from a file at run time")
    elif sub == "checkout":
        if "f" in shorts.split("b")[0].split("B")[0] or has_long("--force", 4):
            return "data_loss_guard: git checkout --force throws away local changes" + LOSS_TAIL
        if "B" in shorts:
            return "data_loss_guard: git checkout -B resets an existing branch and can orphan its commits" + LOSS_TAIL
        if whole(pos):
            return "data_loss_guard: git checkout over the whole tree discards every uncommitted change" + LOSS_TAIL
        if any(_pclass(p, cwd) == "hooks" for p in pos if _lit3(p)):
            st.ask("git checkout rewrites hook files from another version")
    elif sub == "restore":
        if any(_pclass(p, cwd) == "hooks" for p in pos if _lit3(p)):
            st.ask("git restore rewrites hook files from another version")
        staged = "S" in shorts or has_long("--staged", 4)
        worktree = "W" in shorts or has_long("--worktree", 3)
        if whole(pos) and (worktree or not staged):
            return "data_loss_guard: git restore over the whole tree discards every uncommitted change" + LOSS_TAIL
    elif sub == "switch":
        if "f" in shorts or "C" in shorts.split("c")[0] or has_long("--discard-changes", 5) or \
                any(n.startswith("--force") or (len(n) >= 6 and "--force".startswith(n)) for n in longs):
            return "data_loss_guard: git switch that discards local changes or resets a branch" + LOSS_TAIL
    elif sub == "branch":
        if "f" in shorts or has_long("--force", 6):
            return "data_loss_guard: git branch --force moves an existing branch and can orphan its commits" + LOSS_TAIL
    elif sub == "stash":
        p = [t for t in pos]
        if p and p[0] in ("drop", "clear"):
            return "data_loss_guard: git stash " + p[0] + " throws stashed work away" + LOSS_TAIL
    elif sub == "reflog":
        if pos and pos[0] in ("expire", "delete"):
            return "data_loss_guard: git reflog " + pos[0] + " removes the record that recovers lost commits" + LOSS_TAIL
    elif sub == "push":
        if "d" in shorts or has_long("--delete", 5):
            return "data_loss_guard: git push --delete removes a remote branch" + LOSS_TAIL
        if has_long("--mirror", 4):
            return "data_loss_guard: git push --mirror overwrites and deletes remote refs" + LOSS_TAIL
        if has_long("--prune", 5):
            return "data_loss_guard: git push --prune deletes remote branches" + LOSS_TAIL
        for p in pos[1:]:
            if _lit3(p) and re.match(r"^\+?:[^:]+$", p):
                return "data_loss_guard: git push " + p + " deletes a remote ref" + LOSS_TAIL
    elif sub == "worktree":
        if pos and pos[0] == "remove" and ("f" in shorts or has_long("--force", 4)):
            return "data_loss_guard: git worktree remove --force deletes a worktree with its changes" + LOSS_TAIL
    elif sub == "rm":
        if "n" in shorts or has_long("--dry-run", 4):
            return None
        for p in pos:
            if _pclass(p, cwd) == "hooks":
                return "hook_bypass_guard: git rm removes a git hook (" + p + ")" + BYPASS_TAIL
        if whole(pos) and not has_long("--cached", 4):
            return "data_loss_guard: git rm over the whole tree deletes every tracked file" + LOSS_TAIL
        if whole(pos):
            return SAY + "git rm --cached " + " ".join(pos) + " (stages the removal of the whole tree)"
        if any(o.startswith("--pathspec-from-file") for o in opts):
            st.ask("git rm --pathspec-from-file reads its paths from a file at run time")
    elif sub == "mv":
        for p in pos[:-1]:
            if _pclass(p, cwd) == "hooks":
                return "hook_bypass_guard: git mv moves a git hook away (" + p + ")" + BYPASS_TAIL
    elif sub == "config":
        return _config3(args, st)
    elif sub == "symbolic-ref":
        if "d" in shorts or has_long("--delete", 4):
            return "data_loss_guard: git symbolic-ref --delete removes a ref" + LOSS_TAIL
        if len(pos) >= 2:
            st.ask("git symbolic-ref rewrites where a ref points")
    elif sub == "read-tree":
        if "u" in shorts:
            if has_long("--reset", 4):
                return "data_loss_guard: git read-tree --reset -u overwrites the worktree" + LOSS_TAIL
            st.ask("git read-tree -u rewrites worktree files")
    elif sub == "checkout-index":
        if ("f" in shorts or has_long("--force", 4)) and ("a" in shorts or has_long("--all", 3)):
            return "data_loss_guard: git checkout-index --force --all overwrites every worktree file" + LOSS_TAIL
    elif sub == "update-index":
        if any(o.startswith("--chmod=-x") for o in opts) and any(_pclass(p, cwd) == "hooks" for p in pos):
            return "hook_bypass_guard: git update-index --chmod=-x turns a hook off for everyone" + BYPASS_TAIL
        if "g" in shorts or has_long("--again", 4):
            st.ask("git update-index --again restages paths the guard cannot list")
    elif sub == "submodule":
        if pos and pos[0] == "foreach":
            rest = [a for a in args[args.index("foreach") + 1:]]
            while rest and rest[0] in ("--recursive", "-q", "--quiet"):
                rest = rest[1:]
            code = " ".join(rest)
            if not _lit3(code):
                st.ask("git submodule foreach runs text the guard cannot resolve")
            elif code:
                st.run(code)
    elif sub == "rebase":
        for j, a in enumerate(args):
            code = None
            if a in ("-x", "--exec") and j + 1 < len(args):
                code = args[j + 1]
            elif a.startswith("--exec="):
                code = a.split("=", 1)[1]
            elif a.startswith("-x") and len(a) > 2:
                code = a[2:]
            if code is not None:
                if _lit3(code):
                    st.run(code)
                else:
                    st.ask("git rebase --exec runs text the guard cannot resolve")
    elif sub == "bisect":
        if pos and pos[0] == "run":
            code = " ".join(shlex.quote(a) for a in args[args.index("run") + 1:])
            if _lit3(code):
                st.run(code)
            else:
                st.ask("git bisect run runs a command the guard cannot resolve")
    elif sub == "fetch":
        force = "f" in shorts or has_long("--force", 4)
        for p in pos[1:]:
            if _lit3(p) and ":" in p:
                dst = p.split(":", 1)[1]
                if dst and (p.startswith("+") or force) and not dst.startswith("refs/remotes/") \
                        and not dst.startswith("refs/tags/"):
                    return ("data_loss_guard: git fetch " + p + " force-updates a local branch and can "
                            "orphan its commits" + LOSS_TAIL)
    elif sub == "pull":
        if any(len(n) >= 8 and "--no-verify".startswith(n) for n in longs):
            return "hook_bypass_guard: --no-verify on git pull" + BYPASS_TAIL
    elif sub in REWRITERS:
        st.ask("git " + sub + " rewrites history or refs; the guard cannot tell what it keeps")
    return None


def _config3(args, st):
    readonly = any(a.startswith("--get") or a in ("--list", "-l", "--show-origin", "--show-scope", "--edit", "-e")
                   for a in args)
    k, pos, unset, rmsec = 0, [], False, False
    while k < len(args):
        a = args[k]
        if a in ("--file", "-f", "--blob", "--type", "--default", "--comment", "--value", "-t"):
            k += 2
            continue
        if a.startswith("--unset"):
            unset = True
        elif a in ("--remove-section", "--rename-section"):
            rmsec = True
        elif not a.startswith("-") or _dyn(a):
            pos.append(a)
        k += 1
    if pos and pos[0] in ("get", "list"):
        return None
    if pos and pos[0] in ("set", "unset", "remove-section", "rename-section"):
        unset = unset or pos[0] == "unset"
        rmsec = rmsec or pos[0] in ("remove-section", "rename-section")
        pos = pos[1:]
    if readonly or not pos:
        return None
    key = pos[0]
    if _dyn(key):
        st.ask("git config with a key the guard cannot resolve (it could be core.hooksPath)")
        return None
    lk = key.lower()
    val = pos[1] if len(pos) > 1 else None
    if rmsec and lk == "core":
        return "hook_bypass_guard: removing the [core] section drops core.hooksPath" + BYPASS_TAIL
    if lk == "core.hookspath":
        if unset:
            return "hook_bypass_guard: git config unset core.hooksPath disarms the hooks" + BYPASS_TAIL
        if val is not None and _dyn(val):
            st.ask("git config core.hooksPath set to a value the guard cannot resolve")
        elif val is not None and val != ".githooks":
            return "hook_bypass_guard: git config core.hooksPath " + (val or '""') + " disarms the hooks" + BYPASS_TAIL
        return None
    if val is None or unset:
        return None
    if _dyn(val):
        if lk.startswith("alias.") or lk in ("clean.requireforce",) or lk.startswith("include") or _CMD_KEY.match(lk) or \
                (lk.startswith("remote.") and (lk.endswith(".push") or lk.endswith(".mirror"))):
            st.ask("git config " + key + " set to a value the guard cannot resolve")
        return None
    if _CMD_KEY.match(lk) and not (lk.startswith("credential") and not val.strip().startswith("!")):
        st.run(val.strip().lstrip("!"))
    if lk == "clean.requireforce" and val.lower() in ("false", "0", "no", "off"):
        return "data_loss_guard: clean.requireForce=false lets git clean delete files without -f" + LOSS_TAIL
    if lk.startswith("remote.") and lk.endswith(".push") and val.startswith("+"):
        return "data_loss_guard: a +refspec in remote.*.push makes every push a force push" + LOSS_TAIL
    if lk.startswith("remote.") and lk.endswith(".mirror") and val.lower() in ("true", "1", "yes", "on"):
        return "data_loss_guard: remote.*.mirror makes every push overwrite and delete remote refs" + LOSS_TAIL
    if lk.startswith("alias."):
        st.git_aliases[key[6:]] = val
    if lk == "include.path" or lk.startswith("includeif."):
        st.ask("git config include.path loads a config file the guard does not read")
    return None


def _git_dyn3(sub, args, st):
    """Ask when a part the guard cannot resolve could turn this git call into a violation."""
    if sub not in RISKY or sub == "config":
        return
    tp = _opts_and_pos(sub, args)
    if sub == "stash":
        p = [t for t, k in tp if k in ("pos",)]
        if p and _dyn(p[0]):
            st.ask("the git stash action is unknown until run time")
        elif any(U in t for t, k in tp if k == "opt"):
            st.ask("git stash has a flag the guard cannot resolve")
        return
    if sub in ("submodule", "bisect"):
        return
    opts = [t for t, k in tp if k == "opt"]
    if sub in ("add", "rm", "clean", "push", "commit") and any(
            o in ("-n", "--dry-run") or (sub in ("clean", "rm", "add") and re.match(r"^-[A-Za-z]*n[A-Za-z]*$", o)
                                         and sub != "commit") for o in opts):
        return                      # a dry run changes nothing, whatever the unresolved part is
    for t, kind in tp:
        if not _dyn(t) and PSUB not in t:
            continue
        if PSUB in t and _lit3(t.replace(PSUB, "")):
            continue
        if kind == "val":
            if U in t:
                st.ask("git " + sub + " has an option value the guard cannot resolve, and unquoted it can split into flags")
                return
            continue
        if kind == "path":
            if sub in PATH_SENS:
                st.ask("git " + sub + " has a pathspec the guard cannot resolve (it could be . or the repo root)")
                return
            if sub == "push" and not (Q in t and U not in t and _lead_safe(t)):
                st.ask("git push has a refspec the guard cannot resolve (it could force or delete)")
                return
            continue
        if U in t:
            st.ask("git " + sub + " has an unquoted word the guard cannot resolve; it can split into any flag")
            return
        if sub in PATH_SENS:
            st.ask("git " + sub + " has an argument the guard cannot resolve (a flag or a whole-tree pathspec)")
            return
        if not _lead_safe(t):
            st.ask("git " + sub + " has an argument the guard cannot resolve (it could be a flag that "
                   "makes this a violation)")
            return


def _walk(text, st):
    pls = _parse3(text, st.bodies)
    if pls is None:
        if re.search(r"\bgit\b|\bsh\b|\bbash\b|\beval\b|\bsource\b", text):
            st.ask("quoting the guard cannot parse")
        return None
    for pl in pls:
        for idx, stage in enumerate(pl):
            upstream = pl[:idx] if stage["pipe_in"] else []
            for op, tgt in stage["redirs"]:
                if op in (">", ">|", ">>") and _abs(tgt, st.cwd):
                    plain = dict(stage, out=False, redirs=[])
                    txt = _eval_stages((upstream or []) + [plain]) if (plain["argv"] or plain["here"]) else ""
                    a = _abs(tgt, st.cwd)
                    old = st.files.get(a, "") if op == ">>" else ""
                    st.files[a] = (old + txt) if txt is not None and _lit3(txt) and _lit3(old) else U
            cmds = _peel(stage["argv"], stage, upstream, st)
            for env, argv in cmds:
                why = _judge(env, argv, stage, upstream, st)
                if why:
                    return why
            if stage["redirs"]:
                first = cmds[0][1] if cmds and cmds[0][1] else stage["argv"]
                why = _redir_rules(posixpath.basename(first[0]) if first else "", first[1:] if first else [],
                                   stage, st)
                if why:
                    return why
    return None


def _check3(cmd, root, depth, known=None, pos=None, funcs=None):
    """-> ("block" | "ask" | "allow", reason). Blocks anywhere win over asks anywhere."""
    nohd = _strip_heredocs(cmd)
    if depth > 0:
        why = _guards(nohd, root)              # what version 1 and 2 read, on this payload as written
        if why:
            return "block", why
    bodies = _heredoc_bodies(cmd)
    base = _ifs_pass(_ansi_pass(_join_pass(nohd)))
    r = _R(known, pos, "main", None, funcs)
    views = [(_brace_pass(r.resolve(base)), True, r)]
    for k, vals in r.loops[:4]:
        for vi in range(1, min(len(vals), 8)):
            r2 = _R(known, pos, "main", {k: vi}, funcs)
            views.append((_brace_pass(r2.resolve(base)), True, r2))
    if r.alt:
        r3 = _R(known, pos, "default", None, funcs)
        views.append((_brace_pass(r3.resolve(base)), False, r3))
    asks, payloads = [], []
    for d, body, quoted in bodies:
        if not quoted and ("$" in body or "`" in body):
            hr = _R(known, pos, "main", None, r.funcs)     # an unquoted delimiter: $(...) in the body runs
            hr.expand(body.replace('"', "'"), 2)
            payloads.extend(hr.payloads)
    for text, ask_ok, rr in views:
        why = _guards(text, root, as_written=False)
        if why:
            return "block", why
        st = _St(root, rr, bodies, depth)
        why = _walk(text, st)
        if not why and st.canon:
            why = _guards(" ; ".join(st.canon), root, as_written=False)
        if why:
            return "block", why
        if ask_ok:
            asks.extend(st.asks)
        payloads.extend(rr.payloads + st.payloads)
    seen = set()
    for p, kn, ps in payloads:
        key = (p, tuple(ps) if ps is not None else None)
        if key in seen or not p.strip():
            continue
        seen.add(key)
        if depth + 1 > MAX_DEPTH:
            asks.append(FAIL + "code nested deeper than %d levels" % MAX_DEPTH + ASK_TAIL)
            break
        v, why = _check3(p, root, depth + 1, kn, ps, r.funcs)
        if v == "block":
            return "block", why + (" (found in code this command runs)" if "(found in code" not in why else "")
        if v == "ask":
            asks.append(why)
    if asks:
        return "ask", asks[0]
    return "allow", ""


def _decide3(command):
    """Version 3, unchanged: ("block" | "ask" | "allow", reason). The version 2 check runs first and
    unchanged, so every v2 block stays a block. Then version 3 reads further and fails closed: when
    it cannot resolve a part that could make the command a violation, it returns "ask". An internal
    error in version 3 is also an "ask", with the exception named."""
    command = command or ""
    try:
        why = _check(command, _root(), 0)
        if why:
            return "block", why
    except Exception:
        pass                        # version 2 failed open here; version 3 still reads the command
    try:
        return _check3(command, _root(), 0)
    except Exception as exc:
        return "ask", "fail_closed: guard error %s: %s. A human decides." % (type(exc).__name__, str(exc)[:160])


# =====================================================================================
# VERSION 4: NEVER ASK. Every stop is a deny that carries a redirect the agent can follow.
# Detection is _decide3, unchanged. Each redirect is chosen by the SHAPE of the v3 reason (first
# match wins), and every command in backticks inside a redirect is a safe alternative that this
# guard allows. bench.py checks both: no deny without a specific redirect, and no alternative that
# the guard itself would stop.
# =====================================================================================
REDIRECT_MARK = " DO THIS INSTEAD: "
_V3_TAILS = (" Stop and ask. Name the paths or refs, and let a human run it.",
             " Bypassing them is an act for a human in their own terminal. Stop and ask.",
             " A human decides.")
_VAR_ALT = {"add": "git add path/to/file", "stage": "git add path/to/file",
            "commit": "git commit -m \"message\" -- path/to/file", "push": "git push origin branch-name",
            "reset": "git reset --soft HEAD~1", "branch": "git branch -d branch-name",
            "checkout": "git switch branch-name", "switch": "git switch branch-name",
            "restore": "git restore path/to/file", "merge": "git merge branch-name",
            "rm": "git rm path/to/file", "mv": "git mv old/path new/path", "stash": "git stash list",
            "clean": "git clean -n", "config": "git config user.name \"Name\"",
            "rebase": "git rebase origin/branch-name", "pull": "git pull --rebase origin branch-name"}
# (shape id, regex over the v3 reason, redirect). Order matters: the first match wins.
REDIRECTS = [
    # policy B: never disarm the hooks
    ("B-no-verify-pull", r"^hook_bypass_guard: --no-verify on git pull",
     "Run `git pull origin branch-name` without --no-verify. If a hook fails, read its output, fix what it "
     "names, and run it again."),
    ("B-no-verify", r"^hook_bypass_guard: --no-verify",
     "Run the same command without --no-verify, for example `git commit -m \"message\"` or "
     "`git push origin branch-name`. If a hook fails, read its output, fix what it names, and run it again."),
    ("B-commit-n", r"^hook_bypass_guard: git commit -n",
     "Drop -n, which means --no-verify on commit: `git commit -m \"message\"`. If the hook fails, fix what "
     "it names and commit again."),
    ("B-hookspath-oneshot", r"^hook_bypass_guard: (?:-c core\.hooksPath|--config-env core\.hooksPath)",
     "Drop the core.hooksPath override and run the plain command, for example `git commit -m \"message\"`. "
     "The hooks then run as the repo set them."),
    ("B-config-env", r"^hook_bypass_guard: GIT_CONFIG_",
     "Drop the GIT_CONFIG_* variables. To pass a setting that does not touch hooks, write it literally "
     "with -c: `git -c user.name=\"Name\" commit -m \"message\"`."),
    ("B-hookspath-config", r"^hook_bypass_guard: (?:git config core\.hooksPath|git config unset core\.hooksPath|"
                           r"removing the \[core\] section|writes core\.hooksPath)",
     "Leave core.hooksPath pointing at the repo's hooks: `git config core.hooksPath .githooks`. Check the "
     "value with `git config --get core.hooksPath`."),
    ("B-runner-off", r"^hook_bypass_guard: .*switches the hook runner off",
     "Run the command without HUSKY=0, LEFTHOOK=0, HUSKY_SKIP_HOOKS or SKIP=, for example "
     "`git commit -m \"message\"`. If a hook fails, fix what it names and run it again."),
    ("B-pre-commit-uninstall", r"^hook_bypass_guard: pre-commit uninstall",
     "Keep the hooks installed. Run them by hand with `pre-commit run --all-files` and fix what they report."),
    ("B-plumbing", r"^hook_bypass_guard: git plumbing",
     "Use the commands that run the hooks: `git commit -m \"message\"` to commit, `git push origin "
     "branch-name` to publish, and `git branch new-branch commit-id` to point a new branch at a commit."),
    ("B-hook-file", r"^hook_bypass_guard: .*(?:git hook|hooks? off|hooks? for everyone)",
     "Leave the hook files in place. Read the hook with `cat .git/hooks/pre-commit` to see what it checks, "
     "fix the code it complains about, and run the command again."),
    # policy A: stage by name only
    ("A-rm-cached-all", r"^blanket_stage_guard: .*Form seen: git rm",
     "Untrack files by name: `git rm --cached path/to/file`, or one folder with "
     "`git rm -r --cached path/to/folder`. Add the path to .gitignore so it stays out."),
    ("A-commit-all", r"^blanket_stage_guard: .*Form seen: git commit (?:--all|-[A-Za-z]*a)",
     "Stage the files by name, then commit without -a: `git add path/to/file1 path/to/file2` and then "
     "`git commit -m \"message\"`. Run `git status --short` first to see what changed."),
    ("A-commit-whole", r"^blanket_stage_guard: .*Form seen: git commit",
     "Commit only named paths: `git commit -m \"message\" -- path/to/file`. Run `git status --short` "
     "first to see what changed."),
    ("A-add-exclude", r"^blanket_stage_guard: .*Form seen: git add \S*(?::\(exclude\)|:!|:\^)",
     "Name what to stage, not what to skip. `git status --short` lists the changed files; then "
     "`git add path/to/file1 path/to/file2`."),
    ("A-add-whole", r"^blanket_stage_guard: ",
     "Stage the files you changed by name. Run `git status --short` to list them, then "
     "`git add path/to/file1 path/to/file2`."),
    # policy C: never destroy uncommitted or pushed work
    ("C-reset-hard", r"^data_loss_guard: .*reset --hard",
     "Keep the work. Set it aside with `git stash push -m \"before reset\"`, or keep it on a new branch with "
     "`git switch -c backup-branch`. To move the branch back but keep the changes, use "
     "`git reset --soft HEAD~1`. To unstage one file, use `git restore --staged path/to/file`."),
    ("C-clean-config", r"^data_loss_guard: .*clean\.requireForce",
     "Leave clean.requireForce on. Preview what git clean would remove with `git clean -n`, then delete "
     "named files with `rm path/to/file`."),
    ("C-clean", r"^data_loss_guard: git clean",
     "Do not delete untracked files in bulk. Preview with `git clean -n`, then remove the files you mean "
     "by name with `rm path/to/file`, or add them to .gitignore."),
    ("C-discard-whole-tree", r"^data_loss_guard: .*over the whole tree discards",
     "Discard changes one file at a time, by name: `git restore path/to/file`. To set everything aside "
     "instead, run `git stash push -m \"wip\"`."),
    ("C-switch-discard", r"^data_loss_guard: (?:git checkout --force|git switch that discards)",
     "Save your changes first with `git stash push -m \"wip\"`, then switch with `git switch branch-name`. "
     "Bring the changes back later with `git stash apply`."),
    ("C-branch-move", r"^data_loss_guard: (?:git checkout -B|git branch --force moves|git fetch \S+ force-updates)",
     "Do not move an existing branch. Make a new one where you need it: "
     "`git switch -c new-branch origin/main`. To update a branch from its remote, use "
     "`git pull --rebase origin branch-name`."),
    ("C-overwrite-worktree", r"^data_loss_guard: (?:git checkout-index|git read-tree --reset)",
     "Restore named files from the commit you want: `git restore --source=commit-id -- path/to/file`."),
    ("C-remote-push-config", r"^data_loss_guard: -c remote\.\*\.push",
     "Push one named branch: `git push origin branch-name`. Do not set a forcing push refspec."),
    ("C-force-push", r"^data_loss_guard: .*force push",
     "Use `git push origin branch-name` without --force. If the push is rejected because the remote moved, "
     "run `git fetch origin` and `git rebase origin/branch-name`, then push again."),
    ("C-remote-delete", r"^data_loss_guard: (?:git push --delete|git push :|git push --prune|git push --mirror|"
                        r"remote\.\*\.mirror)",
     "Leave the remote branches in place and push only the branch you mean: `git push origin branch-name`. "
     "To drop a merged branch from your own clone, use `git branch -d branch-name`."),
    ("C-branch-delete", r"^data_loss_guard: git branch (?:-D|--delete --force)",
     "Use `git branch -d branch-name`, which refuses to delete unmerged work. If it refuses, merge the "
     "branch first, or keep it under a new name with `git branch -m old-name new-name`."),
    ("C-stash-drop", r"^data_loss_guard: git stash (?:drop|clear)",
     "Keep the stash. See it with `git stash list`, apply it with `git stash apply`, or turn it into a "
     "branch with `git stash branch new-branch`."),
    ("C-reflog", r"^data_loss_guard: git reflog",
     "Leave the reflog alone; it is how lost commits come back. To shrink the repo, run `git gc`."),
    ("C-worktree-force", r"^data_loss_guard: git worktree remove --force",
     "Commit or stash inside the worktree first, then remove it without --force: "
     "`git worktree remove path/to/worktree`."),
    ("C-git-rm-whole", r"^data_loss_guard: git rm over the whole tree",
     "Remove files by name: `git rm path/to/file`. Run `git status --short` first to see what is tracked."),
    ("C-symbolic-ref-delete", r"^data_loss_guard: git symbolic-ref --delete",
     "Leave HEAD in place. To move to another branch, run `git switch branch-name`."),
    ("C-delete-dotgit", r"^data_loss_guard: deletes the repository's own history",
     "Leave .git in place. If the repo looks broken, check it with `git fsck`. To start over on fresh "
     "files, make a new branch with `git switch -c new-branch`."),
    ("C-unparseable", r"^data_loss_guard: a work-destroying git form inside an unparseable",
     "Fix the quoting so every quote closes, then run one plain git command at a time. Check the state "
     "first with `git status --short`."),
    # fail-closed shapes (v3 asked; v4 denies with a way forward)
    ("F-hook-write", r"^fail_closed: .*(?:git hook|hook files)",
     "Leave the hook files in place. Read the hook with `cat .git/hooks/pre-commit` to see what it checks, "
     "fix the code it complains about, and run the command again."),
    ("F-gitdir-delete", r"^fail_closed: a delete inside \.git",
     "Use git's own command to clear an operation in progress: `git rebase --abort`, `git merge --abort` "
     "or `git cherry-pick --abort`."),
    ("F-worktree-delete", r"^fail_closed: a recursive delete of the whole worktree",
     "Delete named paths only: `rm -r path/to/dir`. Check what is there first with `git status --short`."),
    ("F-symbolic-ref", r"^fail_closed: git symbolic-ref",
     "Move HEAD with `git switch branch-name`, or start an empty branch with "
     "`git switch --orphan new-branch`."),
    ("F-read-tree", r"^fail_closed: git read-tree",
     "Bring named files from another commit with `git restore --source=commit-id -- path/to/file`, or "
     "merge the branch with `git merge branch-name`."),
    ("F-history-rewrite", r"^fail_closed: git \S+ rewrites history",
     "Do not rewrite history in place. Make the change as a new commit: edit the files, stage them with "
     "`git add path/to/file`, then `git commit -m \"message\"`."),
    ("F-git-alias", r"^fail_closed: `git \S+` is not a git command",
     "Spell out the git command the alias stands for. List the aliases with "
     "`git config --get-regexp alias` and run the full command."),
    ("F-git-sub-unknown", r"^fail_closed: (?:the git subcommand is unknown|the git stash action is unknown|"
                          r"git has a word before its subcommand)",
     "Write the git subcommand and its flags literally, for example `git stash list` or "
     "`git status --short`. Print a variable first with `echo \"$VAR\"` and paste its value."),
    ("F-git-global-option", r"^fail_closed: a git global option value",
     "Write the path literally: `git -C path/to/repo status`. Print a variable first with "
     "`echo \"$VAR\"` and paste its value."),
    ("F-config-key", r"^fail_closed: git config with a key",
     "Write the config key and value literally, for example `git config user.name \"Name\"`."),
    ("F-command-setting", r"^fail_closed: (?:git config \S+ set to a value|an environment variable git runs|"
                          r"a config file swapped in|-c include)",
     "Write the program literally, for example `git config core.editor vim` or "
     "`GIT_SSH_COMMAND=\"ssh -i path/to/key\" git fetch origin`. Do not load git config from another file."),
    ("F-eval", r"^fail_closed: eval of text",
     "Do not eval generated text. Print it with `echo \"$VAR\"`, then run the printed commands as plain "
     "text, one call each."),
    ("F-shell-c", r"^fail_closed: (?:a shell runs -c text|the command word itself is unknown)",
     "Run the command directly, not through sh -c or a variable. Print it with `echo \"$VAR\"` and type "
     "the printed command as a plain Bash command."),
    ("F-pipe-to-shell", r"^fail_closed: a shell runs (?:a pipe|a script)",
     "Do not pipe generated or downloaded text into a shell. Save it to a file and read it first, for "
     "example `cat script.sh`, then run its steps as plain commands."),
    ("F-interpreter", r"^fail_closed: interpreter code builds",
     "Run git directly in Bash with literal arguments, for example `git status --short`, instead of "
     "building the command inside python, perl, ruby or node."),
    ("F-nested-code", r"^fail_closed: code nested deeper",
     "Decode the payload to the screen first, for example `echo \"$VAR\" | base64 -d`, and run what it "
     "says as plain commands."),
    ("F-quoting", r"^fail_closed: quoting the guard cannot parse",
     "Fix the quoting so every quote closes, then run one plain command at a time. Check the state with "
     "`git status --short`."),
    ("F-var", r"^fail_closed: git (\S+) has (?:an unquoted word|an argument|a pathspec|an option value)", None),
    ("F-guard-error", r"^fail_closed: guard error",
     "Split the command into shorter plain steps, one command per call, starting with "
     "`git status --short`."),
]
_REDIRECTS_RE = [(sid, re.compile(rx), text) for sid, rx, text in REDIRECTS]
UNMATCHED = "UNMATCHED"
_PLAIN_PREFIX = "Run git directly as plain text, not through decoded or generated code. "
_BACKTICK = re.compile(r"`([^`]+)`")


def _core_reason(why):
    for tail in _V3_TAILS:
        why = why.replace(tail, "")
    return why


def redirect_for(core):
    """-> (shape id, redirect text). UNMATCHED means no specific redirect: bench.py fails on it."""
    for sid, rx, text in _REDIRECTS_RE:
        m = rx.search(core)
        if not m:
            continue
        if sid == "F-var":
            sub = m.group(1)
            sid = "F-var-" + (sub if sub in _VAR_ALT else "other")
            alt = _VAR_ALT.get(sub, "git status --short")
            text = ("Write the value into the command literally so it can be checked. Print it first with "
                    "`echo \"$VAR\"`, then run the command with the printed value, for example `%s`." % alt)
        if "(found in code" in core or "(found in text" in core:
            text = _PLAIN_PREFIX + text
        return sid, text
    return UNMATCHED, ("Split the command into plain literal steps and run each one by itself. Check the "
                       "state first with `git status --short`.")


def alternatives(redirect):
    """Every command in backticks inside a redirect. Each one must be a command the guard allows."""
    return _BACKTICK.findall(redirect or "")


def decide_full(command):
    """-> dict(verdict "deny"|"allow", origin "block"|"fail_closed"|None, v3 verdict, shape, redirect,
    alternatives, reason). reason is what the hook prints: the v3 reason without its ask tails, then
    DO THIS INSTEAD and the redirect."""
    v3, why = _decide3(command)
    if v3 == "allow":
        return {"verdict": "allow", "origin": None, "v3": v3, "shape": None, "redirect": "",
                "alternatives": [], "reason": ""}
    core = _core_reason(why)
    shape, text = redirect_for(core)
    return {"verdict": "deny", "origin": "block" if v3 == "block" else "fail_closed", "v3": v3,
            "shape": shape, "redirect": text, "alternatives": alternatives(text),
            "reason": core.rstrip() + REDIRECT_MARK + text}


def decide(command):
    """Return ("block" | "allow", reason). Version 4 never returns "ask": every v3 stop is a block
    whose reason ends with a redirect the agent can follow."""
    d = decide_full(command)
    return ("block", d["reason"]) if d["verdict"] == "deny" else ("allow", "")


def _undo_hook(command, payload):
    """On an allow: let undo.py snapshot the repo at the hook's cwd if the command could change it.
    Off when AGENT_GUARD_UNDO=0. Only the payload's cwd or AGENT_GUARD_UNDO_REPO picks the repo,
    never a fallback, so a run with neither snapshots nothing. Returns a message on failure."""
    if os.environ.get("AGENT_GUARD_UNDO", "1") == "0":
        return None
    cwd = (payload.get("cwd") if isinstance(payload, dict) else None) or os.environ.get("AGENT_GUARD_UNDO_REPO")
    if not cwd:
        return None
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import undo
        undo.pre_tool_use(command, cwd)
        return None
    except Exception as exc:
        return ("UNDO SNAPSHOT FAILED (%s: %s). This command runs WITHOUT an undo point."
                % (type(exc).__name__, str(exc)[:160]))


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
    d = decide_full(command)
    if d["verdict"] == "deny":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": d["reason"]}}))
        return 0
    note = _undo_hook(command, payload)
    if note:
        print(json.dumps({"systemMessage": note}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
