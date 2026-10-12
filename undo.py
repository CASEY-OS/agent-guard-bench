#!/usr/bin/env python3
"""undo.py: an undo point for shell commands in a git repo. Standard library and the git CLI only.

Why. Claude Code's checkpointing does not track files changed by Bash commands, and those changes
cannot be undone through rewind (code.claude.com/docs/en/checkpointing, read 2026-10-12). A guard
can deny what it sees. It cannot see everything. This layer makes what it allowed undoable.

snapshot(repo) captures the whole working state WITHOUT touching the user's index, HEAD, branches or
stash list:
  - the worktree: tracked, staged, unstaged and untracked (not ignored) files, through a TEMPORARY
    index (a copy of the real one), `git add -A` into it, `git write-tree`;
  - the real index, as its raw bytes (keeps conflict stages, intent-to-add, flags) and as a tree;
  - every ref under refs/heads, refs/tags, refs/remotes and refs/stash, symbolic refs, HEAD, the raw
    stash reflog, annotated tag objects, and the in-progress state files (MERGE_HEAD and friends);
  - the permission bits of every captured file.
It stores one commit under refs/agent-guard/snapshots/<UTC timestamp>. Its parents are HEAD and every
recorded ref tip and stash entry, so `git gc` cannot prune a commit a snapshot can restore. A snapshot
identical to the newest one is not stored twice. Only the newest KEEP (default 50, AGENT_GUARD_UNDO_KEEP)
are kept; older refs are deleted, and git gc reclaims their objects later.

restore(repo, id) puts the worktree, the index, refs/heads, refs/tags, refs/stash, HEAD, the stash
list and the state files back exactly, after taking a "pre-restore" snapshot so the restore itself
can be undone. It never touches a remote, and it leaves refs/remotes as they are, because they
describe the remote. When a remote-tracking ref moved since the snapshot (a force push, a push
--delete) it prints the one push that puts the remote back, and does not run it. Run that push only
if the undone command pushed; if you fetched someone else's work since, do not.

pre_tool_use(command, cwd) is the hook path: plan(command, cwd) decides whether the command could
change the repo, and if so a snapshot is taken first. Read-only commands cost no git call.

CLI: python3 undo.py [--repo PATH] list | snapshot [--label L] | restore <id> | restore --last
     [--no-safety] | plan <command>

Blind to: ignored files, files outside the repo, empty directories, owner, ACLs, xattrs and mtimes,
submodule contents and nested repos, skip-worktree and sparse paths, branch reflogs other than the
stash, an in-progress rebase directory, and remote state the local repo never fetched.
"""
import datetime
import json
import os
import posixpath
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile

REF_NS = "refs/agent-guard/snapshots/"
KEEP_DEFAULT = 50
REF_SPACES = ("refs/heads/", "refs/tags/", "refs/remotes/", "refs/stash")
STATE_FILES = ("MERGE_HEAD", "MERGE_MSG", "MERGE_MODE", "MERGE_AUTOSTASH", "CHERRY_PICK_HEAD",
               "REVERT_HEAD", "ORIG_HEAD", "AUTO_MERGE")
IDENT = {"GIT_AUTHOR_NAME": "agent-guard", "GIT_AUTHOR_EMAIL": "agent-guard@localhost",
         "GIT_COMMITTER_NAME": "agent-guard", "GIT_COMMITTER_EMAIL": "agent-guard@localhost"}
_KEEP_ENV = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_SYSTEM", "GIT_CEILING_DIRECTORIES",
             "GIT_EXEC_PATH")


class UndoError(Exception):
    pass


def _env(extra=None):
    """The caller's environment minus every GIT_* variable that could point git at another repo or
    index, plus a fixed locale."""
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k in _KEEP_ENV}
    e["LC_ALL"] = "C"
    e["GIT_TERMINAL_PROMPT"] = "0"
    e.update(IDENT)
    if extra:
        e.update(extra)
    return e


