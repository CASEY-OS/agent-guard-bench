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
  - the permission bits of every captured file and of every directory that holds one.
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
change the repo, and if so a snapshot is taken first. Read-only commands cost no git call. The plan skips a snapshot only for a command it can PROVE read-only:
an unknown program, a form it cannot parse, a git -c key or a GIT_* variable that makes git run a program,
xargs operands, or an extraction from an archive all get one.

Files the repo snapshot does not hold (v7). When the plan names a path OUTSIDE the repo (or the command
runs outside any repo), or an IGNORED path inside it (.env, build/), the hook copies those exact paths
first into <store>/files/<id>/ with a manifest (path, existed or not, type, mode, sha256, size). The repo
snapshot of the same call records that id in meta.json, and `restore` puts those files back too:
deleted ones recreated, bytes and modes put back, files the command created at a target removed. A
files-only snapshot restores with `files restore --last`. Bounded at 200 MB and 20,000 entries per
command (AGENT_GUARD_FILES_MAX_BYTES, AGENT_GUARD_FILES_MAX); over that a target is skipped and said so.
It never follows a symlink, and never copies /, $HOME itself or an ancestor of $HOME.

CLI: python3 undo.py [--repo PATH] list | snapshot [--label L] | restore <id> | restore --last
     [--no-safety] | plan <command> | files list | files restore <id> | files restore --last

