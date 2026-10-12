#!/usr/bin/env python3
"""undo_bench.py: does the undo layer really put things back? One command: python3 undo_bench.py

For each scenario it builds a throwaway repo under one temp dir (commits, a second branch, tags, a
stash, staged, unstaged and untracked changes, ignored files, a local bare remote). It sends the
command through the real hook (guard.py, stdin JSON, with the repo as cwd), which takes the snapshot.
If the guard denies the command, the bench writes it into a script file outside the repo and sends
`bash <script>` instead, the route a guard cannot read (residual res-22). Then it RUNS the command,
inside that repo only, restores with `python3 undo.py restore --last`, and reads the state back by
its own route (os.walk, sha256, lstat, git ls-files -s, git for-each-ref, git stash list). It never
asks undo.py what it restored.

Fully restored means: every non-ignored file's bytes and mode bits, every symlink target, the index
entries with their stages, refs/heads, refs/tags, refs/stash and HEAD, the stash list, the merge
state files, and refs/remotes plus the bare remote's own refs once the printed repair push has run.

Negative controls skip the snapshot (AGENT_GUARD_UNDO=0) and must show the loss. Residual scenarios
show each named limit: the bench asserts the loss happens and says so.

Safety. Every repo lives under one mkdtemp root. Before every command the bench asserts the repo's
real path is under that root and that git's own toplevel is that repo. GIT_CEILING_DIRECTORIES stops
git at the root. Global and system git config are replaced. The root is deleted at the end.
"""
import hashlib
import json
import os
import platform
import random
import shutil
import stat
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "guard.py")
UNDO = os.path.join(HERE, "undo.py")
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="agb-undo-"))
HOME = os.path.join(ROOT, "home")
os.makedirs(HOME)
with open(os.path.join(HOME, "gitconfig"), "w") as fh:
    fh.write("[user]\n\tname = Bench\n\temail = bench@localhost\n[init]\n\tdefaultBranch = main\n"
             "[advice]\n\tdetachedHead = false\n[gc]\n\tauto = 0\n[maintenance]\n\tauto = false\n")
# auto gc and background maintenance off: a pack git writes on its own would be counted as snapshot cost
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k not in ("CLAUDE_PROJECT_DIR",)}
ENV.update({"HOME": HOME, "GIT_CONFIG_GLOBAL": os.path.join(HOME, "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CEILING_DIRECTORIES": ROOT, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0",
            "GIT_EDITOR": "true", "EDITOR": "true"})
os.environ.clear()
os.environ.update(ENV)          # undo.py, imported for the cost section, inherits the pinned config
sys.path.insert(0, HERE)
import undo  # noqa: E402

RUNS = []                        # every destructive command run, with the repo it ran in
JAIL = []                        # set by --holdouts: blind commands run with writes jailed to ROOT, no network


def inside(path):
    rp = os.path.realpath(path)
    assert rp.startswith(ROOT + os.sep), "REFUSED: %s is not under the bench root %s" % (rp, ROOT)
    return rp


def sh(cwd, cmd, check=True, env=None):
    inside(cwd)
    p = subprocess.run(["/bin/bash", "-c", cmd], cwd=cwd, env=env or ENV, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    if check and p.returncode != 0:
        raise RuntimeError("setup failed: %s\n%s" % (cmd, p.stderr.decode()))
    return p


def git(cwd, *args, check=True):
    inside(cwd)
    p = subprocess.run(["git"] + list(args), cwd=cwd, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), p.stderr.decode()))
    return p.stdout