def _git(cwd, args, env=None, input=None, check=True):
    p = subprocess.run(["git"] + list(args), cwd=cwd, env=env or _env(), input=input,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode != 0:
        raise UndoError("git %s failed (%d): %s" % (" ".join(args[:3]), p.returncode,
                                                    p.stderr.decode("utf-8", "replace").strip()[:300]))
    return p


def _out(cwd, args, **kw):
    return _git(cwd, args, **kw).stdout.decode("utf-8", "surrogateescape").strip()


def paths(repo):
    """-> (toplevel, per-worktree git dir, common git dir), all absolute."""
    o = _out(repo, ["rev-parse", "--path-format=absolute", "--show-toplevel", "--absolute-git-dir",
                    "--git-common-dir"]).split("\n")
    if len(o) != 3 or not o[0]:
        raise UndoError("not inside a git worktree: %s" % repo)
    return o[0], o[1], o[2]


def _hash_blobs(top, blobs, tmpdir):
    """blobs: list of bytes -> list of blob ids, one git call."""
    if not blobs:
        return []
    names = []
    for n, b in enumerate(blobs):
        f = os.path.join(tmpdir, "blob%d" % n)
        with open(f, "wb") as fh:
            fh.write(b)
        names.append(f)
    out = _out(top, ["hash-object", "-w", "--no-filters", "--stdin-paths"],
               input=("\n".join(names) + "\n").encode()).split("\n")
    if len(out) != len(blobs):
        raise UndoError("hash-object returned %d ids for %d blobs" % (len(out), len(blobs)))
    return out


def _mktree(top, entries):
    """entries: list of (mode, type, id, name) -> tree id."""
    body = b"".join(("%s %s %s\t" % (m, t, i)).encode() + os.fsencode(n) + b"\0"
                    for m, t, i, n in sorted(entries, key=lambda e: e[3]))
    return _out(top, ["mktree", "-z"], input=body)


def _refs(top):
    """-> list of (kind, value, name). kind is 'ref' (value = object id) or 'symref' (value = target)."""
    fmt = "%(refname)%00%(objectname)%00%(objecttype)%00%(symref)%00%(*objectname)%00%(*objecttype)"
    raw = _out(top, ["for-each-ref", "--format=" + fmt] + [s.rstrip("/") for s in REF_SPACES])
    rows = []
    for line in raw.split("\n"):
        if not line:
            continue
        name, oid, otype, symref, peeled, ptype = line.split("\0")
        rows.append((name, oid, otype, symref, peeled, ptype))
    return rows


def _head(top):
    p = _git(top, ["symbolic-ref", "-q", "HEAD"], check=False)
    if p.returncode == 0:
        return ("sym", p.stdout.decode().strip())
    p = _git(top, ["rev-parse", "-q", "--verify", "HEAD"], check=False)
    return ("detached", p.stdout.decode().strip())


def _read(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except (IOError, OSError):
        return None


def _snapshots(top):
    raw = _out(top, ["for-each-ref", "--sort=refname", "--format=%(refname) %(objectname)",
                     REF_NS.rstrip("/")])
    return [(l.split(" ")[0][len(REF_NS):], l.split(" ")[1]) for l in raw.split("\n") if l]


def _new_id(existing):
    """A UTC timestamp. It always sorts after the newest id, even if the clock went backwards."""
    sid = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    if existing and sid <= existing[-1]:
        sid = existing[-1] + "-1"
    return sid


def snapshot(repo, label="", keep=None, force=False):
    """Capture the full working state. -> snapshot id (an existing id when nothing changed)."""
    top, gitdir, common = paths(repo)
    keep = int(os.environ.get("AGENT_GUARD_UNDO_KEEP", KEEP_DEFAULT)) if keep is None else keep
    tmpdir = tempfile.mkdtemp(prefix="agent-guard-undo-")
    try:
        idx_bytes = _read(os.path.join(gitdir, "index"))
        tmp_index = os.path.join(tmpdir, "index")
        if idx_bytes is not None:
            with open(tmp_index, "wb") as fh:
                fh.write(idx_bytes)
        tenv = _env({"GIT_INDEX_FILE": tmp_index})
        p = _git(top, ["write-tree"], env=tenv, check=False)      # fails on conflict stages: kept as raw bytes
        itree = p.stdout.decode().strip() if p.returncode == 0 else None
        p = _git(top, ["add", "-A", "--ignore-errors"], env=tenv, check=False)
        warnings = [l for l in p.stderr.decode("utf-8", "replace").split("\n") if l.strip()][:20]
        wtree = _out(top, ["write-tree"], env=tenv)
        # permission bits of every captured regular file
        listing = _git(top, ["ls-tree", "-r", "-z", "--full-tree", wtree]).stdout.split(b"\0")
        modes = []
        for ent in listing:
            if not ent:
                continue
            meta, path = ent.split(b"\t", 1)
            if meta.split(b" ")[1] != b"blob":
                continue
            try:
                st = os.lstat(os.path.join(os.fsencode(top), path))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                modes.append(b"%o %s" % (stat.S_IMODE(st.st_mode), path))
        refs = _refs(top)
        head = _head(top)
        lines, parents, tagobjs, keepobjs = [], [], [], []
        if head[0] == "detached" and head[1]:
            parents.append(head[1])
        else:
            p = _git(top, ["rev-parse", "-q", "--verify", "HEAD"], check=False)
            if p.returncode == 0:
                parents.append(p.stdout.decode().strip())
        lines.append("HEAD %s %s" % head)
        for name, oid, otype, symref, peeled, ptype in refs:
            if symref:
                lines.append("symref %s %s" % (symref, name))
                continue
            lines.append("ref %s %s" % (oid, name))
            if otype == "commit":
                parents.append(oid)
            elif otype == "tag":
                tagobjs.append(oid)
                if ptype == "commit":
                    parents.append(peeled)
                elif peeled:
                    keepobjs.append((peeled, ptype))
            else:
                keepobjs.append((oid, otype))
        stash_log = _read(os.path.join(common, "logs", "refs", "stash"))
        if stash_log:
            for l in stash_log.split(b"\n"):
                f = l.split(b" ")
                if len(f) > 1 and re.match(rb"^[0-9a-f]{40,64}$", f[1]):
                    parents.append(f[1].decode())
        # annotated tag objects, the whole chain, so a deleted tag can be rebuilt byte for byte
        tag_raw = {}
        todo = list(tagobjs)
        while todo:
            t = todo.pop()
            if t in tag_raw:
                continue
            raw = _git(top, ["cat-file", "tag", t]).stdout
            tag_raw[t] = raw
            m = re.match(rb"object ([0-9a-f]+)\ntype (\w+)\n", raw)
            if m and m.group(2) == b"tag":
                todo.append(m.group(1).decode())
        names, blobs = [], []
        if idx_bytes is not None:
            names.append(("index.bin",))
            blobs.append(idx_bytes)
        names.append(("refs.txt",))
        blobs.append(("\n".join(lines) + "\n").encode("utf-8", "surrogateescape"))
        names.append(("modes.bin",))
        blobs.append(b"\0".join(modes))
        if stash_log is not None:
            names.append(("stash-log.bin",))
            blobs.append(stash_log)
        for f in STATE_FILES:
            b = _read(os.path.join(gitdir, f))
            if b is not None:
                names.append(("state", f))
                blobs.append(b)
        for t, raw in sorted(tag_raw.items()):
            names.append(("tagobjs", t))
            blobs.append(raw)
        ids = _hash_blobs(top, blobs, tmpdir)
        root, sub = [], {}
        for nm, bid in zip(names, ids):
            if len(nm) == 1:
                root.append(("100644", "blob", bid, nm[0]))
            else:
                sub.setdefault(nm[0], []).append(("100644", "blob", bid, nm[1]))
        for k, ents in sub.items():
            root.append(("040000", "tree", _mktree(top, ents), k))
        root.append(("040000", "tree", wtree, "worktree"))
        if itree:
            root.append(("040000", "tree", itree, "index-tree"))
        kept = [("100644" if t == "blob" else "040000", t, o, o) for o, t in keepobjs if t in ("blob", "tree")]
        if kept:
            root.append(("040000", "tree", _mktree(top, kept), "keep"))
        state_tree = _mktree(top, root)
        existing = _snapshots(top)
        if existing and not force:
            p = _git(top, ["rev-parse", "-q", "--verify", existing[-1][1] + ":state"], check=False)
            if p.returncode == 0 and p.stdout.decode().strip() == state_tree:
                return existing[-1][0]                                   # nothing changed since
        sid = _new_id([s for s, _ in existing])
        meta = json.dumps({"version": 1, "id": sid, "toplevel": top, "label": label[:500],
                           "warnings": warnings}, sort_keys=True).encode()
        meta_id = _hash_blobs(top, [meta], tmpdir)[0]
        top_tree = _mktree(top, [("040000", "tree", state_tree, "state"), ("100644", "blob", meta_id, "meta.json")])
        seen, plist = set(), []
        for p_ in parents:
            if p_ and p_ not in seen:
                seen.add(p_)
                plist += ["-p", p_]
        subject = "agent-guard snapshot %s: %s" % (sid, " ".join(label.split())[:120])
        commit = _out(top, ["commit-tree", "--no-gpg-sign", top_tree] + plist, input=subject.encode())
        _git(top, ["update-ref", REF_NS + sid, commit, ""])          # "" = must not exist yet
        all_ids = [s for s, _ in existing] + [sid]
        if keep > 0 and len(all_ids) > keep:
            script = "".join("delete %s%s\n" % (REF_NS, s) for s in all_ids[:len(all_ids) - keep])
            _git(top, ["update-ref", "--stdin"], input=script.encode())
        return sid
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def list_snapshots(repo):
    top, _, _ = paths(repo)
    out = []
    for sid, sha in _snapshots(top):
        subj = _out(top, ["log", "-1", "--format=%s", sha])
        out.append({"id": sid, "commit": sha, "label": subj.split(": ", 1)[1] if ": " in subj else ""})
    return out


def _blob(top, spec):
    p = _git(top, ["cat-file", "blob", spec], check=False)
    return p.stdout if p.returncode == 0 else None


def _remove_empty_parents(top, path):
    d = os.path.dirname(path)
    while len(d) > len(top) and d.startswith(top + os.sep):
        try:
            os.rmdir(d)
        except OSError:
            return
        d = os.path.dirname(d)


def restore(repo, sid, safety=True):
    """Put the worktree, index, local refs, HEAD, stash list and state files back to snapshot sid.
    refs/remotes are left alone; the repair push for each moved one is returned, never run."""
    top, gitdir, common = paths(repo)
    if sid == "--last":
        snaps = _snapshots(top)
        if not snaps:
            raise UndoError("no snapshot to restore in %s" % top)
        sid = snaps[-1][0]
    p = _git(top, ["rev-parse", "-q", "--verify", REF_NS + sid + "^{commit}"], check=False)
    if p.returncode != 0:
        raise UndoError("no snapshot %s in %s" % (sid, top))
    snap = p.stdout.decode().strip()
    meta = json.loads(_blob(top, snap + ":meta.json") or b"{}")
    if meta.get("toplevel") and os.path.realpath(meta["toplevel"]) != os.path.realpath(top):
        raise UndoError("snapshot %s belongs to %s, not %s" % (sid, meta["toplevel"], top))
    if os.path.exists(os.path.join(gitdir, "index.lock")):
        raise UndoError("index.lock exists: another git process is running in %s" % top)
    st = snap + ":state"
    before_refs = {r[0]: r[1] for r in _refs(top) if not r[3]}
    safety_id = snapshot(top, label="pre-restore of " + sid) if safety else None
    # 1. worktree: delete what the snapshot did not have, then write every snapshot file
    wtree = _out(top, ["rev-parse", st + "/worktree"])
    target = {}
    for ent in _git(top, ["ls-tree", "-r", "-z", "--full-tree", wtree]).stdout.split(b"\0"):
        if ent:
            meta_, path = ent.split(b"\t", 1)
            target[os.fsdecode(path)] = meta_.split(b" ")[0].decode()
    current = _git(top, ["ls-files", "-z", "-c", "-o", "--exclude-standard"]).stdout.split(b"\0")
    ignored = set(_git(top, ["ls-files", "-z", "-c", "-i", "--exclude-standard"]).stdout.split(b"\0"))
    deleted = 0
    for raw in current:
        rel = os.fsdecode(raw)
        if not rel or rel.endswith("/") or rel in target or raw in ignored:
            continue                                     # "x/" is a nested repo: never touched
        full = os.path.join(top, rel)
        if os.path.islink(full) or os.path.isfile(full):
            os.unlink(full)
            deleted += 1
            _remove_empty_parents(top, full)
    for rel, mode in target.items():
        if mode == "160000":
            continue
        full = os.path.join(top, rel)
        parts = rel.split("/")
        for k in range(1, len(parts)):                   # a file or link where a directory must be
            pre = os.path.join(top, *parts[:k])
            if os.path.islink(pre) or (os.path.lexists(pre) and not os.path.isdir(pre)):
                os.unlink(pre)
        if os.path.isdir(full) and not os.path.islink(full):
            shutil.rmtree(full)                          # a directory where a file must be
    tmpdir = tempfile.mkdtemp(prefix="agent-guard-undo-")
    try:
        tenv = _env({"GIT_INDEX_FILE": os.path.join(tmpdir, "index")})
        _git(top, ["read-tree", wtree], env=tenv)
        _git(top, ["checkout-index", "-a", "-f"], env=tenv)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    modes = _blob(top, st + "/modes.bin") or b""
    for ent in modes.split(b"\0"):
        if ent:
            m, path = ent.split(b" ", 1)
            full = os.path.join(os.fsencode(top), path)
            if os.path.isfile(full) and not os.path.islink(full):
                os.chmod(full, int(m, 8))
    # 2. the index, raw bytes, under git's own lock protocol
    idx = _blob(top, st + "/index.bin")
    lock = os.path.join(gitdir, "index.lock")
    if idx is not None:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            os.write(fd, idx)
        finally:
            os.close(fd)
        os.replace(lock, os.path.join(gitdir, "index"))
    elif os.path.exists(os.path.join(gitdir, "index")):
        os.unlink(os.path.join(gitdir, "index"))
    _git(top, ["update-index", "-q", "--refresh"], check=False)
    # 3. tag objects gc may have pruned, then refs, HEAD, the stash reflog and state files
    tagtree = _git(top, ["rev-parse", "-q", "--verify", st + "/tagobjs"], check=False)
    if tagtree.returncode == 0:
        for ent in _git(top, ["ls-tree", "-z", st + "/tagobjs"]).stdout.split(b"\0"):
            if not ent:
                continue
            t = ent.split(b"\t", 1)[1].decode()
            if _git(top, ["cat-file", "-e", t], check=False).returncode != 0:
                got = _out(top, ["hash-object", "-t", "tag", "-w", "--stdin"],
                           input=_blob(top, st + "/tagobjs/" + t))
                if got != t:
                    raise UndoError("rebuilt tag object %s came back as %s" % (t, got))
    rec = (_blob(top, st + "/refs.txt") or b"").decode("utf-8", "surrogateescape").split("\n")
    want, syms, head = {}, {}, None
    for l in rec:
        if l.startswith("ref "):
            _, oid, name = l.split(" ", 2)
            want[name] = oid
        elif l.startswith("symref "):
            _, tgt, name = l.split(" ", 2)
            syms[name] = tgt
        elif l.startswith("HEAD "):
            f = l.split(" ")
            head = (f[1], f[2] if len(f) > 2 else "")
    now = _refs(top)
    script = []
    for name, oid, _t, symref, _p, _pt in now:
        if name not in want and name not in syms and not name.startswith("refs/remotes/"):
            script.append("option no-deref\ndelete %s\n" % name)
    for name, oid in want.items():
        if not name.startswith("refs/remotes/"):
            script.append("option no-deref\nupdate %s %s\n" % (name, oid))
    if script:
        _git(top, ["update-ref", "--stdin"], input="".join(script).encode("utf-8", "surrogateescape"))
    for name, tgt in syms.items():
        if not name.startswith("refs/remotes/"):
            _git(top, ["symbolic-ref", name, tgt])
    if head and head[0] == "sym":
        _git(top, ["symbolic-ref", "HEAD", head[1]])
    elif head and head[1]:
        _git(top, ["update-ref", "--no-deref", "HEAD", head[1]])
    stash_log = _blob(top, st + "/stash-log.bin")
    slog = os.path.join(common, "logs", "refs", "stash")
    if stash_log is not None and "refs/stash" in want:
        os.makedirs(os.path.dirname(slog), exist_ok=True)
        with open(slog, "wb") as fh:
            fh.write(stash_log)
    for f in STATE_FILES:
        b = _blob(top, st + "/state/" + f)
        path = os.path.join(gitdir, f)
        if b is not None:
            with open(path, "wb") as fh:
                fh.write(b)
        elif os.path.exists(path):
            os.unlink(path)
    # 4. refs/remotes describe the remote, which restore never touches. Where one moved since the
    #    snapshot, print the push that would put the remote back. Run it only if the undone command
    #    pushed (a force push, a push --delete). If you fetched someone else's work, do not.
    hints = []
    for name, oid in sorted(want.items()):
        m = re.match(r"^refs/remotes/([^/]+)/(.+)$", name)
        if m and before_refs.get(name) != oid and m.group(2) != "HEAD":
            r, b = m.group(1), m.group(2)
            if name in before_refs:
                hints.append("git push --force-with-lease=refs/heads/%s:%s %s %s:refs/heads/%s"
                             % (b, before_refs[name], r, oid, b))
            else:
                hints.append("git push %s %s:refs/heads/%s" % (r, oid, b))
    return {"restored": sid, "safety_snapshot": safety_id, "files_deleted": deleted,
            "files_written": len(target), "refs": len(want), "remote_repair": hints}


# ---- the hook path: should this command get a snapshot first? ----
READONLY = {"cat", "head", "tail", "ls", "stat", "file", "wc", "grep", "egrep", "fgrep", "rg", "ag", "diff",
            "cmp", "md5", "md5sum", "shasum", "sha1sum", "sha256sum", "du", "df", "echo", "printf", "test",
            "[", "[[", "]]", "realpath", "readlink", "basename", "dirname", "od", "hexdump", "strings", "cut",
            "true", "false", ":", "pwd", "which", "type", "whoami", "id", "uname", "date", "hostname",
            "jq", "less", "more", "nl", "column", "tr", "seq", "sleep", "wait", "export", "unset", "set",
            "local", "declare", "read", "ps", "env", "printenv", "cal", "bc", "expr"}
WRAPPERS = {"sudo", "doas", "command", "builtin", "exec", "nohup", "time", "nice", "ionice", "stdbuf",
            "timeout", "xargs", "env"}
KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}", "(", ")",
            "for", "in", "select", "case", "esac", "function", "coproc"}