Blind to: ignored files and files outside the repo that the command does not name (git clean -fdX,
a script that deletes them), a target over the bound, empty directories inside the repo, owner, ACLs,
xattrs and mtimes,
submodule contents and nested repos, skip-worktree and sparse paths, branch reflogs other than the
stash, an in-progress rebase directory, and remote state the local repo never fetched.
"""
import datetime
import hashlib
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
               "REVERT_HEAD", "ORIG_HEAD", "AUTO_MERGE", "SQUASH_MSG")
STATE_DIRS = ("sequencer",)                    # a multi-commit cherry-pick or revert keeps its todo list here
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


def _store_base():
    return os.environ.get("AGENT_GUARD_STORE") or os.path.join(os.path.expanduser("~"), ".local", "state",
                                                                "agent-guard")


def store_dir(top):
    """The copy of this repo's snapshots kept OUTSIDE the repo, so `rm -rf .git` cannot take the
    snapshots with it: $AGENT_GUARD_STORE (default ~/.local/state/agent-guard)/<hash of the path>.git."""
    h = hashlib.sha256(os.path.realpath(top).encode("utf-8", "surrogateescape")).hexdigest()[:20]
    return os.path.join(_store_base(), h + ".git")


def _mirror(top, sid, keep):
    """Copy snapshot sid into the store (a bare repo; a fetch run from the store side, so no hook of
    the user's repo runs). Never fails the snapshot: a store problem is printed and skipped."""
    store = store_dir(top)
    try:
        if not os.path.isdir(store):
            os.makedirs(os.path.dirname(store), exist_ok=True)
            _git(os.path.dirname(store), ["init", "-q", "--bare", store])
        _git(store, ["fetch", "-q", "--no-tags", "--no-write-fetch-head", top,
                     "+%s%s:%s%s" % (REF_NS, sid, REF_NS, sid)])
        have = _snapshots(store)
        if keep > 0 and len(have) > keep:
            script = "".join("delete %s%s\n" % (REF_NS, s) for s, _ in have[:len(have) - keep])
            _git(store, ["update-ref", "--stdin"], input=script.encode())
    except (UndoError, OSError) as exc:
        print("undo: snapshot %s not copied to the store %s: %s" % (sid, store, exc), file=sys.stderr)


def _from_store(repo):
    """If the repo lost its git dir (or was re-initialised) and the store holds its snapshots, make the
    repo a git repo again and fetch every stored snapshot into it. -> True when it imported."""
    top = os.path.realpath(repo)
    store = store_dir(top)
    if not os.path.isdir(store) or not _snapshots(store):
        return False
    p = _git(top, ["rev-parse", "--path-format=absolute", "--show-toplevel"], check=False)
    if p.returncode != 0 or os.path.realpath(p.stdout.decode().strip()) != top:
        _git(top, ["init", "-q", top])
    elif _snapshots(top):
        return False                                    # its own snapshots are there: nothing to import
    _git(top, ["fetch", "-q", "--no-tags", "--no-write-fetch-head", store,
               "+%s*:%s*" % (REF_NS, REF_NS)])
    return True


def snapshot(repo, label="", keep=None, force=False, files=None):
    """Capture the full working state. -> snapshot id (an existing id when nothing changed). files: the id of
    the files snapshot (outside the repo, or ignored) taken by the same hook call; it goes into meta.json,
    and a snapshot that carries one is always stored, so `restore --last` finds it."""
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
        modes, dirs = [], {b"."}
        for ent in listing:
            if not ent:
                continue
            meta, path = ent.split(b"\t", 1)
            if meta.split(b" ")[1] != b"blob":
                continue
            d_ = os.path.dirname(path)
            while d_ and d_ not in dirs:
                dirs.add(d_)
                d_ = os.path.dirname(d_)
            try:
                st = os.lstat(os.path.join(os.fsencode(top), path))
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                modes.append(b"%o %s" % (stat.S_IMODE(st.st_mode), path))
        dirmodes = []                                   # the permission bits of every directory that holds a captured file
        for d_ in sorted(dirs):
            try:
                st = os.lstat(os.path.join(os.fsencode(top), d_))
            except OSError:
                continue
            if stat.S_ISDIR(st.st_mode):
                dirmodes.append(b"%o %s" % (stat.S_IMODE(st.st_mode), d_))
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
        names.append(("dirmodes.bin",))
        blobs.append(b"\0".join(dirmodes))
        if stash_log is not None:
            names.append(("stash-log.bin",))
            blobs.append(stash_log)
        for f in STATE_FILES:
            b = _read(os.path.join(gitdir, f))
            if b is not None:
                names.append(("state", f))
                blobs.append(b)
        for dname in STATE_DIRS:
            ddir = os.path.join(gitdir, dname)
            if os.path.isdir(ddir):
                for f in sorted(os.listdir(ddir)):
                    b = _read(os.path.join(ddir, f))
                    if b is not None:
                        names.append((dname, f))
                        blobs.append(b)
        # the git dir's own files, so a repo whose .git is deleted comes back with its remotes, its
        # core.hooksPath and its installed hooks (they are in no ref or tree)
        for rel, nm in (("config", "config"), (os.path.join("info", "exclude"), "info-exclude")):
            b = _read(os.path.join(common, rel))
            if b is not None:
                names.append(("gitmeta", nm))
                blobs.append(b)
        hdir, hmodes = os.path.join(common, "hooks"), []
        if os.path.isdir(hdir):
            for f in sorted(os.listdir(hdir)):
                full = os.path.join(hdir, f)
                if os.path.isfile(full) and not os.path.islink(full):
                    names.append(("gitmeta-hooks", f))
                    blobs.append(_read(full) or b"")
                    hmodes.append("%o %s" % (stat.S_IMODE(os.lstat(full).st_mode), f))
            names.append(("gitmeta", "hooks-modes"))
            blobs.append("\n".join(hmodes).encode("utf-8", "surrogateescape"))
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
        if existing and not force and not files:
            p = _git(top, ["rev-parse", "-q", "--verify", existing[-1][1] + ":state"], check=False)
            if p.returncode == 0 and p.stdout.decode().strip() == state_tree:
                if not os.path.isdir(store_dir(top)):
                    _mirror(top, existing[-1][0], keep)
                return existing[-1][0]                                   # nothing changed since
        sid = _new_id([s for s, _ in existing])
        meta = {"version": 1, "id": sid, "toplevel": top, "label": label[:500], "warnings": warnings}
        if files:
            meta["files"] = files
        meta = json.dumps(meta, sort_keys=True).encode()
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
        _mirror(top, sid, keep)
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


def _open_dirs(top, rels):
    """Make each directory (a path relative to top, "" is top) readable, writable and searchable for its
    owner, parents first, so restore can delete and write inside it. Their recorded modes go back later."""
    for rel in sorted(set(rels), key=lambda r: (r.count("/"), r)):
        full = os.path.join(top, rel) if rel else top
        try:
            st = os.lstat(full)
            if stat.S_ISDIR(st.st_mode) and (st.st_mode & 0o700) != 0o700:
                os.chmod(full, stat.S_IMODE(st.st_mode) | 0o700)
        except OSError:
            pass


def _open_tree(full):
    """_open_dirs for a directory and everything below it (symlinks are not followed)."""
    try:
        st = os.lstat(full)
        if not stat.S_ISDIR(st.st_mode):
            return
        if (st.st_mode & 0o700) != 0o700:
            os.chmod(full, stat.S_IMODE(st.st_mode) | 0o700)
        for e in os.scandir(full):
            if e.is_dir(follow_symlinks=False):
                _open_tree(e.path)
    except OSError:
        pass


def _apply_modes(top, blob, dirs):
    ents = [e for e in (blob or b"").split(b"\0") if e]
    ents = [(int(e.split(b" ", 1)[0], 8), e.split(b" ", 1)[1]) for e in ents]
    if dirs:
        ents.sort(key=lambda e: -e[1].count(b"/") if e[1] != b"." else 1)    # children first, then parents, top last
    for m, path in ents:
        full = os.path.join(os.fsencode(top), path)
        if dirs:
            ok = os.path.isdir(full) and not os.path.islink(full)
        else:
            ok = os.path.isfile(full) and not os.path.islink(full)
        if ok:
            try:
                os.chmod(full, m)
            except OSError:
                pass


def restore(repo, sid, safety=True):
    """Put the worktree, index, local refs, HEAD, stash list and state files back to snapshot sid.
    refs/remotes are left alone; the repair push for each moved one is returned, never run. If the repo
    lost its git dir (rm -rf .git, or rm then git init), the snapshots come back from the store first, and
    then refs/remotes are restored too: the remote did not move, only the local record of it was lost."""
    rebuilt = _from_store(repo)
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
    # the files snapshot the same hook call took (outside the repo, or ignored): its safety copy goes first,
    # linked from the repo's pre-restore snapshot, so undoing this restore puts both back
    fid = meta.get("files")
    fman = _files_manifest(fid) if fid else None
    if fid and fman is None:
        print("undo: files snapshot %s is no longer kept in %s; the files outside the repo and the ignored files "
              "it named are NOT restored" % (fid, files_dir()), file=sys.stderr)
    fsafe = None
    if safety and fman:
        fsafe = files_snapshot(_manifest_targets(fman), label="pre-restore of files " + fid, repo=top, protect=fid)
    safety_id = snapshot(top, label="pre-restore of " + sid, files=fsafe) if safety else None
    # 1. worktree: delete what the snapshot did not have, then write every snapshot file
    wtree = _out(top, ["rev-parse", st + "/worktree"])
    target = {}
    for ent in _git(top, ["ls-tree", "-r", "-z", "--full-tree", wtree]).stdout.split(b"\0"):
        if ent:
            meta_, path = ent.split(b"\t", 1)
            target[os.fsdecode(path)] = meta_.split(b" ")[0].decode()
    # a command may have made directories read-only (chmod -R a-w): open every directory restore touches
    tracked = [os.fsdecode(x) for x in _git(top, ["ls-files", "-z", "-c"]).stdout.split(b"\0") if x]
    anc = {""}
    for rel in list(target) + tracked:
        d_ = posixpath.dirname(rel)
        while d_ and d_ not in anc:
            anc.add(d_)
            d_ = posixpath.dirname(d_)
    _open_dirs(top, anc)
    # the ignore rules first: what counts as "ignored" must be judged by the snapshot's .gitignore files, not
    # by the ones the command wrote (echo '*.out' >> .gitignore hides the new result.out until it is undone)
    for rel, mode in target.items():
        if posixpath.basename(rel) == ".gitignore" and mode in ("100644", "100755"):
            full = os.path.join(top, rel)
            try:
                os.makedirs(os.path.dirname(full), exist_ok=True)
                if os.path.lexists(full):
                    os.unlink(full)
                with open(full, "wb") as fh:
                    fh.write(_blob(top, wtree + ":" + rel) or b"")
            except OSError:
                pass                                     # a file is in the way: the general pass below clears it
    for raw in _git(top, ["ls-files", "-z", "-o", "--exclude-standard", "--directory"]).stdout.split(b"\0"):
        if raw.endswith(b"/"):
            _open_tree(os.path.join(top, os.fsdecode(raw)))
    deleted = 0
    for _ in range(4):                                   # a stray .gitignore can hide other strays: look again
        current = _git(top, ["ls-files", "-z", "-c", "-o", "--exclude-standard"]).stdout.split(b"\0")
        ignored = set(_git(top, ["ls-files", "-z", "-c", "-i", "--exclude-standard"]).stdout.split(b"\0"))
        gone = 0
        for raw in current:
            rel = os.fsdecode(raw)
            if not rel or rel.endswith("/") or rel in target or raw in ignored:
                continue                                 # "x/" is a nested repo: never touched
            full = os.path.join(top, rel)
            if os.path.islink(full) or os.path.isfile(full):
                os.unlink(full)
                gone += 1
                _remove_empty_parents(top, full)
        deleted += gone
        if not any(posixpath.basename(os.fsdecode(r)) == ".gitignore" for r in current):
            break
        if not gone:
            break
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
            _open_tree(full)
            shutil.rmtree(full)                          # a directory where a file must be
    tmpdir = tempfile.mkdtemp(prefix="agent-guard-undo-")
    try:
        tenv = _env({"GIT_INDEX_FILE": os.path.join(tmpdir, "index")})
        _git(top, ["read-tree", wtree], env=tenv)
        _git(top, ["checkout-index", "-a", "-f"], env=tenv)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    _apply_modes(top, _blob(top, st + "/modes.bin"), dirs=False)
    _apply_modes(top, _blob(top, st + "/dirmodes.bin"), dirs=True)       # last: a read-only directory is sealed after its files are written
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
        if name not in want and name not in syms and (rebuilt or not name.startswith("refs/remotes/")):
            script.append("option no-deref\ndelete %s\n" % name)
    for name, oid in want.items():
        if rebuilt or not name.startswith("refs/remotes/"):
            script.append("option no-deref\nupdate %s %s\n" % (name, oid))
    if script:
        _git(top, ["update-ref", "--stdin"], input="".join(script).encode("utf-8", "surrogateescape"))
    for name, tgt in syms.items():
        if rebuilt or not name.startswith("refs/remotes/"):
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
    for dname in STATE_DIRS:
        ddir = os.path.join(gitdir, dname)
        if os.path.isdir(ddir):
            shutil.rmtree(ddir, ignore_errors=True)
        if _git(top, ["rev-parse", "-q", "--verify", st + "/" + dname], check=False).returncode == 0:
            os.makedirs(ddir, exist_ok=True)
            for ent in _git(top, ["ls-tree", "-z", st + "/" + dname]).stdout.split(b"\0"):
                if ent:
                    nm = ent.split(b"\t", 1)[1].decode()
                    with open(os.path.join(ddir, nm), "wb") as fh:
                        fh.write(_blob(top, st + "/" + dname + "/" + nm) or b"")
    # the git dir's own files: config, info/exclude and the hooks dir, as the snapshot had them
    for nm, rel in (("config", "config"), ("info-exclude", os.path.join("info", "exclude"))):
        b = _blob(top, st + "/gitmeta/" + nm)
        if b is not None:
            os.makedirs(os.path.dirname(os.path.join(common, rel)), exist_ok=True)
            with open(os.path.join(common, rel), "wb") as fh:
                fh.write(b)
    hm = _blob(top, st + "/gitmeta/hooks-modes")
    if hm is not None:
        hdir = os.path.join(common, "hooks")
        os.makedirs(hdir, exist_ok=True)
        want_h = {}
        for l in hm.decode("utf-8", "surrogateescape").split("\n"):
            if l:
                m_, f = l.split(" ", 1)
                want_h[f] = int(m_, 8)
        for f in os.listdir(hdir):
            full = os.path.join(hdir, f)
            if f not in want_h and os.path.isfile(full) and not os.path.islink(full):
                os.unlink(full)
        for f, m_ in want_h.items():
            full = os.path.join(hdir, f)
            if os.path.islink(full):
                os.unlink(full)
            with open(full, "wb") as fh:
                fh.write(_blob(top, st + "/gitmeta-hooks/" + f) or b"")
            os.chmod(full, m_)
    # 4. refs/remotes describe the remote, which restore never touches. Where one moved since the
    #    snapshot, print the push that would put the remote back. Run it only if the undone command
    #    pushed (a force push, a push --delete). If you fetched someone else's work, do not.
    hints = []
    for name, oid in sorted(want.items()):
        m = re.match(r"^refs/remotes/([^/]+)/(.+)$", name)
        if m and not rebuilt and before_refs.get(name) != oid and m.group(2) != "HEAD":
            r, b = m.group(1), m.group(2)
            if name in before_refs:
                hints.append("git push --force-with-lease=refs/heads/%s:%s %s %s:refs/heads/%s"
                             % (b, before_refs[name], r, oid, b))
            else:
                hints.append("git push %s %s:refs/heads/%s" % (r, oid, b))
    # 5. last, the files outside the repo and the ignored files the command named
    fres = files_restore(fid, safety=False) if fman else None
    return {"restored": sid, "safety_snapshot": safety_id, "files_deleted": deleted,
            "files_written": len(target), "refs": len(want), "remote_repair": hints,
            "rebuilt_from_store": rebuilt, "files": fres, "files_safety_snapshot": fsafe,
            "files_missing": fid if fid and not fman else None}


# ---- files the repo snapshot does not hold: outside every repo, or ignored inside it ----
# A command that names a path outside the repo (rm ../notes.txt, sed -i ~/.bashrc, > /tmp/x) or an ignored
# path inside it (rm .env, rm -rf build) gets those EXACT paths copied first, into the store, beside the
# repo snapshots: <store>/files/<id>/manifest.json and data/<sha256>. Bounded, and never a symlink followed.
FILES_MAX_BYTES_DEFAULT = 200 * 1024 * 1024
FILES_MAX_ENTRIES_DEFAULT = 20000


def files_dir():
    return os.path.join(_store_base(), "files")


def _files_ids():
    d = files_dir()
    try:
        names = os.listdir(d)
    except OSError:
        return []
    return sorted(n for n in names if not n.startswith(".") and os.path.isfile(os.path.join(d, n, "manifest.json")))


def _files_manifest(fid):
    try:
        with open(os.path.join(files_dir(), fid, "manifest.json"), "rb") as fh:
            return json.loads(fh.read().decode("utf-8", "surrogateescape"))
    except (IOError, OSError, ValueError):
        return None


def _manifest_targets(man):
    return [(t["path"], t.get("exclude", [])) for t in man.get("targets", []) if not t.get("skipped")]


def _under(p, root):
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


def _forbidden(path):
    """A target this layer never copies: /, $HOME itself, an ancestor of $HOME, a device path, the store."""
    home = os.path.realpath(os.path.expanduser("~"))
    p = path.rstrip(os.sep) or os.sep
    if p == os.sep:
        return "the filesystem root is never copied"
    if p == home:
        return "$HOME itself is never copied"
    if home.startswith(p + os.sep):
        return "an ancestor of $HOME is never copied"
    if any(_under(p, d) for d in ("/dev", "/proc", "/sys")):
        return "a device or kernel path is never copied"
    if _under(p, os.path.realpath(_store_base())):
        return "the undo store itself is never copied"
    return None


def _ftype(st):
    if stat.S_ISLNK(st.st_mode):
        return "symlink"
    if stat.S_ISDIR(st.st_mode):
        return "dir"
    if stat.S_ISREG(st.st_mode):
        return "file"
    return "other"


def _walk(root, excludes, cap=None):
    """-> [(path, lstat, readable)] for root and everything below it, parents before children. A symlink is
    recorded, never followed; an excluded subtree (the repo itself, the store) is not entered. With cap, it
    stops after cap + 1 entries: the caller only needs to know the target is over the bound."""
    out, stack = [], [root]
    while stack:
        if cap is not None and len(out) > cap:
            break
        p = stack.pop()
        try:
            st = os.lstat(p)
        except OSError:
            continue
        ok = True
        kids = []
        if stat.S_ISDIR(st.st_mode):
            try:
                kids = sorted(os.listdir(p))
            except OSError:
                ok = False
        out.append((p, st, ok))
        for n in reversed(kids):
            c = os.path.join(p, n)
            if not any(_under(c, x) for x in excludes):
                stack.append(c)
    return out


def _copy_in(src, data):
    """Copy one regular file into data/<sha256>, never through a symlink. -> (sha256, size)."""
    h, size = hashlib.sha256(), 0
    part = os.path.join(data, ".part-%d" % os.getpid())
    fd = os.open(src, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as fi, open(part, "wb") as fo:
        while True:
            b = fi.read(1 << 20)
            if not b:
                break
            h.update(b)
            size += len(b)
            fo.write(b)
    d = h.hexdigest()
    dst = os.path.join(data, d)
    if os.path.exists(dst):
        os.unlink(part)
    else:
        os.replace(part, dst)
    return d, size


def _prune_files(keep, protect=None):
    ids = _files_ids()
    if keep > 0 and len(ids) > keep:
        for old in ids[:len(ids) - keep]:
            if old != protect:
                shutil.rmtree(os.path.join(files_dir(), old), ignore_errors=True)


def files_snapshot(targets, label="", repo=None, keep=None, protect=None):
    """Copy each target (an absolute path, with the subtrees to leave out) as it is now. -> files snapshot id,
    or None when there is no target. A target that does not exist is recorded too, so a restore removes what
    the command creates there. Over the bound (AGENT_GUARD_FILES_MAX_BYTES, default 200 MB, and
    AGENT_GUARD_FILES_MAX, default 20,000 entries, for all targets together) a target is skipped: said on
    stderr and recorded in the manifest."""
    if not targets:
        return None
    keep = int(os.environ.get("AGENT_GUARD_UNDO_KEEP", KEEP_DEFAULT)) if keep is None else keep
    max_bytes = int(os.environ.get("AGENT_GUARD_FILES_MAX_BYTES", FILES_MAX_BYTES_DEFAULT))
    max_ents = int(os.environ.get("AGENT_GUARD_FILES_MAX", FILES_MAX_ENTRIES_DEFAULT))
    fdir = files_dir()
    if not os.path.isdir(fdir):
        os.makedirs(fdir, mode=0o700, exist_ok=True)     # the copies can hold secrets (.env): owner only
    tmp = tempfile.mkdtemp(prefix=".tmp-", dir=fdir)
    data = os.path.join(tmp, "data")
    os.makedirs(data)
    store = os.path.realpath(_store_base())
    tlist, entries, notes = [], [], []
    used_bytes = used_ents = 0
    try:
        for ti, (path, excl) in enumerate(targets):
            t = {"path": path, "exclude": sorted(excl), "existed": False, "type": None, "skipped": None,
                 "entries": 0, "bytes": 0}
            tlist.append(t)
            why = _forbidden(path)
            if why:
                t["skipped"] = why
                continue
            try:
                st = os.lstat(path)
            except OSError:
                continue                                   # not there now: a restore removes what appears
            t["existed"], t["type"] = True, _ftype(st)
            walk = _walk(path, list(excl) + [store], cap=max_ents - used_ents)
            n = len(walk)
            b = sum(s.st_size for _, s, _ in walk if stat.S_ISREG(s.st_mode))
            if used_ents + n > max_ents or used_bytes + b > max_bytes:
                t["skipped"] = ("over the bound: %d entries and %d bytes would pass %d entries or %d bytes"
                                % (used_ents + n, used_bytes + b, max_ents, max_bytes))
                continue
            used_ents += n
            used_bytes += b
            t["entries"], t["bytes"] = n, b
            for p, s, readable in walk:
                e = {"path": p, "target": ti, "type": _ftype(s), "mode": "%o" % stat.S_IMODE(s.st_mode)}
                if e["type"] == "symlink":
                    e["link"] = os.readlink(p)
                elif e["type"] == "file":
                    try:
                        e["sha256"], e["size"] = _copy_in(p, data)
                    except OSError as exc:
                        e["unreadable"] = str(exc)[:200]
                elif e["type"] == "dir" and not readable:
                    e["unreadable"] = "cannot list it"
                if e.get("unreadable") or e["type"] == "other":
                    notes.append("%s: %s" % (p, e.get("unreadable") or "not a file, directory or symlink"))
                entries.append(e)
        for t in tlist:
            if t["skipped"]:
                print("undo: NOT copied %s (%s). A restore will not bring it back." % (t["path"], t["skipped"]),
                      file=sys.stderr)
        existing = _files_ids()
        man = {"version": 1, "label": label[:500], "repo": repo, "targets": tlist, "entries": entries,
               "notes": notes, "max_bytes": max_bytes, "max_entries": max_ents}
        while True:
            sid = _new_id(existing)
            man["id"] = sid
            with open(os.path.join(tmp, "manifest.json"), "wb") as fh:
                fh.write(json.dumps(man, sort_keys=True, indent=1).encode("utf-8", "surrogateescape"))
            try:
                os.rename(tmp, os.path.join(fdir, sid))
                break
            except OSError:
                if not os.path.exists(os.path.join(fdir, sid)):
                    raise
                existing = existing + [sid]                # another hook took this id: take the next one
        tmp = None
        _prune_files(keep, protect)
        return sid
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def _remove_node(p):
    if os.path.isdir(p) and not os.path.islink(p):
        _open_tree(p)
        shutil.rmtree(p)
    else:
        os.unlink(p)


def _same_file(p, sha):
    try:
        st = os.lstat(p)
        if not stat.S_ISREG(st.st_mode):
            return False
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for b in iter(lambda: fh.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest() == sha
    except OSError:
        return False


def files_list():
    out = []
    for fid in _files_ids():
        m = _files_manifest(fid) or {}
        out.append({"id": fid, "repo": m.get("repo"), "label": m.get("label", ""),
                    "targets": [t["path"] for t in m.get("targets", [])],
                    "skipped": [t["path"] for t in m.get("targets", []) if t.get("skipped")]})
    return out


def files_restore(fid, safety=True):
    """Put every target of files snapshot fid back as it was: deleted files and directories recreated,
    overwritten bytes and modes put back, and whatever the command created at a target that did not exist,
    or inside a target directory, removed. A pre-restore copy of the same targets is taken first."""
    ids = _files_ids()
    if fid == "--last":
        if not ids:
            raise UndoError("no files snapshot in %s" % files_dir())
        fid = ids[-1]
    man = _files_manifest(fid) if fid in ids else None
    if man is None:
        raise UndoError("no files snapshot %s in %s" % (fid, files_dir()))
    data = os.path.join(files_dir(), fid, "data")
    safety_id = files_snapshot(_manifest_targets(man), label="pre-restore of files " + fid, repo=man.get("repo"),
                               protect=fid) if safety else None
    by_t = {}
    for e in man.get("entries", []):
        by_t.setdefault(e["target"], []).append(e)
    written = removed = unchanged = 0
    skipped, lost = [], []
    for ti, t in enumerate(man.get("targets", [])):
        p = t["path"]
        if t.get("skipped"):
            skipped.append(p)
            continue
        if not t.get("existed"):
            if os.path.lexists(p):
                _remove_node(p)
                removed += 1
            continue
        ents = by_t.get(ti, [])
        if not ents:
            continue
        excl = list(t.get("exclude", [])) + [os.path.realpath(_store_base())]
        parent = os.path.dirname(p)
        os.makedirs(parent, exist_ok=True)
        pmode = stat.S_IMODE(os.lstat(parent).st_mode)
        if pmode & 0o300 != 0o300:
            os.chmod(parent, pmode | 0o300)            # a read-only parent: opened for the restore, closed after
        try:
            want = {e["path"]: e for e in ents}
            sealed = [e["path"] for e in ents if e["type"] == "dir" and e.get("unreadable")]
            if ents[0]["type"] == "dir":
                if os.path.lexists(p) and (os.path.islink(p) or not os.path.isdir(p)):
                    os.unlink(p)
                os.makedirs(p, exist_ok=True)
                _open_tree(p)
                for cp, cst, _ in reversed(_walk(p, excl + sealed)):     # children first
                    if cp == p:
                        continue
                    e = want.get(cp)
                    if e is None or e["type"] != _ftype(cst):
                        if os.path.lexists(cp):
                            _remove_node(cp)
                            removed += 1
            for e in ents:                                   # parents before children
                ep, kind = e["path"], e["type"]
                if kind == "other" or e.get("unreadable"):
                    if not os.path.lexists(ep):
                        lost.append(ep)
                    continue
                if kind == "dir":
                    if os.path.lexists(ep) and (os.path.islink(ep) or not os.path.isdir(ep)):
                        os.unlink(ep)
                    os.makedirs(ep, exist_ok=True)
                    _open_dirs(ep, [""])
                    continue
                if os.path.isdir(ep) and not os.path.islink(ep):
                    _remove_node(ep)
                if kind == "symlink":
                    if os.path.islink(ep) and os.readlink(ep) == e["link"]:
                        unchanged += 1
                        continue
                    if os.path.lexists(ep):
                        os.unlink(ep)
                    os.symlink(e["link"], ep)
                    written += 1
                    continue
                if _same_file(ep, e["sha256"]):
                    unchanged += 1                           # same bytes: not rewritten, so its mtime stays
                else:
                    part = ep + ".agent-guard-part"
                    shutil.copyfile(os.path.join(data, e["sha256"]), part)
                    os.replace(part, ep)
                    written += 1
            for e in ents:
                if e["type"] == "file" and not e.get("unreadable") and os.path.isfile(e["path"]):
                    os.chmod(e["path"], int(e["mode"], 8))           # each file's mode bits
            for e in sorted((e for e in ents if e["type"] == "dir"), key=lambda e: -e["path"].count(os.sep)):
                if os.path.isdir(e["path"]) and not os.path.islink(e["path"]):
                    os.chmod(e["path"], int(e["mode"], 8))     # last, children first: a read-only directory is sealed after its files
        finally:
            if pmode & 0o300 != 0o300:
                os.chmod(parent, pmode)
    return {"restored": fid, "safety_snapshot": safety_id, "written": written, "removed": removed,
            "unchanged": unchanged, "skipped": skipped, "not_restorable": lost}


def _ignored_under(top, rels):
    """Ignored paths the repo snapshot does not hold, for these repo-relative targets: the target itself
    when it is ignored, or the ignored files and ignored directories inside a target directory. Two git
    calls at most, and only for a command that names a path inside the repo."""
    exist = [r for r in rels if os.path.lexists(os.path.join(top, r))]
    absent = [r for r in rels if r not in exist]
    found = []
    if exist:
        raw = _git(top, ["--literal-pathspecs", "ls-files", "-z", "-o", "-i", "--exclude-standard", "--directory",
                         "--"] + exist, check=False).stdout
        for x in raw.split(b"\0"):
            if not x:
                continue
            r = os.fsdecode(x).rstrip("/")
            if any(t == "." or r == t or r.startswith(t + "/") for t in exist):
                found.append(os.path.join(top, r))           # the target, or an ignored path inside it
            found += [os.path.join(top, t) for t in exist if t != "." and t.startswith(r + "/")]   # inside an ignored dir: the exact path
    if absent:
        p = _git(top, ["check-ignore", "-z", "--stdin"], input=("\0".join(absent) + "\0").encode("utf-8", "surrogateescape"),
                 check=False)
        found += [os.path.join(top, os.fsdecode(x)) for x in p.stdout.split(b"\0") if x]
    return found


def _file_targets(effects, home):
    """The path effects the repo snapshot does not hold -> [(absolute path, [subtrees left out])]: a path
    outside the repo (or anywhere, when the command runs outside any repo), an ignored path inside it, and
    a directory that holds the repo (the repo is left out of it; its ignored files are added)."""
    vals = []
    for kind, val in effects:
        if kind == "path" and val and val not in vals:
            vals.append(val)
    if not vals:
        return []
    hr = os.path.realpath(home) if home else None
    out, inrepo = [], []
    for v in vals:
        if hr and _under(v, hr):
            rel = os.path.relpath(v, hr)
            if rel.split(os.sep)[0] != ".git":           # the git dir is the repo snapshot's (and the store's)
                inrepo.append(rel.replace(os.sep, "/"))
        elif hr and _under(hr, v):
            out.append((v, [hr]))
            inrepo.append(".")
        else:
            out.append((v, []))
    if inrepo:
        out += [(p, []) for p in _ignored_under(hr, sorted(set(inrepo)))]
    keep, seen = [], set()
    for p, ex in sorted(out, key=lambda x: x[0]):
        if p in seen or any(_under(p, q) and p != q and not any(_under(p, x) for x in qx) for q, qx in keep):
            continue                                     # inside a target already copied whole
        seen.add(p)
        keep.append((p, ex))
    return keep


# ---- the hook path: should this command get a snapshot first? ----
READONLY = {"cat", "head", "tail", "ls", "stat", "file", "wc", "grep", "egrep", "fgrep", "rg", "ag", "diff",
            "cmp", "md5", "md5sum", "shasum", "sha1sum", "sha256sum", "du", "df", "echo", "printf", "test",
            "[", "[[", "]]", "realpath", "readlink", "basename", "dirname", "od", "hexdump", "strings", "cut",
            "true", "false", ":", "pwd", "which", "type", "whoami", "id", "uname", "date", "hostname",
            "jq", "less", "more", "zcat", "gzcat", "bzcat", "xzcat", "nl", "column", "tr", "seq", "sleep", "wait", "export", "unset", "set",
            "local", "declare", "read", "ps", "printenv", "cal", "bc", "expr"}
# wrapper -> (flags, options that take a value). An option not listed makes the plan snapshot.
WRAP = {
    "sudo": (set("EnHSkbABP"), set("ughprCtUTDR")),
    "doas": (set("n"), set("uC")),
    "command": (set("p"), set()),
    "builtin": (set(), set()),
    "exec": (set("cl"), set("a")),
    "nohup": (set(), set()),
    "time": (set("plv"), set("fo")),
    "nice": (set(), set("n") | {"--adjustment"}),
    "ionice": (set("t"), set("cnpPu")),
    "stdbuf": (set(), set("ioe")),
    "timeout": (set("v") | {"--foreground", "--preserve-status", "--verbose"}, set("ks") | {"--kill-after", "--signal"}),
    "xargs": (set("0roptx") | {"--null", "--no-run-if-empty", "--verbose", "--interactive", "--exit", "--open-tty"},
              set("adEILnPs") | {"--arg-file", "--delimiter", "--eof", "--max-lines", "--max-args", "--max-procs",
                                 "--max-chars", "--process-slot-var"}),
    "env": (set(), set()),                               # parsed by hand in _unwrap
}
XARGS_OPTIONAL = set("eil")                              # -e, -i, -l take an attached value only
TAR_VAL = set("fCITXbLNVgKHF")
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\+?=")
ASSIGNERS = {"export", "declare", "typeset", "local", "readonly"}
# a variable that makes a program run (git's pager, editor, ssh, external diff, config injection, the dynamic
# loader, the search path ...). Setting one anywhere in a command gets a snapshot.
DANGER_ENV = re.compile(r"^(GIT_[A-Z0-9_]*|LD_[A-Z_]*|DYLD_[A-Z_]*|PATH|PAGER|MANPAGER|EDITOR|VISUAL|BASH_ENV|ENV|IFS|"
                        r"LESSOPEN|LESSCLOSE|SHELLOPTS|PROMPT_COMMAND|PERL5OPT|PYTHONSTARTUP|NODE_OPTIONS|RUBYOPT)$")
SAFE_ENV = re.compile(r"^GIT_(TERMINAL_PROMPT|OPTIONAL_LOCKS|MERGE_AUTOEDIT|AUTHOR_[A-Z]+|COMMITTER_[A-Z]+|NO_REPLACE_OBJECTS|"
                      r"CONFIG_NOSYSTEM|LITERAL_PATHSPECS|GLOB_PATHSPECS|NOGLOB_PATHSPECS|ICASE_PATHSPECS)$")
SAFE_PAGER = re.compile(r"^(cat|less|more|true|:|)( -[A-Za-z]+)*$")
# git -c keys that cannot make git run a program
SAFE_CFG = re.compile(r"^(color\.[a-z0-9.-]+|core\.(quotepath|abbrev|filemode|precomposeunicode|ignorecase|autocrlf|"
                      r"safecrlf|whitespace)|status\.[a-z]+|advice\.[a-z]+|user\.(name|email)|diff\.(renames|context|"
                      r"algorithm|noprefix|mnemonicprefix|colormoved|ignoresubmodules)|column\.[a-z]+|safe\.directory|"
                      r"init\.defaultbranch|i18n\.[a-z]+)$", re.I)


def _danger(name, val):
    if name.startswith("GIT_TRACE") and val in ("0", "1", "2", "true", "false", ""):
        return False
    if name in ("GIT_PAGER", "PAGER", "MANPAGER", "GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "EDITOR", "VISUAL") \
            and SAFE_PAGER.match(val):
        return False
    return bool(DANGER_ENV.match(name)) and not SAFE_ENV.match(name)


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
        m = re.search(r"(?<!<)<<(?!<)-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", lines[i])
        i += 1
        if m:
            end = next((j for j in range(i, len(lines)) if lines[j].strip() == m.group(1)), None)
            if end is not None:
                i = end + 1
    return "\n".join(out)


def _events(cmd):
    """-> list of ("cmd", words) | ("sep", ";" "&&" "||" "|" "|&" "&") | ("open",) | ("close",)."""
    lx = shlex.shlex(cmd.replace("\\\n", " "), posix=True, punctuation_chars=";&|()<>\n")
    lx.whitespace_split = True
    lx.commenters = ""
    lx.whitespace = " \t\r"
    ev, cur = [], []

    def flush():
        if cur:
            ev.append(("cmd", list(cur)))
            del cur[:]

    def sep(s):
        s = s.replace("\n", ";") if set(s) <= set(";\n") else s.replace("\n", "")
        if s:
            ev.append(("sep", ";" if set(s) <= {";"} else s))

    for t in lx:
        if t and set(t) <= set(";&|()\n"):
            s = ""
            for ch in t:
                if ch in "()":
                    flush()
                    sep(s)
                    s = ""
                    ev.append(("open",) if ch == "(" else ("close",))
                else:
                    s += ch
            flush()
            sep(s)
        else:
            cur.append(t)
    flush()
    return ev


def _literal(w):
    return not re.search(r"[$`*?\[\]{}~]", w)


def _resolve(w, cwd):
    """An absolute path for a literal word, or None when it cannot be known. A leading ~ or ~/ is $HOME, as
    bash expands it (~user is not resolved)."""
    if w == "~" or w.startswith("~/"):
        if not _literal(w[1:]):
            return None
        w = os.path.expanduser("~") + w[1:]
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


def _paths(words, cwds):
    return [("path", _resolve(w, h)) for h in cwds for w in words]


def _opts(a, flags, vals, optatt=(), numeric=False):
    """Consume the leading options of a wrapper command. -> index of the first operand, or None when an
    option is not one the plan knows (then the plan cannot tell what runs)."""
    k = 0
    while k < len(a):
        w = a[k]
        if w == "--":
            return k + 1
        if not w.startswith("-") or w == "-":
            return k
        if w.startswith("--"):
            nm, eq, _ = w.partition("=")
            if nm in vals:
                k += 1 if eq else 2
            elif nm in flags:
                k += 1
            else:
                return None
            continue
        if numeric and re.fullmatch(r"-\d+", w):
            k += 1
            continue
        cl, used = w[1:], 1
        for i, c in enumerate(cl):
            if c in vals:
                used = 2 if i == len(cl) - 1 else 1
                break
            if c in optatt:
                break
            if c not in flags:
                return None
        k += used
    return k if k <= len(a) else None


def _unwrap(argv, cwds):
    """Strip sudo, env, xargs and the like. -> (argv, dyn, cwds) or None when the plan cannot parse a
    wrapper. dyn: the operands come from standard input (xargs). An env -S string is split and run."""
    dyn, local, n = False, cwds, 0
    while argv and n < 30:
        n += 1
        w = argv[0]
        m = ASSIGN.match(w)
        if m:
            if _danger(m.group(1), w[m.end():]):
                return None
            argv = argv[1:]
            continue
        name = posixpath.basename(w)
        if name not in WRAP:
            break
        rest = argv[1:]
        if name == "command" and rest and rest[0] in ("-v", "-V"):
            return [], dyn, local
        if name == "env":
            k, pre = 0, []
            while k < len(rest):
                a = rest[k]
                if a == "--":
                    k += 1
                    break
                if a == "-":
                    k += 1
                    continue
                if not a.startswith("-"):
                    break
                if a.startswith("--"):
                    nm, eq, val = a.partition("=")
                    if nm in ("--ignore-environment", "--null", "--debug"):
                        k += 1
                        continue
                    if nm in ("--unset", "--chdir", "--split-string", "--argv0"):
                        if not eq:
                            if k + 1 >= len(rest):
                                return None
                            val, k = rest[k + 1], k + 2
                        else:
                            k += 1
                        if nm == "--chdir":
                            local = [_resolve(val, h) for h in local]
                        elif nm == "--split-string":
                            pre += shlex.split(val)
                        continue
                    return None
                cl, adv = a[1:], 1
                for i, c in enumerate(cl):
                    if c in "i0v":
                        continue
                    if c in "uCSaP":
                        if i < len(cl) - 1:
                            val = cl[i + 1:]
                        elif k + 1 < len(rest):
                            val, adv = rest[k + 1], 2
                        else:
                            return None
                        if c == "C":
                            local = [_resolve(val, h) for h in local]
                        elif c == "S":
                            pre += shlex.split(val)
                        break
                    return None
                k += adv
            argv = pre + rest[k:]
            continue
        flags, vals = WRAP[name]
        k = _opts(rest, flags, vals, XARGS_OPTIONAL if name == "xargs" else (), numeric=(name == "nice"))
        if k is None:
            return None
        rest = rest[k:]
        if name == "timeout":
            rest = rest[1:]                              # the duration
        if name == "xargs":
            dyn = True
        argv = rest
    return argv, dyn, local


def _safe_cfg(kv):
    return bool(SAFE_CFG.match(kv.split("=", 1)[0]))


def _short_has(args, letters, stop=""):
    """True when some short-option cluster in args holds one of letters (a value-taking letter in
    stop ends the cluster: the rest of it is that option's value)."""
    for a in args:
        if a == "--":
            return False
        if a.startswith("-") and not a.startswith("--") and len(a) > 1:
            for c in a[1:]:
                if c in letters:
                    return True
                if c in stop:
                    break
    return False


def _operands(args):
    pos, end = [], False
    for a in args:
        if end:
            pos.append(a)
        elif a == "--":
            end = True
        elif a.startswith("--target-directory="):
            pos.append(a.split("=", 1)[1])
        elif a and (not a.startswith("-") or a == "-"):
            pos.append(a)
    return pos


def _sed(args):
    """-> ("ro", []) | ("edit", operands) | ("unknown", []). An edit is -i in any cluster (-Ei, -ni, -i.bak,
    --in-place); unknown is a w, W or e command or an s///w, s///e flag, or a script file (-f)."""
    scripts, pos, k, edit, suffix = [], [], 0, False, ""
    while k < len(args):
        a = args[k]
        k += 1
        if a == "--":
            pos += args[k:]
            break
        if a.startswith("--"):
            nm, eq, val = a.partition("=")
            if nm == "--in-place":
                edit = True
                suffix = val
            elif nm == "--file":
                return "unknown", []
            elif nm == "--expression":
                if not eq and k < len(args):
                    val, k = args[k], k + 1
                scripts.append(val)
            elif nm == "--line-length" and not eq:
                k += 1
            continue
        if a.startswith("-") and len(a) > 1:
            cl = a[1:]
            for i, c in enumerate(cl):
                if c == "i":
                    edit = True
                    suffix = cl[i + 1:]
                    break                                # the rest of the cluster is the backup suffix
                if c == "f":
                    return "unknown", []
                if c in "el":
                    val = cl[i + 1:]
                    if not val and k < len(args):
                        val, k = args[k], k + 1
                    if c == "e":
                        scripts.append(val)
                    break
            continue
        pos.append(a)
    if not scripts and pos:
        scripts.append(pos[0])
    sub = r"s(.)((?:\\.|(?!\1).)*)\1((?:\\.|(?!\1).)*)\1([A-Za-z0-9]*)"
    for s_ in scripts:
        for m in re.finditer(sub, s_, re.S):
            if re.search(r"[we]", m.group(4)):
                return "unknown", []
        t = re.sub(sub, "s", s_, flags=re.S)
        t = re.sub(r"y(.)(?:\\.|(?!\1).)*\1(?:\\.|(?!\1).)*\1", "y", t, flags=re.S)
        t = re.sub(r"/(?:\\.|[^/])*/", "/", t)
        if re.search(r"(^|[\s;{}!,$0-9/])[wWe]($|[\s;}]|[^A-Za-z])", t):
            return "unknown", []
    if edit and suffix and ("/" in suffix or "*" in suffix):
        return "unknown", []                             # GNU names the backup by a pattern: a path the plan cannot know
    pos = [p for p in pos if p]
    return ("edit", pos + [p + suffix for p in pos if suffix]) if edit else ("ro", [])   # -i.bak also writes <file>.bak


def _sort_out(args):
    """-> None (it runs a program) | (writes, operands). sort writes with -o in a cluster, --output."""
    out, writes, end = [], False, False
    for a in args:
        if end:
            out.append(a)
        elif a == "--":
            end = True
        elif a.startswith("--"):
            nm, _, val = a.partition("=")
            if nm == "--compress-program":
                return None
            if nm == "--output":
                writes = True
                out.append(val)
        elif a.startswith("-") and len(a) > 1:
            for i, c in enumerate(a[1:]):
                if c == "o":
                    writes = True
                    out.append(a[i + 2:])
                    break
                if c in "kftTS":
                    break
        else:
            out.append(a)
    return writes, [p for p in out if p]


def _find(args, cwds):
    U = [("unknown", None)]
    k, starts = 0, []
    while k < len(args) and (args[k] in ("-H", "-L", "-P") or re.match(r"^-[DO]", args[k])):
        k += 1
    while k < len(args) and not args[k].startswith("-") and args[k] not in ("(", ")", "!", ","):
        starts.append(args[k])
        k += 1
    out, deleting = [], False
    for j in range(k, len(args)):
        a = args[j]
        if a in ("-exec", "-execdir", "-ok", "-okdir"):
            return U
        if a == "-delete":
            deleting = True
        elif a in ("-fprint", "-fprint0", "-fprintf", "-fls") and j + 1 < len(args):
            out.append(args[j + 1])
    if deleting:
        out += starts or ["."]
    return _paths(out, cwds)


def _tar(args, cwds):
    U = [("unknown", None)]
    modes, files, dirs, need, ops = set(), [], [], [], []
    stdout = remove = False
    LONG = {"--create": "c", "--extract": "x", "--get": "x", "--list": "t", "--append": "r", "--update": "u",
            "--concatenate": "A", "--catenate": "A", "--delete": "D", "--diff": "d", "--compare": "d"}
    CODE = ("--to-command", "--checkpoint-action", "--use-compress-program", "--info-script",
            "--new-volume-script", "--rsh-command", "--rmt-command", "--index-file", "--lzop", "--use-compress")
    k = 0
    while k < len(args):
        a = args[k]
        k += 1
        if a == "--":
            ops += args[k:]
            break
        if a.startswith("--"):
            nm, eq, val = a.partition("=")
            if nm in LONG:
                modes.add(LONG[nm])
            elif nm in CODE:
                return U
            elif nm in ("--file", "--directory"):
                if not eq:
                    if k >= len(args):
                        return U
                    val, k = args[k], k + 1
                (files if nm == "--file" else dirs).append(val)
            elif nm == "--to-stdout":
                stdout = True
            elif nm == "--remove-files":
                remove = True
            elif nm in ("--one-top-level",):
                dirs.append(val or ".")
            continue
        first = k == 1 and not a.startswith("-")
        if a.startswith("-") or first:
            cl = a if first else a[1:]
            for i, c in enumerate(cl):
                if c in "cxtruAd":
                    modes.add(c)
                elif c == "O":
                    stdout = True
                elif c in "IF":
                    return U
                elif c in TAR_VAL:
                    if first:
                        need.append(c)                   # old style: the value is a later argument
                        continue
                    val = cl[i + 1:]
                    if not val:
                        if k >= len(args):
                            return U
                        val, k = args[k], k + 1
                    (files if c == "f" else dirs if c == "C" else []).append(val)
                    break
            continue
        if need:
            c = need.pop(0)
            (files if c == "f" else dirs if c == "C" else []).append(a)
        else:
            ops.append(a)
    if need or len(modes) != 1:
        return U
    m = modes.pop()
    if m in ("t", "d"):
        return []
    if m == "x":
        return [] if stdout else _paths(dirs or ["."], cwds)
    out = [f for f in files if f != "-"]
    if m == "c" and remove:
        out += ops
    return _paths(out, cwds)


def _unzip(args, cwds):
    dest = None
    k = 0
    while k < len(args):
        a = args[k]
        k += 1
        if a.startswith("-") and len(a) > 1:
            for i, c in enumerate(a[1:]):
                if c in "ltpvZz":
                    return []
                if c in "dPOI":
                    val = a[i + 2:]
                    if not val and k < len(args):
                        val, k = args[k], k + 1
                    if c == "d":
                        dest = val
                    break
    return _paths([dest or "."], cwds)


def _mut(name, args, cwds, dyn):
    """Effects of a command that can write files. [] means this use of it only reads."""
    U = [("unknown", None)]
    if name == "perl":
        return U                                         # perl can write anything
    if name == "patch":
        return [] if any(a in ("--dry-run", "--check") for a in args) else U   # targets are in the diff
    if name == "sed":
        kind, pos = _sed(args)
        if kind == "ro":
            return []
        return U if dyn or kind == "unknown" else _paths(pos, cwds)
    if name == "find":
        eff = _find(args, cwds)
        return U if dyn and eff else eff
    if name == "sort":
        r = _sort_out(args)
        if r is None:
            return U
        return [] if not r[0] else (U if dyn else _paths(r[1], cwds))
    if name == "uniq":
        pos = _operands(args)
        return [] if len(pos) < 2 else (U if dyn else _paths(pos, cwds))
    if name == "tree":
        return [] if not _short_has(args, "o") and not any(a.startswith("--output") for a in args) else U
    if name == "tar":
        return U if dyn else _tar(args, cwds)
    if name == "unzip":
        return U if dyn else _unzip(args, cwds)
    if name in ("gzip", "gunzip", "bzip2", "xz"):
        if _short_has(args, "clt", "S") or any(a in ("--stdout", "--to-stdout", "--list", "--test") for a in args):
            return []
    if dyn:
        return U                                         # its operands come from standard input
    if name == "dd":
        return _paths([a[3:] for a in args if a.startswith("of=")], cwds)
    pos = _operands(args)
    if name in ("chmod", "chown", "chgrp"):
        ref = any(a.startswith("--reference") for a in args)
        pos, end = [], False
        for a in args:
            if end:
                pos.append(a)
            elif a == "--":
                end = True
            elif a.startswith("--"):
                continue
            elif a.startswith("-") and len(a) > 1 and all(c in "RfvchHLP" for c in a[1:]):
                continue
            else:
                pos.append(a)
        if not ref:
            pos = pos[1:]                                # the first operand is the mode or owner (may start with -)
    if name in ("split", "csplit"):
        pos = pos + ["."]                                # the pieces land in the current directory
    if name in ("cp", "mv", "ln", "install"):
        return _dest_paths(name, args, pos, cwds)
    return _paths(pos, cwds)


def _dest_paths(name, args, pos, cwds):
    """cp, mv, ln and install write their LAST operand, or a name inside it when it is a directory. The
    sources are only read (mv also removes them; an ln source is a link target, not a path here). So a copy
    into ~/bin/ names ~/bin/<file>, not the whole of ~/bin. With -t, or install -d, every operand counts."""
    if name == "install":                                # -m 755, -o root, -g wheel: values, not operands
        pos, k = [], 0
        while k < len(args):
            a = args[k]
            if a.startswith("-") and not a.startswith("--") and len(a) > 1 and a[-1] in "mogBSfM":
                k += 2
                continue
            if not a.startswith("-") or a == "-":
                pos.append(a)
            k += 1
    shorts = "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--") and a != "-")
    if "t" in shorts or any(a.startswith("--target-directory") for a in args) or not pos \
            or (name == "install" and "d" in shorts):
        return _paths(pos, cwds)
    if len(pos) == 1:
        if name != "ln":
            return _paths(pos, cwds)
        dest, srcs = ".", pos                            # ln -s x: the link is ./x
    else:
        dest, srcs = pos[-1], pos[:-1]
    into = "T" not in shorts and "--no-target-directory" not in args
    out = _paths(srcs, cwds) if name == "mv" else []
    for h in cwds:
        d = _resolve(dest, h)
        if into and d and os.path.isdir(d):
            rd = os.path.realpath(d)
            names = [posixpath.basename(x.rstrip("/")) for x in srcs]
            if all(_literal(x) and n not in ("", ".", "..") for x, n in zip(srcs, names)):
                out += [("path", os.path.join(rd, n)) for n in names]
            else:
                out.append(("path", rd))                 # a glob into a directory: the directory itself
        else:
            out.append(("path", d))
    return out


def _ro_unsafe(name, args):
    """A program on the read-only list used in a way that writes or runs a program."""
    if name in ("rg", "ag"):
        return any(a.startswith(("--pre", "--hostname-bin", "--pager")) for a in args)
    if name == "file":
        return _short_has(args, "C")
    if name in ("less", "more"):
        return any(a.startswith(("-o", "-O", "--log-file", "--LOG-FILE")) for a in args)
    return False


def plan(command, cwd):
    """-> {"effects": [...], "why": str}. An effect is ("git", dir), ("path", abs path or None) or
    ("unknown", None). No effects means provably read-only: no snapshot. The rule: a snapshot is skipped
    only for a command the plan can prove read-only. A program it does not know, a form it cannot parse,
    a git setting or an environment variable that makes git run a program, all get a snapshot."""
    effects, why = [], []
    U = ("unknown", None)
    if re.search(r"\$\(|`|<\(|>\(", command):
        return {"effects": [U], "why": "command substitution runs code the plan cannot read"}
    try:
        ev = _events(_strip_heredocs(command))
    except ValueError:
        return {"effects": [U], "why": "quoting the plan cannot parse"}
    cwds, prev, stack, pipe, pend = [cwd], [None], [], False, None

    def settle(sep):
        # a cd takes effect for what follows it, except in a pipeline or in the background; when the cd
        # could fail, what follows may run in either directory, so both are kept
        nonlocal cwds, prev, pend
        if pend is None:
            return
        new, in_pipe = pend
        pend = None
        if in_pipe or sep in ("|", "|&", "&"):
            return
        sure = sep != "||" and all(p and os.path.isdir(p) for p in new)
        nxt = new if (sure or sep == "&&") else cwds + [p for p in new if p not in cwds]
        prev, cwds = cwds, nxt

    for e in ev:
        if e[0] == "sep":
            settle(e[1])
            pipe = e[1] in ("|", "|&")
            continue
        if e[0] == "open":
            settle(";")
            stack.append((cwds, prev))
            pipe = False
            continue
        if e[0] == "close":
            settle(";")
            if stack:
                cwds, prev = stack.pop()
            continue
        seg, argv, redirs, k = e[1], [], [], 0
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
            effects += _paths([tgt], cwds)
            why.append("writes " + tgt)
        while argv:
            if argv[0] in KEYWORDS:
                if argv[0] in ("for", "select", "case"):
                    argv = []
                    break
                argv = argv[1:]
            elif ASSIGN.match(argv[0]):
                m_ = ASSIGN.match(argv[0])
                if _danger(m_.group(1), argv[0][m_.end():]):
                    effects.append(U)
                    why.append("sets " + argv[0].split("=")[0])
                argv = argv[1:]
            else:
                break
        if argv and posixpath.basename(argv[0]) in ASSIGNERS:
            for a in argv[1:]:
                m = ASSIGN.match(a)
                if m and _danger(m.group(1), a[m.end():]):
                    effects.append(U)
                    why.append("exports " + m.group(1))
        un = _unwrap(argv, cwds)
        if un is None:
            effects.append(U)
            why.append("a wrapper the plan cannot parse")
            continue
        argv, dyn, lcwd = un
        if not argv:
            continue
        name = posixpath.basename(argv[0])
        args = argv[1:]
        if name in ("cd", "pushd", "popd"):
            a = [x for x in args if x not in ("-L", "-P", "-e", "-@", "--")]
            if name == "popd" or not a:
                new = [None]
            elif a[0] == "-":
                new = prev
            else:
                new = [_resolve(a[0], h) for h in cwds]
            pend = (new, pipe)
            continue
        if name == "git":
            sub, k, target, unsafe = None, 0, list(lcwd), False
            while k < len(args):
                a = args[k]
                if a == "-C":
                    target = [_resolve(args[k + 1], t) if k + 1 < len(args) else None for t in target]
                    k += 2
                elif a == "-c":
                    unsafe = unsafe or not _safe_cfg(args[k + 1] if k + 1 < len(args) else "")
                    k += 2
                elif a in ("--git-dir", "--work-tree"):
                    target = [None]
                    k += 2
                elif a == "--namespace":
                    k += 2
                elif a == "--config-env":
                    unsafe = True
                    k += 2
                elif a.startswith(("--git-dir=", "--work-tree=")):
                    target = [None]
                    k += 1
                elif a.startswith(("--exec-path", "--config-env=")) or a in ("-p", "--paginate") \
                        or (a.startswith("-c") and not a.startswith("--")):
                    unsafe = True                        # may run a program
                    k += 1
                elif a.startswith("-"):
                    k += 1
                else:
                    sub = a
                    break
            rest = args[k + 1:]
            if sub is not None and not unsafe and _git_readonly(sub, rest):
                continue
            effects += [("git", t) for t in target]
            why.append("git " + (sub or "?") + (" (config that can run a program)" if unsafe else ""))
            continue
        if name in READONLY:
            if _ro_unsafe(name, args):
                effects.append(U)
                why.append(name + " option that writes or runs a program")
            continue
        if name in MUTATORS:
            eff = _mut(name, args, lcwd, dyn)
            effects += eff
            if eff:
                why.append(name)
            continue
        effects.append(U)
        why.append(name + " (cannot prove it read-only)")
    settle(";")
    return {"effects": effects, "why": ", ".join(why) or "read-only"}


def _git_readonly(sub, rest):
    pos = [a for a in rest if not a.startswith("-")]
    if any(a.startswith("--output") for a in rest):
        return False
    if sub == "grep" and any(a.startswith("-O") or a.startswith("--open-files-in-pager") for a in rest):
        return False                                     # runs a pager program
    if sub == "ls-remote" and (any(a.startswith(("--upload-pack", "--exec", "-u")) for a in rest)
                               or any("::" in a for a in pos)):
        return False                                     # runs a program, or an ext:: remote helper
    if sub == "fsck" and any(a.startswith("--lost-found") for a in rest):
        return False
    if sub == "cat-file" and any(a in ("--filters", "--textconv") for a in rest):
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
        if any(a in ("-e", "--edit") for a in rest):
            return False                                 # opens an editor
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


def _repos(effects, home):
    repos = []
    for kind, val in effects:
        if kind == "git":
            t = _toplevel(val) if val else home
        elif kind == "path" and val is not None:
            hr = os.path.realpath(home) if home else None
            t = home if hr and (val == hr or val.startswith(hr + os.sep) or hr.startswith(val.rstrip(os.sep) + os.sep)) else None
        else:
            t = home
        if t and t not in repos:
            repos.append(t)
    return repos


def snapshot_targets(command, cwd):
    """The repos the hook would snapshot before this command. Read-only: no git call at all."""
    pl = plan(command, cwd)
    if not pl["effects"]:
        return [], pl["why"]
    return _repos(pl["effects"], _toplevel(cwd)), pl["why"]


def targets(command, cwd):
    """-> {"repos": [...], "files": [(path, [left out]), ...], "home": repo top or None, "why": str}: what the
    hook copies before this command. Copies nothing. A read-only command costs no git call."""
    pl = plan(command, cwd)
    if not pl["effects"]:
        return {"repos": [], "files": [], "home": None, "why": pl["why"]}
    home = _toplevel(cwd)
    return {"repos": _repos(pl["effects"], home), "files": _file_targets(pl["effects"], home), "home": home,
            "why": pl["why"]}


def pre_tool_use(command, cwd):
    """The hook path. -> (the snapshot ids taken, with the files snapshot as "files:<id>"; the plan's reason).
    The files outside the repo and the ignored files the command names are copied first; the repo snapshot
    of the same call records that copy's id. A command whose every target is outside the repo still gets a
    repo snapshot when it runs inside one, so `restore --last` there brings its files back. Run outside any
    repo, it gets a files-only snapshot (`undo.py files restore --last`)."""
    t = targets(command, cwd)
    repos = t["repos"]
    fid = files_snapshot(t["files"], label=command, repo=t["home"]) if t["files"] else None
    if fid and t["home"] and t["home"] not in repos:
        repos.append(t["home"])
    ids = [snapshot(r, label=command, files=fid) for r in repos]
    return ids + (["files:" + fid] if fid else []), t["why"]


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
        if argv[0] == "files" and len(argv) >= 2 and argv[1] == "list":
            for f in files_list():
                print("%s  %s  %d target(s)%s  %s" % (f["id"], f["repo"] or "(no repo)", len(f["targets"]),
                                                     (", %d skipped" % len(f["skipped"])) if f["skipped"] else "",
                                                     f["label"]))
            return 0
        if argv[0] == "files" and len(argv) >= 3 and argv[1] == "restore":
            print(json.dumps(files_restore(argv[2], safety="--no-safety" not in argv), indent=2))
            return 0
    except UndoError as exc:
        print("undo: %s" % exc, file=sys.stderr)
        if "not inside a git worktree" in str(exc) or "not a git repository" in str(exc):
            print("undo: for a command run outside any repo, run: python3 undo.py files restore --last",
                  file=sys.stderr)
        return 2
    print("usage: python3 undo.py [--repo PATH] list | snapshot | restore <id>|--last [--no-safety] | plan <cmd>\n"
          "       python3 undo.py files list | files restore <id>|--last [--no-safety]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
