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


def _unescape(s):
    """Backslash escapes as echo -e, printf and $'..' read them."""
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
    t = t  # DEFECT (negative control): $IFS and ${IFS} are not turned into a space
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
                out.append(_unescape(a) if p == "%b" else a)
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
        return (_unescape(s) if esc else s) + ("\n" if nl else "")
    if head == "printf":
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
        try:
            if head == "base32":
                body += "=" * (-len(body) % 8)
                return _decode_bytes(base64.b32decode(body))
            body += "=" * (-len(body) % 4)
            return _decode_bytes(base64.b64decode(body, validate=True))
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
            elif word in ("source", ".") and rest[:1] in (["/dev/stdin"], ["-"], ["/dev/fd/0"]) \
                    and idx == len(pl) - 1 and idx > 0:
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


def decide(command):
    """Return ("block", reason) or ("allow", reason). An allow carries an empty reason, except a
    fail-open, whose reason names the exception."""
    try:
        why = _check(command or "", _root(), 0)
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