MUTATORS = {"rm", "rmdir", "unlink", "mv", "cp", "ln", "touch", "mkdir", "chmod", "chown", "chgrp",
            "truncate", "tee", "dd", "install", "rsync", "shred", "patch", "tar", "unzip", "gunzip", "gzip",
            "bzip2", "xz", "zip", "sed", "perl", "find", "sort", "uniq", "tree", "split", "csplit"}
GIT_READONLY = {"status", "log", "diff", "show", "blame", "grep", "describe", "shortlog", "rev-parse",
                "rev-list", "ls-files", "ls-tree", "ls-remote", "cat-file", "for-each-ref", "show-ref",
                "name-rev", "merge-base", "var", "help", "version", "whatchanged", "count-objects",
                "check-ignore", "check-attr", "cherry", "range-diff", "verify-commit", "verify-tag",
                "show-branch", "diff-tree", "diff-files", "diff-index", "fsck", "check-ref-format"}
GIT_GLOBAL_VAL = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
OUT_OPS = {">", ">>", ">|", "&>", "&>>", "<>", ">&"}
SEP = {";", "&&", "||", "|", "&", "|&", "(", ")", "\n", ";;"}
SAFE_SINKS = ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty")


def _strip_heredocs(cmd):
    out, lines, i = [], cmd.split("\n"), 0
    while i < len(lines):
        out.append(lines[i])
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", lines[i])
        i += 1
        if m:
            end = next((j for j in range(i, len(lines)) if lines[j].strip() == m.group(1)), None)
            if end is not None:
                i = end + 1
    return "\n".join(out)