def run_destructive(repo, cmd):
    """The one place a scenario command runs. Path asserted first, every time."""
    rp = inside(repo)
    top = os.path.realpath(git(repo, "rev-parse", "--show-toplevel").decode().strip())
    assert top == rp, "REFUSED: git toplevel %s is not the scenario repo %s" % (top, rp)
    RUNS.append(rp)
    argv = ["/bin/bash", "-c", cmd]
    if JAIL:
        argv = JAIL + argv
    return subprocess.run(argv, cwd=rp, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode


def write(path, data, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data if isinstance(data, bytes) else data.encode())
    if mode is not None:
        os.chmod(path, mode)


def build(name):
    """A repo with history, a second branch, tags, a stash, every kind of change, and a bare remote."""
    base = tempfile.mkdtemp(prefix=name + "-", dir=ROOT)
    remote, repo = os.path.join(base, "remote.git"), os.path.join(base, "repo")
    os.makedirs(os.path.join(base, "steps"))
    git(base, "init", "-q", "--bare", remote)
    git(base, "init", "-q", repo)
    rnd = random.Random(7)
    write(os.path.join(repo, ".gitignore"), "build/\n*.log\n")
    write(os.path.join(repo, "README.md"), "# demo\nalpha beta\n")
    write(os.path.join(repo, "src/app.py"), "print('app')\n")
    write(os.path.join(repo, "src/util.py"), "def util():\n    return 1\n")
    write(os.path.join(repo, "src/lib/deep.py"), "DEEP = True\n")
    write(os.path.join(repo, "docs/old.md"), "old doc\n")
    write(os.path.join(repo, "bin/run.sh"), "#!/bin/sh\necho run\n", 0o755)
    write(os.path.join(repo, "data/blob.bin"), bytes(rnd.getrandbits(8) for _ in range(2048)))
    os.symlink("README.md", os.path.join(repo, "link"))
    git(repo, "add", ".gitignore", "README.md", "src/app.py", "src/util.py", "src/lib/deep.py", "docs/old.md",
        "bin/run.sh", "data/blob.bin", "link")
    git(repo, "commit", "-q", "-m", "C1")
    git(repo, "tag", "light")
    write(os.path.join(repo, "src/app.py"), "print('app v2')\n")
    git(repo, "add", "src/app.py")
    git(repo, "commit", "-q", "-m", "C2")
    git(repo, "tag", "-a", "v1", "-m", "release one")
    write(os.path.join(repo, "src/util.py"), "def util():\n    return 3\n")
    git(repo, "add", "src/util.py")
    git(repo, "commit", "-q", "-m", "C3")
    git(repo, "checkout", "-q", "-b", "other", "HEAD~1")
    write(os.path.join(repo, "other.txt"), "from other\n")
    git(repo, "add", "other.txt")
    git(repo, "commit", "-q", "-m", "O1")
    git(repo, "checkout", "-q", "main")
    git(repo, "remote", "add", "origin", remote)
    git(repo, "push", "-q", "origin", "main", "other")
    git(repo, "fetch", "-q", "origin")
    git(repo, "remote", "set-head", "origin", "main")
    write(os.path.join(repo, "src/lib/deep.py"), "DEEP = 'stashed'\n")
    git(repo, "stash", "push", "-q", "-m", "saved work")
    write(os.path.join(repo, "src/util.py"), "def util():\n    return 4  # staged\n")
    write(os.path.join(repo, "src/new_staged.py"), "NEW = 1\n")
    git(repo, "add", "src/util.py", "src/new_staged.py")
    write(os.path.join(repo, "src/app.py"), "print('app v3 staged')\n")
    git(repo, "add", "src/app.py")
    write(os.path.join(repo, "src/app.py"), "print('app v3 staged')\nprint('and unstaged')\n")
    write(os.path.join(repo, "README.md"), "# demo\nalpha beta\nunstaged line\n")
    os.unlink(os.path.join(repo, "docs/old.md"))
    write(os.path.join(repo, "notes.txt"), "private notes\n", 0o600)
    write(os.path.join(repo, "src/untracked_dir/u.txt"), "untracked\n")
    write(os.path.join(repo, "build/out.o"), b"\x7fELF ignored build output")
    write(os.path.join(repo, "debug.log"), "ignored log\n")
    write(os.path.join(base, "outside.txt"), "outside the repo\n")
    return base, repo, remote


STATE_FILES = ("MERGE_HEAD", "MERGE_MSG", "MERGE_MODE", "CHERRY_PICK_HEAD", "REVERT_HEAD", "ORIG_HEAD")


def capture(repo, remote=None):
    """Read the state back by an independent route: the filesystem and git plumbing."""
    files = {}
    for dp, dns, fns in os.walk(repo):
        rel_dir = os.path.relpath(dp, repo)
        if rel_dir == ".":
            dns[:] = [d for d in dns if d != ".git"]
        for n in list(dns) + fns:
            full = os.path.join(dp, n)
            rel = os.path.normpath(os.path.join(rel_dir, n))
            st = os.lstat(full)
            if stat.S_ISLNK(st.st_mode):
                files[rel] = ("link", os.readlink(full))
            elif stat.S_ISREG(st.st_mode):
                with open(full, "rb") as fh:
                    files[rel] = ("file", hashlib.sha256(fh.read()).hexdigest(), "%o" % stat.S_IMODE(st.st_mode))
    ignored = set(os.fsdecode(x) for x in git(repo, "ls-files", "-z", "-o", "-i", "--exclude-standard").split(b"\0") if x)
    refs = {}
    for l in git(repo, "for-each-ref", "--format=%(refname) %(objectname) %(symref)").decode().splitlines():
        f = l.split(" ")
        if not f[0].startswith("refs/agent-guard/"):
            refs[f[0]] = (f[1], f[2] if len(f) > 2 else "")
    gd = os.path.join(repo, ".git")
    s = {"files": {k: v for k, v in files.items() if k not in ignored},
         "ignored": {k: v for k, v in files.items() if k in ignored},
         "index": git(repo, "ls-files", "-s", "-z").decode(),
         "refs": {k: v for k, v in refs.items() if not k.startswith("refs/remotes/")},
         "remotes": {k: v for k, v in refs.items() if k.startswith("refs/remotes/")},
         "HEAD": open(os.path.join(gd, "HEAD")).read(),
         "stash": git(repo, "stash", "list", "--format=%H %gd %gs").decode(),
         "state": {f: (open(os.path.join(gd, f), "rb").read() if os.path.exists(os.path.join(gd, f)) else None)
                   for f in STATE_FILES}}
    if remote:
        s["bare"] = git(remote, "for-each-ref", "--format=%(refname) %(objectname)").decode()
    return s


def raw_user_state(repo):
    """Bytes a snapshot must never change: the index file, HEAD, packed refs, the stash reflog."""
    gd = os.path.join(repo, ".git")
    out = {}
    for f in ("index", "HEAD", "packed-refs", "logs/refs/stash", "refs/stash"):
        p = os.path.join(gd, f)
        out[f] = hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.exists(p) else None
    return out


def diff(a, b, keys=("files", "index", "refs", "HEAD", "stash", "state")):
    out = []
    for k in keys:
        if k not in a and k not in b:
            continue
        if a.get(k) == b.get(k):
            continue
        if isinstance(a.get(k), dict):
            ka, kb = set(a[k]), set(b.get(k) or {})
            for x in sorted(ka - kb):
                out.append("%s: lost %s" % (k, x))
            for x in sorted(kb - ka):
                out.append("%s: extra %s" % (k, x))
            for x in sorted(ka & kb):
                if a[k][x] != b[k][x]:
                    out.append("%s: changed %s" % (k, x))
        else:
            out.append("%s differs" % k)
    return out


def hook(repo, command, undo_on=True):
    payload = {"session_id": "bench", "hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": command}, "cwd": repo}
    env = dict(ENV, AGENT_GUARD_ROOT=repo, AGENT_GUARD_UNDO="1" if undo_on else "0")
    p = subprocess.run([sys.executable, GUARD], input=json.dumps(payload).encode(), env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = p.stdout.decode().strip()
    d = json.loads(out) if out else {}
    dec = d.get("hookSpecificOutput", {}).get("permissionDecision", "allow")
    return dec, d


def snap_refs(repo):
    return [l for l in git(repo, "for-each-ref", "--format=%(refname)", "refs/agent-guard/").decode().splitlines() if l]


def setup_conflict(repo):
    git(repo, "stash", "push", "-q", "-m", "dirt before conflict")
    git(repo, "checkout", "-q", "-b", "conflict")
    write(os.path.join(repo, "README.md"), "# demo\nconflict side\n")
    git(repo, "commit", "-q", "-am", "conflict side")
    git(repo, "checkout", "-q", "main")
    write(os.path.join(repo, "README.md"), "# demo\nmain side\n")
    git(repo, "commit", "-q", "-am", "main side")
    git(repo, "merge", "conflict", check=False)
    assert os.path.exists(os.path.join(repo, ".git", "MERGE_HEAD")), "conflict setup did not conflict"


def setup_diverge(repo):
    git(repo, "commit", "-q", "--amend", "--only", "-m", "C3 rewritten")


def setup_empty_dir(repo):
    os.makedirs(os.path.join(repo, "empty_dir"))


def setup_remote_unfetched(repo):
    base = os.path.dirname(repo)
    other = os.path.join(base, "colleague")
    git(base, "clone", "-q", os.path.join(base, "remote.git"), other)
    write(os.path.join(other, "theirs.txt"), "a colleague's commit\n")
    git(other, "add", "theirs.txt")
    git(other, "commit", "-q", "-m", "colleague work")
    git(other, "push", "-q", "origin", "main")
    sha = git(other, "rev-parse", "HEAD").decode().strip()
    shutil.rmtree(other)                      # only the server had it
    setup_diverge(repo)
    return sha


GC = "git reflog expire --expire=now --all && git gc -q --prune=now"
SCENARIOS = [
    ("reset-hard-HEAD~1", "git reset --hard HEAD~1", None),
    ("reset-hard", "git reset --hard", None),
    ("reset-mixed-HEAD~2", "git reset --mixed HEAD~2", None),
    ("reset-soft-HEAD~2", "git reset --soft HEAD~2", None),
    ("clean-fdx", "git clean -fdx", None),
    ("clean-fd", "git clean -fd", None),
    ("checkout-dash-dash-dot", "git checkout -- .", None),
    ("restore-dot", "git restore .", None),
    ("restore-staged-dot", "git restore --staged .", None),
    ("restore-source-src", "git restore --source=HEAD~2 --staged --worktree src", None),
    ("checkout-force-other", "git checkout -f other", None),
    ("switch-discard-other", "git switch --discard-changes other", None),
    ("checkout-other-whole-tree", "git checkout other -- .", None),
    ("branch-D-other", "git branch -D other", None),
    ("branch-f-other", "git branch -f other HEAD~2", None),
    ("stash-push", "git stash push -m wip", None),
    ("stash-drop", "git stash drop", None),
    ("stash-clear", "git stash clear", None),
    ("stash-then-drop", "git stash && git stash drop", None),
    ("commit", "git commit -q -m 'agent commit'", None),
    ("commit-amend", "git commit -q --amend -m amended", None),
    ("stash-then-merge", "git stash -q && git merge -q --no-edit other", None),
    ("rebase-autostash", "git rebase -q --autostash other", None),
    ("rebase-drop-commit", "git rebase -q --autostash --onto HEAD~2 HEAD~1", None),
    ("update-ref-delete", "git update-ref -d refs/heads/other", None),
    ("update-ref-move", "git update-ref refs/heads/main HEAD~2", None),
    ("reset-then-gc", "git reset -q --hard HEAD~2 && " + GC, None),
    ("tag-delete-then-gc", "git tag -d v1 light && " + GC, None),
    ("merge-abort-conflict", "git merge --abort", setup_conflict),
    ("force-push", "git push -q -f origin main", setup_diverge),
    ("push-delete", "git push -q origin --delete other", None),
    ("rm-rf-src", "rm -rf src", None),
    ("rm-files", "rm -f README.md notes.txt bin/run.sh", None),
    ("mv-dir", "mv src lib", None),
    ("mv-out-of-repo", "mv notes.txt ../moved_notes.txt", None),
    ("cp-over", "cp README.md src/app.py", None),
    ("sed-in-place", "sed -i.bak 's/a/X/g' src/app.py README.md", None),
    ("truncate", "truncate -s 0 src/util.py data/blob.bin", None),
    ("redirect-write", "echo junk > README.md && echo more >> notes.txt", None),
    ("tee", "echo x | tee src/app.py src/lib/deep.py", None),
    ("find-delete", "find . -name '*.py' -not -path './.git/*' -delete", None),
    ("git-rm-r-force", "git rm -r -q -f src", None),
    ("git-mv", "git mv README.md README2.md", None),
    ("chmod", "chmod 600 bin/run.sh && chmod 755 notes.txt", None),
    ("file-becomes-dir", "rm src/util.py && mkdir src/util.py && echo x > src/util.py/inner", None),
    ("symlink-becomes-file", "rm link && echo plain > link", None),
    ("dir-becomes-symlink", "rm -rf src/lib && ln -s ../docs src/lib", None),
    ("binary-overwrite", "head -c 512 /dev/zero > data/blob.bin", None),
    ("python-rmtree", "python3 -c \"import shutil; shutil.rmtree('src')\"", None),
]
CONTROLS = ["reset-hard-HEAD~1", "clean-fdx", "rm-rf-src", "branch-D-other", "stash-drop"]
# one-line defects in restore, built at run time under the bench root: the readback must catch each
MUTANTS = [
    ("skips the mode bits", "chmod", "                os.chmod(full, int(m, 8))", "                pass"),
    ("skips the stash reflog", "stash-drop", "            fh.write(stash_log)", "            pass"),
]
RESIDUALS = [
    ("ignored-files", "git clean -fdX", None, "ignored files are not in any snapshot"),
    ("outside-the-repo", "rm -f ../outside.txt", None, "a file outside the repo is not in any snapshot"),
    ("empty-directory", "rmdir empty_dir", setup_empty_dir, "git does not record empty directories"),
    ("remote-only-commit", "git push -q -f origin main", setup_remote_unfetched,
     "a commit that only the remote held is gone once it is overwritten"),
]


def play(name, cmd, setup, undo_on=True, undo_cli=UNDO):
    base, repo, remote = build(name)
    extra = setup(repo) if setup else None
    pre = capture(repo, remote)
    raw_pre = raw_user_state(repo)
    n0 = len(snap_refs(repo))
    direct, _ = hook(repo, cmd, undo_on)
    route, agent_cmd = "direct", cmd
    if direct == "deny":
        script = os.path.join(base, "steps", name + ".sh")
        write(script, "set -e\n" + cmd + "\n")
        agent_cmd = "bash " + script
        dec, _ = hook(repo, agent_cmd, undo_on)
        assert dec != "deny", "the guard denied the script route for " + name
        route = "script"
    taken = len(snap_refs(repo)) - n0
    untouched = capture(repo, remote) == pre and raw_user_state(repo) == raw_pre
    out_pre = outside_state(base)
    rc = run_destructive(repo, agent_cmd)
    outside_changed = outside_state(base) != out_pre
    post = capture(repo, remote)
    damage = diff(pre, post, keys=("files", "index", "refs", "HEAD", "stash", "state", "remotes", "bare"))
    p = subprocess.run([sys.executable, undo_cli, "--repo", repo, "restore", "--last"], env=ENV,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    restore_rc = p.returncode
    hints = []
    if restore_rc == 0:
        hints = json.loads(p.stdout.decode().split("\nREMOTE NOT RESTORED")[0])["remote_repair"]
    for h in hints:                             # the printed repair, run inside the bench root only
        run_destructive(repo, h)
    if hints:
        git(repo, "fetch", "-q", "origin")
    after = capture(repo, remote)
    left = diff(pre, after, keys=("files", "index", "refs", "HEAD", "stash", "state", "remotes", "bare"))
    ignored_lost = diff(pre, after, keys=("ignored",))
    return {"name": name, "command": cmd, "route": route, "guard_direct": direct, "rc": rc,
            "snapshots_taken": taken, "snapshot_left_state_untouched": untouched, "damage": len(damage),
            "damage_sample": damage[:4], "restore_rc": restore_rc, "remote_repair": hints,
            "left": left, "ignored_lost": len(ignored_lost), "outside_changed": outside_changed, "extra": extra,
            "base": base, "repo": repo}


def outside_state(base):
    """Files beside the repo (not the repo, the bare remote or the bench's own steps): name -> sha256."""
    seen = {}
    for dp, dns, fns in os.walk(base):
        if dp == base:
            dns[:] = [d for d in dns if d not in ("repo", "remote.git", "steps")]
        for n in fns:
            full = os.path.join(dp, n)
            with open(full, "rb") as fh:
                seen[os.path.relpath(full, base)] = hashlib.sha256(fh.read()).hexdigest()
    return seen


def plan_cases(outside, repo):
    snap = ["rm -rf src", "rm notes.txt", "mv a b", "cp x y", "sed -i.bak s/a/b/ f", "truncate -s 0 f",
            "echo x > f", "printf x >> f", "echo x | tee f", "find . -name '*.py' -delete",
            "find . -name x -exec rm {} \\;", "find %s -exec rm src/a \\;" % outside, "git commit -m x",
            "git reset --hard", "git checkout main", "git stash", "git branch -D x", "git branch newb",
            "git tag -d v1", "python3 x.py", "make", "npm test", "bash script.sh", "X=$(rm -rf src)",
            "cd src && rm a.py", "git -c a=b commit -m x", "timeout 5 rm f", "sudo rm f", "chmod 600 f",
            "dd if=/dev/zero of=f", "sort -o f f", "sed 's/a/b/w out' f", "git clean -fd", "git fetch",
            "git pull", "git rebase main", "git merge x", "git stash drop", "ln -s a b", "touch new",
            "mkdir d", "ls\nrm -rf src", "if true; then rm f; fi", "for f in a b; do rm $f; done",
            "perl -pi -e s/a/b/ f", "echo hi 2>&1 > out.txt", "cd %s && git -C %s reset --hard" % (outside, repo),
            "git stash pop", "git config core.hooksPath x", "base64 -d -o f in.b64"]
    keep = ["ls -la", "cat f", "git status", "git log --oneline -5", "git diff", "git show HEAD", "git branch",
            "git branch -a", "git stash list", "git clean -n", "git config --get user.name", "grep -r x .",
            "echo hi", "echo hi > /dev/null", "ls 2>&1", "rm -rf %s/x" % outside, "find . -name '*.py'",
            "sed -n 1p f", "sort f", "head -5 f | wc -l", "git tag", "git remote -v", "wc -l f", "pwd",
            "cd src && ls", "cp %s/a %s/b" % (outside, outside), "git rev-parse HEAD", "git ls-files",
            "cd %s && rm -f x" % outside, "git -C %s status" % outside, "echo a && echo b; ls | head",
            "git log --format=%H -n 3", "test -f x && echo yes", "diff a b", "git worktree list"]
    return [(c, True) for c in snap] + [(c, False) for c in keep]


def cost():
    base = tempfile.mkdtemp(prefix="cost-", dir=ROOT)
    repo = os.path.join(base, "repo")
    git(base, "init", "-q", repo)
    rnd = random.Random(11)
    names = []
    for d in range(50):
        for f in range(20):
            rel = "pkg%02d/mod%02d.py" % (d, f)
            write(os.path.join(repo, rel), "".join(rnd.choice("abcdefghij \n") for _ in range(rnd.randint(800, 2400))))
            names.append(rel)
    for k in range(0, 1000, 250):
        git(repo, "add", *names[k:k + 250])
    git(repo, "commit", "-q", "-m", "1000 files")

    def objsize():
        tot = 0
        for dp, _, fns in os.walk(os.path.join(repo, ".git", "objects")):
            for n in fns:
                tot += os.path.getsize(os.path.join(dp, n))
        return tot

    s0 = objsize()
    t = time.perf_counter()
    undo.snapshot(repo, label="cost first")
    first_ms = (time.perf_counter() - t) * 1000
    s1 = objsize()
    noop = []
    for _ in range(10):
        t = time.perf_counter()
        undo.snapshot(repo, label="cost no change")
        noop.append((time.perf_counter() - t) * 1000)
    dirty, sizes = [], []
    for k in range(10):
        for j in range(10):
            write(os.path.join(repo, names[k * 10 + j]), "changed %d %d\n" % (k, j) * 40)
        write(os.path.join(repo, "untracked/new%02d.txt" % k), "new file %d\n" % k * 50)
        b = objsize()
        t = time.perf_counter()
        undo.snapshot(repo, label="cost dirty")
        dirty.append((time.perf_counter() - t) * 1000)
        sizes.append(objsize() - b)
    t = time.perf_counter()
    for _ in range(2000):
        undo.plan("git log --oneline -5 && ls -la src | head", repo)
    plan_us = (time.perf_counter() - t) / 2000 * 1e6
    hook_ro, hook_rw = [], []
    for k in range(5):
        t = time.perf_counter()
        hook(repo, "git status --short")
        hook_ro.append((time.perf_counter() - t) * 1000)
        write(os.path.join(repo, names[500 + k]), "hook change %d\n" % k)
        t = time.perf_counter()
        hook(repo, "rm -f untracked/new0%d.txt" % k)
        hook_rw.append((time.perf_counter() - t) * 1000)
    t = time.perf_counter()
    p = subprocess.run([sys.executable, UNDO, "--repo", repo, "restore", "--last", "--no-safety"], env=ENV,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    restore_ms = (time.perf_counter() - t) * 1000
    if p.returncode != 0:
        raise RuntimeError("cost restore failed: " + p.stderr.decode())
    return {"files": 1000, "objects_bytes_before": s0, "first_snapshot_ms": first_ms,
            "first_snapshot_bytes": s1 - s0, "no_change_ms_median": statistics.median(noop),
            "dirty_snapshot_ms_median": statistics.median(dirty), "dirty_snapshot_bytes_median": statistics.median(sizes),
            "plan_us_read_only": plan_us, "hook_read_only_ms_median": statistics.median(hook_ro),
            "hook_with_snapshot_ms_median": statistics.median(hook_rw), "restore_ms": restore_ms}


def prune_and_dedupe():
    base = tempfile.mkdtemp(prefix="prune-", dir=ROOT)
    repo = os.path.join(base, "repo")
    git(base, "init", "-q", repo)
    write(os.path.join(repo, "a.txt"), "a\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "a")
    a = undo.snapshot(repo, label="one")
    b = undo.snapshot(repo, label="same state")
    write(os.path.join(repo, "a.txt"), "changed\n")
    c = undo.snapshot(repo, label="changed")
    dedupe_ok = a == b and c != a and len(snap_refs(repo)) == 2
    ids = [c]
    for k in range(53):
        write(os.path.join(repo, "a.txt"), "v%d\n" % k)
        ids.append(undo.snapshot(repo, label="v%d" % k))
    left = sorted(r.split("/")[-1] for r in snap_refs(repo))
    prune_ok = len(left) == 50 and left == sorted(ids)[-50:]
    return {"dedupe_ok": dedupe_ok, "prune_ok": prune_ok, "kept": len(left), "made": 55}


def main():
    t_all = time.perf_counter()
    print("Python %s, %s, %s. Bench root (every repo, every destructive command): %s"
          % (platform.python_version(), platform.system(), git(HOME, "--version").decode().strip(), ROOT))
    results, controls, residuals = [], [], []
    for name, cmd, setup in SCENARIOS:
        results.append(play(name, cmd, setup))
    for name in CONTROLS:
        cmd, setup = next((c, s) for n, c, s in SCENARIOS if n == name)
        controls.append(play(name, cmd, setup, undo_on=False))
    for name, cmd, setup, why in RESIDUALS:
        r = play(name, cmd, setup)
        r["why"] = why
        if name == "remote-only-commit":
            r["their_commit_recoverable"] = subprocess.run(
                ["git", "cat-file", "-e", r["extra"]], cwd=r["repo"], env=ENV).returncode == 0
            r["their_commit_on_remote"] = r["extra"] in git(r["base"], "--git-dir", os.path.join(r["base"], "remote.git"),
                                                            "for-each-ref").decode()
        if name == "outside-the-repo":
            r["outside_exists"] = os.path.exists(os.path.join(r["base"], "outside.txt"))
        if name == "empty-directory":
            r["dir_exists"] = os.path.isdir(os.path.join(r["repo"], "empty_dir"))
        residuals.append(r)
    mutants = []
    src = open(UNDO, encoding="utf-8").read()
    for what, scen, old, new in MUTANTS:
        assert src.count(old) == 1, "mutant line not unique: " + old
        mpath = os.path.join(tempfile.mkdtemp(prefix="mutant-", dir=ROOT), "undo.py")
        with open(mpath, "w", encoding="utf-8") as fh:
            fh.write(src.replace(old, new))
        cmd, setup = next((c, s_) for n, c, s_ in SCENARIOS if n == scen)
        r = play(scen, cmd, setup, undo_cli=mpath)
        r["what"] = what
        mutants.append(r)
    pbase = tempfile.mkdtemp(prefix="plan-", dir=ROOT)
    prepo, poutside = os.path.join(pbase, "repo"), os.path.join(pbase, "outside")
    os.makedirs(poutside)
    git(pbase, "init", "-q", prepo)
    cases = plan_cases(poutside, prepo)
    plan_wrong = []
    for c, want in cases:
        got = bool(undo.snapshot_targets(c, prepo)[0])
        if got != want:
            plan_wrong.append(c)
    pd = prune_and_dedupe()
    costs = cost()

    ok_rows = [r for r in results if not r["left"] and r["restore_rc"] == 0]
    no_damage = [r["name"] for r in results if r["damage"] == 0]
    no_snap = [r["name"] for r in results if r["snapshots_taken"] != 1]
    touched = [r["name"] for r in results + residuals if not r["snapshot_left_state_untouched"]]
    ctrl_ok = [c for c in controls if c["snapshots_taken"] == 0 and c["damage"] > 0 and c["left"]
               and c["restore_rc"] != 0]
    res_by = {r["name"]: r for r in residuals}
    residual_ok = {
        "ignored-files": res_by["ignored-files"]["ignored_lost"] > 0 and not res_by["ignored-files"]["left"],
        "outside-the-repo": not res_by["outside-the-repo"]["outside_exists"],
        "empty-directory": not res_by["empty-directory"]["dir_exists"],
        "remote-only-commit": (not res_by["remote-only-commit"]["their_commit_recoverable"]
                               and not res_by["remote-only-commit"]["their_commit_on_remote"]),
    }
    outside_runs = [p for p in RUNS if not p.startswith(ROOT + os.sep)]
    push_rows = [r for r in results if r["remote_repair"]]

    L = ["# Undo benchmark", "",
         "Python %s on %s, %s. Every repo was built under one temp root and deleted after the run. "
         "Every command below ran for real, inside its own throwaway repo." % (
             platform.python_version(), platform.system(), git(HOME, "--version").decode().strip()), "",
         "Route: `direct` means the guard allowed the command, so the hook took the snapshot. `script` means "
         "the guard denied it, so the bench wrote it to a script file outside the repo and sent `bash <script>`, "
         "a route the guard cannot read. Damage counts what changed. Left counts what still differs after "
         "restore (0 is fully restored).", "",
         "| # | scenario | command | route | damage | left after restore | ignored files lost | remote put back by printed push |",
         "|---:|---|---|---|---:|---:|---:|---|"]
    for i, r in enumerate(results, 1):
        L.append("| %d | %s | `%s` | %s | %d | %d | %d | %s |" % (
            i, r["name"], r["command"].replace("|", "\\|"), r["route"], r["damage"], len(r["left"]),
            r["ignored_lost"], "yes" if r["remote_repair"] else "n/a"))
    L += ["", "Fully restored: %d of %d." % (len(ok_rows), len(results)), ""]
    for r in results:
        if r["left"]:
            L.append("- NOT restored %s: %s" % (r["name"], "; ".join(r["left"][:6])))
    L += ["## Negative controls: snapshot skipped (AGENT_GUARD_UNDO=0)", "",
          "| scenario | snapshots taken | damage | still lost after restore --last | restore --last exit |",
          "|---|---:|---:|---:|---:|"]
    for c in controls:
        L.append("| %s | %d | %d | %d | %d |" % (c["name"], c["snapshots_taken"], c["damage"], len(c["left"]),
                                                c["restore_rc"]))
    L += ["", "Controls that show the loss: %d of %d." % (len(ctrl_ok), len(controls)), "",
          "## Residuals: named limits, shown not hidden", "",
          "| residual | command | what happened | as documented |", "|---|---|---|---|"]
    for r in residuals:
        what = {"ignored-files": "%d ignored files lost; everything in scope restored (%d left)"
                                 % (r["ignored_lost"], len(r["left"])),
                "outside-the-repo": "outside file still exists: %s" % r.get("outside_exists"),
                "empty-directory": "empty directory back: %s" % r.get("dir_exists"),
                "remote-only-commit": "their commit recoverable: %s; on the remote: %s"
                                      % (r.get("their_commit_recoverable"), r.get("their_commit_on_remote"))}[r["name"]]
        L.append("| %s | `%s` | %s | %s |" % (r["name"], r["command"], what, "yes" if residual_ok[r["name"]] else "NO"))
    L += ["", "## Mutants: a one-line defect in restore must be caught", "",
          "| mutant | scenario | left after restore | caught |", "|---|---|---:|---|"]
    for m in mutants:
        L.append("| restore %s | %s | %d | %s |" % (m["what"], m["name"], len(m["left"]), "yes" if m["left"] else "NO"))
    L += ["", "## The hook's plan: snapshot or not", "",
          "%d commands that could change the repo and %d that cannot. Wrong: %d%s." % (
              sum(1 for _, w in cases if w), sum(1 for _, w in cases if not w), len(plan_wrong),
              (" (" + "; ".join(plan_wrong) + ")") if plan_wrong else ""), "",
          "## Bound and dedupe", "",
          "Made %d snapshots with the default bound: %d kept, the newest ones (%s). Same state twice gives the "
          "same id, one ref (%s)." % (pd["made"], pd["kept"], "ok" if pd["prune_ok"] else "WRONG",
                                    "ok" if pd["dedupe_ok"] else "WRONG"), "",
          "## Cost (1,000 files, about 1.6 KB each)", "",
          "| measure | value |", "|---|---:|",
          "| first snapshot, clean tree (one run) | %.0f ms, %d bytes added to .git/objects |" % (costs["first_snapshot_ms"], costs["first_snapshot_bytes"]),
          "| snapshot, nothing changed (dedupe) | %.0f ms median |" % costs["no_change_ms_median"],
          "| snapshot, 10 files changed and 1 new | %.0f ms median, %d bytes median |" % (costs["dirty_snapshot_ms_median"], costs["dirty_snapshot_bytes_median"]),
          "| plan() for a read-only command, in-process | %.0f us |" % costs["plan_us_read_only"],
          "| whole hook, read-only command (Python start-up included) | %.0f ms median |" % costs["hook_read_only_ms_median"],
          "| whole hook, command that gets a snapshot | %.0f ms median |" % costs["hook_with_snapshot_ms_median"],
          "| restore --last, CLI | %.0f ms |" % costs["restore_ms"],
          "| .git/objects before any snapshot | %d bytes |" % costs["objects_bytes_before"], ""]
    conds = [
        ("at least 30 in-scope scenarios", len(results) >= 30, "%d" % len(results)),
        ("every in-scope scenario fully restored", len(ok_rows) == len(results), "%d of %d" % (len(ok_rows), len(results))),
        ("every scenario command really changed something", not no_damage, ", ".join(no_damage) or "all did"),
        ("the hook took exactly one snapshot before each command", not no_snap, ", ".join(no_snap) or "all"),
        ("a snapshot left index bytes, HEAD, refs, stash and files untouched", not touched, ", ".join(touched) or "all"),
        ("all 5 negative controls show the loss", len(controls) == 5 and len(ctrl_ok) == 5, "%d of %d" % (len(ctrl_ok), len(controls))),
        ("every residual behaves as documented", all(residual_ok.values()),
         ", ".join(k for k, v in residual_ok.items() if not v) or "all"),
        ("every one-line restore mutant is caught by the readback", all(m["left"] for m in mutants) and len(mutants) == len(MUTANTS),
         "%d of %d" % (sum(1 for m in mutants if m["left"]), len(MUTANTS))),
        ("the plan is right on every planted and clean command", not plan_wrong, "%d wrong" % len(plan_wrong)),
        ("bound keeps the newest 50; dedupe stores a state once", pd["prune_ok"] and pd["dedupe_ok"], "kept %d" % pd["kept"]),
        ("the printed repair push put every pushed remote back", all(not r["left"] for r in push_rows) and len(push_rows) >= 2,
         "%d push scenarios" % len(push_rows)),
        ("every destructive command ran under the bench root", not outside_runs and len(RUNS) > 0,
         "%d runs, %d outside" % (len(RUNS), len(outside_runs))),
    ]
    ok = all(c[1] for c in conds)
    L += ["Blind to: ignored files, files outside the repo, empty directories, owner, ACLs, xattrs and mtimes, "
          "submodule contents and nested repos, skip-worktree and sparse paths, branch reflogs other than the "
          "stash, an in-progress rebase directory, remote state the local repo never fetched, and any change "
          "made by a command the hook never saw (a tool other than Bash, a process started earlier that keeps "
          "writing). Proven on this machine's OS and git only.", "", "## Exit conditions", ""]
    for text, passed, detail in conds:
        L.append("- %s: %s (%s)" % ("PASS" if passed else "FAIL", text, detail))
    L += ["", "Runtime %.0f s." % (time.perf_counter() - t_all), "", "OVERALL: %s" % ("PASS" if ok else "FAIL")]
    md = "\n".join(L) + "\n"
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "UNDO_RESULTS.md"), "w", encoding="utf-8") as fh:
        fh.write(md.replace(ROOT, "<bench root>"))
    slim = lambda rs: [{k: v for k, v in r.items() if k not in ("base", "repo", "extra")} for r in rs]
    with open(os.path.join(HERE, "results", "undo_results.json"), "w", encoding="utf-8") as fh:
        json.dump(json.loads(json.dumps({"scenarios": slim(results), "controls": slim(controls),
                                         "residuals": slim(residuals), "mutants": slim(mutants), "plan_wrong": plan_wrong,
                                         "prune_dedupe": pd, "cost": costs,
                                         "conditions": [{"name": c[0], "pass": c[1], "detail": c[2]} for c in conds],
                                         "overall": "PASS" if ok else "FAIL"}).replace(ROOT, "<bench root>")),
                  fh, indent=2, sort_keys=True)
        fh.write("\n")
    sys.stdout.write(md)
    return 0 if ok else 1


def jail():
    """A write jail for commands nobody here wrote: writes only under ROOT, no network. macOS sandbox-exec,
    else bubblewrap. With neither, blind scenarios are not run at all."""
    tmp = os.path.join(ROOT, "tmp")
    os.makedirs(tmp, exist_ok=True)
    ENV["TMPDIR"] = tmp
    if shutil.which("sandbox-exec"):
        prof = ('(version 1)(allow default)(deny network*)(deny file-write* (require-not (subpath "%s")))'
                '(allow file-write* (literal "/dev/null") (literal "/dev/zero") (literal "/dev/tty"))' % ROOT)
        return ["sandbox-exec", "-p", prof]
    if shutil.which("bwrap"):
        return ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--bind", ROOT, ROOT, "--unshare-net", "--"]
    return []


def holdouts():
    """Every cases/holdout*/undo_cases.jsonl: play each scenario jailed, judge it against its label."""
    j = jail()
    if not j:
        print("UNDO HOLDOUT none run: no write jail (sandbox-exec or bwrap) on this machine")
        return 0
    JAIL[:] = j
    import glob
    out = {}
    for path in sorted(glob.glob(os.path.join(HERE, "cases", "holdout*", "undo_cases.jsonl"))):
        set_name = os.path.basename(os.path.dirname(path))
        rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        res = []
        for row in rows:
            want = str(row.get("expect", "")).lower()
            try:
                r = play("h-" + str(row["id"]), row["command"], None)
                if r["damage"] == 0 and not r["ignored_lost"] and not r["outside_changed"]:
                    verdict = "no-op"            # changed nothing: proves nothing either way
                elif want == "restore":
                    verdict = "restored" if (not r["left"] and r["restore_rc"] == 0) else "NOT-restored"
                else:
                    verdict = ("residual-loss" if r["left"] or r["ignored_lost"] or r["outside_changed"]
                               else "restored-anyway")
                r = {k: v for k, v in r.items() if k not in ("base", "repo", "extra")}
            except Exception as e:               # a guard that denies even the script route, a setup error
                r, verdict = {"error": "%s: %s" % (type(e).__name__, e)}, "error"
            r.update({"id": row["id"], "expect": want, "verdict": verdict, "class": row.get("class")})
            res.append(r)
        restore_rows = [r for r in res if r["expect"] == "restore" and r["verdict"] != "no-op"]
        ok = [r for r in restore_rows if r["verdict"] == "restored"]
        noop = [r["id"] for r in res if r["verdict"] == "no-op"]
        bad = ["%s (%s)" % (r["id"], "; ".join(r.get("left", [])[:3]) or r.get("error", "")) for r in restore_rows
               if r["verdict"] != "restored"]
        print("UNDO HOLDOUT %s: restored fully %d of %d restore scenarios that changed something; no-op %d%s; "
              "residual scenarios %d; NOT restored: %s" % (
                  set_name, len(ok), len(restore_rows), len(noop), (" (" + ", ".join(noop) + ")") if noop else "",
                  sum(1 for r in res if r["expect"] != "restore"), "; ".join(bad) or "none"))
        out[set_name] = res
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "undo_holdouts.json"), "w", encoding="utf-8") as fh:
        json.dump(json.loads(json.dumps(out).replace(ROOT, "<bench root>")), fh, indent=2, sort_keys=True)
        fh.write("\n")
    return 0


if __name__ == "__main__":
    try:
        code = holdouts() if "--holdouts" in sys.argv[1:] else main()
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
        print("Bench root deleted: %s" % (not os.path.exists(ROOT)))
    sys.exit(code)