def _split(cmd):
    lx = shlex.shlex(cmd.replace("\\\n", " "), posix=True, punctuation_chars=";&|()<>\n")
    lx.whitespace_split = True
    lx.commenters = ""
    lx.whitespace = " \t\r"
    toks = list(lx)
    segs, cur = [], []
    for t in toks:
        if t in SEP or t == "\n" or (t and set(t) <= set(";&|()\n") and not t.startswith(">")):
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        segs.append(cur)
    return segs


def _literal(w):
    return not re.search(r"[$`*?\[\]{}~]", w)


def _resolve(w, cwd):
    """An absolute path for a literal word, or None when it cannot be known."""
    if not _literal(w):
        return None
    if os.path.isabs(w):
        p = w
    elif cwd is None:
        return None
    else:
        p = os.path.join(cwd, w)
    p = os.path.normpath(p)
    parent = os.path.realpath(os.path.dirname(p))
    return os.path.join(parent, os.path.basename(p))


def plan(command, cwd):
    """-> {"effects": [...], "why": str}. An effect is ("git", dir), ("path", abs path or None) or
    ("unknown", None). No effects means provably read-only: no snapshot."""
    effects, why = [], []
    if re.search(r"\$\(|`|<\(|>\(", command):
        return {"effects": [("unknown", None)], "why": "command substitution runs code the plan cannot read"}
    try:
        segs = _split(_strip_heredocs(command))
    except ValueError:
        return {"effects": [("unknown", None)], "why": "quoting the plan cannot parse"}
    here = cwd
    for seg in segs:
        argv, redirs, k = [], [], 0
        while k < len(seg):
            t = seg[k]
            if t in OUT_OPS or (t.endswith(">") and t[:-1].isdigit()):
                tgt = seg[k + 1] if k + 1 < len(seg) else ""
                k += 2
                if t.endswith("&") or t == ">&":
                    if tgt.isdigit() or tgt == "-":
                        continue
                redirs.append(tgt)
                continue
            if t in ("<", "<<", "<<<", "<&"):
                k += 2
                continue
            if t.isdigit() and k + 1 < len(seg) and seg[k + 1] in OUT_OPS:
                k += 1
                continue
            argv.append(t)
            k += 1
        for tgt in redirs:
            if tgt in SAFE_SINKS or tgt.startswith("/dev/fd/"):
                continue
            effects.append(("path", _resolve(tgt, here)))
            why.append("writes " + tgt)
        while argv and (argv[0] in KEYWORDS or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0])):
            if argv[0] in ("for", "select", "case"):
                argv = []
                break
            argv = argv[1:]
        while argv and argv[0] in WRAPPERS:
            w = argv.pop(0)
            if w in ("timeout",) and argv and not argv[0].startswith("-"):
                argv.pop(0)
            while argv and (argv[0].startswith("-") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0])):
                opt = argv.pop(0)
                if w in ("nice", "xargs", "timeout", "env") and opt in ("-n", "-I", "-L", "-P", "-d", "-s",
                                                                        "-u", "-k", "-s", "-E", "-S"):
                    if argv:
                        argv.pop(0)
                if w == "timeout" and argv and not argv[0].startswith("-"):
                    argv.pop(0)
                    break
        if not argv:
            continue
        name = posixpath.basename(argv[0])
        args = argv[1:]
        if name == "cd":
            here = _resolve(args[0], here) if args else None
            continue
        if name == "git":
            sub, k, target = None, 0, here
            while k < len(args):
                a = args[k]
                if a in GIT_GLOBAL_VAL:
                    if a == "-C":
                        target = _resolve(args[k + 1], target) if k + 1 < len(args) else None
                    elif a in ("--git-dir", "--work-tree"):
                        target = None
                    k += 2
                    continue
                if a.startswith("--git-dir=") or a.startswith("--work-tree="):
                    target = None
                if a.startswith("-"):
                    k += 1
                    continue
                sub = a
                break
            rest = args[k + 1:]
            if sub is not None and _git_readonly(sub, rest):
                continue
            effects.append(("git", target))
            why.append("git " + (sub or "?"))
            continue
        if name in READONLY:
            continue
        if name in MUTATORS:
            if name == "sed" and not any(a.startswith("-i") or a.startswith("--in-place") for a in args) \
                    and not any(re.search(r"(^|[^A-Za-z])[wWe]([^A-Za-z]|$)", a) for a in args):
                continue                                 # no in-place edit and no w, W or e command
            if name == "find" and any(a in ("-exec", "-execdir", "-ok", "-okdir") for a in args):
                effects.append(("unknown", None))        # it runs a command on paths it finds
                why.append("find -exec")
                continue
            if name == "find" and not any(a in ("-delete", "-fprint", "-fprint0", "-fprintf", "-fls")
                                          for a in args):
                continue
            if name == "sort" and not any(a == "-o" or a.startswith("-o") or a.startswith("--output")
                                          for a in args):
                continue
            if name == "uniq" and len([a for a in args if not a.startswith("-")]) < 2:
                continue
            if name == "tree" and "-o" not in args:
                continue
            if name == "perl":
                effects.append(("unknown", None))        # perl can write anything
                why.append("perl")
                continue
            pos = []
            for a in args:
                if name == "dd":
                    if a.startswith("of="):
                        pos.append(a[3:])
                elif not a.startswith("-") or a == "-":
                    pos.append(a)
            if name in ("chmod", "chown", "chgrp") and pos:
                pos = pos[1:]                            # the first operand is the mode or owner
            if name == "find":
                pos = [a for a in args if not a.startswith("-") and a not in ("(", ")", "!")][:1] or ["."]
            for a in pos:
                effects.append(("path", _resolve(a, here)))
            if pos:
                why.append(name)
            continue
        effects.append(("unknown", None))
        why.append(name + " (cannot prove it read-only)")
    return {"effects": effects, "why": ", ".join(why) or "read-only"}


def _git_readonly(sub, rest):
    pos = [a for a in rest if not a.startswith("-")]
    if any(a.startswith("--output") for a in rest):
        return False
    if sub in GIT_READONLY:
        return True
    if sub == "branch":
        listing = {"-a", "-r", "-v", "-vv", "--list", "-l", "--show-current", "--all", "--remotes",
                   "--verbose", "--merged", "--no-merged", "--contains", "--no-contains", "--color",
                   "--no-color", "--column", "--no-column"}
        return all(a in listing or a.startswith("--format") or a.startswith("--sort") for a in rest if a.startswith("-")) \
            and (not pos or any(a in ("--list", "-l", "--merged", "--no-merged", "--contains", "--no-contains")
                                for a in rest))
    if sub == "tag":
        return not pos or "-l" in rest or "--list" in rest
    if sub == "stash":
        return bool(rest) and rest[0] in ("list", "show")
    if sub == "remote":
        return not rest or rest[0] in ("-v", "show", "get-url")
    if sub == "worktree":
        return bool(rest) and rest[0] == "list"
    if sub == "reflog":
        return not rest or rest[0] in ("show", "exists")
    if sub == "config":
        return any(a in ("--get", "--get-all", "--get-regexp", "--list", "-l", "--show-origin", "get", "list")
                   for a in rest) or (len(pos) == 1 and not any(a.startswith("--unset") or
                                                                 a.startswith("--remove") for a in rest))
    if sub == "clean":
        return any(a in ("-n", "--dry-run") or (a.startswith("-") and not a.startswith("--") and "n" in a)
                   for a in rest) and not any(a == "--force" or (a.startswith("-") and not a.startswith("--")
                                                                  and "f" in a) for a in rest)
    if sub == "submodule":
        return bool(rest) and rest[0] == "status"
    if sub == "notes":
        return not rest or rest[0] in ("list", "show")
    return False


def _toplevel(d):
    if not d or not os.path.isdir(d):
        return None
    p = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=d, env=_env(),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.stdout.decode().strip() if p.returncode == 0 else None


def snapshot_targets(command, cwd):
    """The repos the hook would snapshot before this command. Read-only: no git call at all."""
    pl = plan(command, cwd)
    if not pl["effects"]:
        return [], pl["why"]
    home = _toplevel(cwd)
    repos = []
    for kind, val in pl["effects"]:
        if kind == "git":
            t = _toplevel(val) if val else home
        elif kind == "path" and val is not None:
            hr = os.path.realpath(home) if home else None
            t = home if hr and (val == hr or val.startswith(hr + os.sep)) else None
        else:
            t = home
        if t and t not in repos:
            repos.append(t)
    return repos, pl["why"]


def pre_tool_use(command, cwd):
    """The hook path. -> (list of snapshot ids taken, the plan's reason)."""
    repos, why = snapshot_targets(command, cwd)
    return [snapshot(r, label=command) for r in repos], why


def main(argv):
    repo = os.getcwd()
    if len(argv) >= 2 and argv[0] == "--repo":
        repo, argv = argv[1], argv[2:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.split("\n\n")[-2])
        return 0
    try:
        if argv[0] == "list":
            for s in list_snapshots(repo):
                print("%s  %s  %s" % (s["id"], s["commit"][:12], s["label"]))
            return 0
        if argv[0] == "snapshot":
            label = argv[argv.index("--label") + 1] if "--label" in argv else "manual"
            print(snapshot(repo, label=label))
            return 0
        if argv[0] == "restore" and len(argv) >= 2:
            r = restore(repo, argv[1], safety="--no-safety" not in argv)
            print(json.dumps(r, indent=2))
            for h in r["remote_repair"]:
                print("REMOTE NOT RESTORED. To put it back, run: " + h)
            return 0
        if argv[0] == "plan" and len(argv) >= 2:
            print(json.dumps(plan(" ".join(argv[1:]), repo)))
            return 0
    except UndoError as exc:
        print("undo: %s" % exc, file=sys.stderr)
        return 2
    print("usage: python3 undo.py [--repo PATH] list | snapshot | restore <id>|--last [--no-safety] | plan <cmd>",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
