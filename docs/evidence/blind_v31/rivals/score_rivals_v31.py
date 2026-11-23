#!/usr/bin/env python3
"""score_rivals_v31.py: score our guard (v30) and two rival guards on blind_v31, by policy. No command is ever run.

    python3 score_rivals_v31.py --approved           ours, dcg, cc-safety-net standard / strict / paranoid (executes the rivals as hooks)
    python3 score_rivals_v31.py --ours-only          ours alone; no rival binary or rival JS is started (the reproduction check)
    python3 score_rivals_v31.py --self-test          proofs on stand-in hooks written at run time; starts no rival

What it does. Every row of docs/evidence/blind_v31/blind_v31_set.jsonl is wrapped as a Claude Code PreToolUse JSON payload
and written to each guard's stdin, as a hook. The guard answers deny, ask or nothing; the command text is never handed to
a shell, so nothing in the set is executed. The set is checked against the sha256 in its LOCK.txt before use. A row is
dangerous when its own label field `expect` is "stop" and safe when it is "allow" (the test tools/score_blind_v31.py uses:
r["expect"] == "stop"); `policy` is A staging, B hooks, C data loss, D delete/home, or none for the safe rows.

The room each hook runs in is built fresh under this folder and deleted at the end: a HOME with files in every folder a
delete rule looks at (.ssh, .aws, .claude, Documents), and a git repo as the working directory with a committed file, a
tracked file with uncommitted edits, an untracked file, and core.hooksPath set to .githooks. The environment handed to a
guard is built from nothing (no variable is inherited), so this machine's own settings cannot reach a guard.

Guards. ours = guard.py of the bench checkout, sha256 asserted to be v30's (08bf8c61...), AGENT_GUARD_UNDO=0 and
AGENT_GUARD_ROOT=/work/repo (the root the set was written for; bench.py pins the same). dcg = the pinned release binary,
no config file, default packs. cc-safety-net = the pinned npm package, run as `node cc-safety-net.js hook --coding-cli`,
level chosen by CC_SAFETY_NET_LEVEL. Each rival's file hash is checked against RIVAL_PINS before it starts; a mismatch
stops the run with nothing started. A crash or a 30 s timeout counts as allow for a rival and is listed by row id.

Ours and the undo layer. With the undo layer off the hook turns a command it would only allow "on an undo point" into a
deny whose text says "none could be taken here". The README's table counts those as allowed (an undo point is taken in a
repo), so this scorer reports ours two ways: README convention (that fallback deny counted as allow, the count the README
states) and hook-as-run (that fallback deny counted as a stop). Both are printed; neither is hidden.

Blind to: whether the labels are right (it scores against them); the real Claude Code payload (this sends no
permission_mode, transcript_path or session history; cc-safety-net answers deny where a real session in default
permission mode could get ask, and both count as a stop); user or project rule files for a rival (none are present, so
this is each rival's out-of-the-box policy, not a tuned one); policies A to D are ours, a rival never claimed them, so a
rival's miss on a policy it does not define is a measured fact about the set, not a defect in the rival; the 50 rows
that name the pinned /work/repo path (a rival sees a path that does not exist here; a sensitivity pass with that path
rewritten to the real fixture repo is reported separately); whether a rival version newer than the pinned one differs;
and the 8-parallel timing (dcg's 1 s evaluation deadline is raised to 10 s so load cannot change a verdict).
"""
import argparse
import collections
import concurrent.futures as cf
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BENCH = os.path.expanduser("~/agent-guard-bench")
EVIDENCE = os.path.join("docs", "evidence", "blind_v31")
OURS_SHA = "08bf8c61aa7a6462a2f3aadefdc865ccb0d1f47cbf60aebf012581532721f887"   # SCORES.json v30 / SEAL_GUARDS.md
PINNED_ROOT = "/work/repo"
TIMEOUT = 30
POLICIES = ["A", "B", "C", "D"]
POLICY_NAME = {"A": "staging", "B": "hooks", "C": "data loss", "D": "delete/home"}
UNDO_FALLBACK = "none could be taken here"

# What was fetched on 2026-11-23 (RIVALS_PROVENANCE.md). A different file is not run.
RIVAL_PINS = {
    "dcg_binary_sha256": "881953634ec7e040bb6574a02b72f5f6b374e431bb06d528121437ed7de6c57d",
    "ccsn_version": "2.8.3",
    "ccsn_tree_sha256": "80285c1e2abf2e72fbfdc0693da6eb0223a030c791f969586d506c65a06b4ded",
}
BASE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"


def sha256_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def tree_sha256(root):
    """sha256 of the sorted list of 'relative-path file-sha256' lines of every file under root."""
    lines = []
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            lines.append("%s %s" % (os.path.relpath(p, root), sha256_file(p)))
    return hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()


class Refuse(SystemExit):
    pass


def refuse(msg):
    raise Refuse("REFUSED: " + msg)


# ------------------------------------------------------------------ the set
def load_set(bench):
    """-> (rows, set sha256, path). Refuses unless the set's sha256 is the one its LOCK.txt names."""
    ev = os.path.join(os.path.realpath(bench), EVIDENCE)
    sp = os.path.join(ev, "blind_v31_set.jsonl")
    raw = open(sp, "rb").read()
    lock = open(os.path.join(ev, "LOCK.txt"), encoding="utf-8").read().split()
    got = hashlib.sha256(raw).hexdigest()
    if len(lock) < 3 or lock[1] != "sha256" or lock[2] != got:
        refuse("SET DOES NOT MATCH ITS LOCK: %s has sha256 %s, LOCK.txt says %s" % (sp, got, lock[2] if len(lock) > 2 else None))
    rows = [json.loads(l) for l in raw.decode("utf-8").splitlines() if l.strip()]
    bad = [r.get("id") for r in rows if r.get("expect") not in ("stop", "allow")]
    if bad:
        refuse("rows whose label field `expect` is neither stop nor allow: %s" % bad[:5])
    return rows, got, sp


def is_dangerous(row):
    return row["expect"] == "stop"      # the same test as tools/score_blind_v31.py


# ------------------------------------------------------------------ the room
def _git(args, cwd, env):
    p = subprocess.run(["git"] + args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if p.returncode != 0:
        refuse("fixture git %s failed: %s" % (args, p.stderr.decode()[:200]))


def build_room(parent):
    """A fresh HOME and git repo under `parent`. -> dict(root, home, repo, tmp)."""
    root = os.path.realpath(tempfile.mkdtemp(prefix="room-", dir=parent))
    home, repo, tmp = (os.path.join(root, x) for x in ("home", "repo", "tmp"))
    for d in (home, repo, tmp):
        os.makedirs(d)
    for rel, body in {
        ".ssh/id_ed25519": "not a key\n", ".ssh/id_ed25519.pub": "ssh-ed25519 AAAA dummy\n", ".ssh/known_hosts": "example.org ssh-ed25519 AAAA\n",
        ".ssh/config": "Host *\n", ".aws/credentials": "[default]\n", ".claude/settings.json": "{}\n", ".claude/CLAUDE.md": "dummy\n",
        ".config/dummy/conf": "x\n", ".zshrc": "# dummy\n", ".bash_profile": "# dummy\n", "Documents/notes.txt": "dummy\n",
        "Desktop/todo.txt": "dummy\n", ".gitconfig": "[user]\n\tname = fixture\n\temail = fixture@example.invalid\n",
    }.items():
        p = os.path.join(home, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(body)
    env = {"PATH": BASE_PATH, "HOME": home, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.path.join(home, ".gitconfig"),
           "LC_ALL": "en_US.UTF-8"}
    _git(["init", "-q", "-b", "main", "."], repo, env)
    for rel, body in {"README.md": "fixture\n", "src/app.py": "print(1)\n", ".gitignore": "*.log\n",
                      ".githooks/pre-commit": "#!/bin/sh\nexit 0\n"}.items():
        p = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(body)
    _git(["config", "core.hooksPath", ".githooks"], repo, env)
    _git(["add", "README.md", "src/app.py", ".gitignore", ".githooks/pre-commit"], repo, env)
    _git(["commit", "-q", "-m", "fixture"], repo, env)
    open(os.path.join(repo, "README.md"), "a").write("uncommitted edit\n")
    open(os.path.join(repo, "notes.txt"), "w").write("untracked\n")
    return {"root": root, "home": home, "repo": repo, "tmp": tmp}


def guard_env(room, extra=None):
    """The whole environment a guard sees: built from nothing."""
    e = {"PATH": BASE_PATH, "HOME": room["home"], "TMPDIR": room["tmp"], "XDG_CONFIG_HOME": os.path.join(room["home"], ".config"),
         "XDG_STATE_HOME": os.path.join(room["home"], ".local", "state"), "XDG_DATA_HOME": os.path.join(room["home"], ".local", "share"),
         "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.path.join(room["home"], ".gitconfig"), "LC_ALL": "en_US.UTF-8",
         "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1", "NO_COLOR": "1", "TERM": "dumb"}
    e.update(extra or {})
    return e


# ------------------------------------------------------------------ the hook call
def payload(command, cwd):
    return json.dumps({"session_id": "b", "hook_event_name": "PreToolUse", "tool_name": "Bash",
                       "tool_input": {"command": command}, "cwd": cwd})


def run_hook(argv, env, cwd, command, timeout=TIMEOUT):
    """-> dict(kind, rc, secs, reason). kind: deny, ask, allow, undo_fallback (ours only), block_exit2, crash, timeout, unparseable.
    The command is only ever inside the JSON on stdin."""
    t0 = time.time()
    try:
        p = subprocess.run(argv, input=payload(command, cwd).encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           cwd=cwd, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"kind": "timeout", "rc": None, "secs": round(time.time() - t0, 3), "reason": ""}
    except Exception as ex:
        return {"kind": "crash", "rc": None, "secs": round(time.time() - t0, 3), "reason": "%s: %s" % (type(ex).__name__, str(ex)[:120])}
    out = p.stdout.decode("utf-8", "replace").strip()
    err = p.stderr.decode("utf-8", "replace").strip()
    decision, reason, sysmsg = "", "", ""
    for line in out.splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if isinstance(d, dict):
            h = d.get("hookSpecificOutput") or {}
            if h.get("permissionDecision"):
                decision, reason = h.get("permissionDecision"), str(h.get("permissionDecisionReason", ""))
            sysmsg = str(d.get("systemMessage", "")) or sysmsg
    secs = round(time.time() - t0, 3)
    if decision in ("deny", "ask"):
        kind = "undo_fallback" if (decision == "deny" and UNDO_FALLBACK in reason) else decision
        return {"kind": kind, "rc": p.returncode, "secs": secs, "reason": reason[:300]}
    if p.returncode == 2:
        return {"kind": "block_exit2", "rc": 2, "secs": secs, "reason": err[:300]}
    if p.returncode != 0 or "FAIL-OPEN" in sysmsg:
        return {"kind": "crash", "rc": p.returncode, "secs": secs, "reason": (sysmsg or err)[:300]}
    if out and not decision:
        return {"kind": "unparseable" if not sysmsg else "allow", "rc": 0, "secs": secs, "reason": out[:300]}
    return {"kind": "allow", "rc": 0, "secs": secs, "reason": ""}


STOP_KINDS = {"deny", "ask", "block_exit2", "undo_fallback"}     # what the hook-as-run does
# README convention for ours: the fallback deny is "allowed on an undo point"
def stops(kind, convention):
    if kind == "undo_fallback":
        return convention == "hook"
    return kind in STOP_KINDS


SANDBOX_EXEC = "/usr/bin/sandbox-exec"
CANARY_BAD, CANARY_OK = "git reset --hard", "git status"


def contain(argv, room):
    """Wrap a guard's argv so it cannot reach the network or write outside the room (macOS sandbox-exec). Reads stay open."""
    if not os.path.exists(SANDBOX_EXEC):
        refuse("%s is missing: cannot contain a third-party guard (no network, writes only inside the room)" % SANDBOX_EXEC)
    prof = ('(version 1)(allow default)(deny network*)'
            '(deny file-write* (require-not (require-any (subpath "%s") (subpath "/dev"))))' % room["root"])
    return [SANDBOX_EXEC, "-p", prof] + list(argv)


def canary(guards, room, timeout=TIMEOUT):
    """Two rows per guard before the matrix: `git reset --hard` must be stopped and `git status` must be allowed, or the guard is
    not working as invoked (a crash counts as allow, so a wrong command line would otherwise score a quiet 0%).
    -> list of 'name: ...' failures, empty when every guard answers as a guard."""
    bad = []
    for name, g in guards.items():
        env = guard_env(room, g[1])
        argv = contain(g[0], room)
        b = run_hook(argv, env, room["repo"], CANARY_BAD, timeout)
        o = run_hook(argv, env, room["repo"], CANARY_OK, timeout)
        if not (stops(b["kind"], "hook") and o["kind"] == "allow"):
            bad.append("%s: `%s` -> %s %s ; `%s` -> %s %s" % (name, CANARY_BAD, b["kind"], b["reason"][:100], CANARY_OK, o["kind"], o["reason"][:100]))
    return bad


def run_matrix(rows, guards, room, workers, timeout=TIMEOUT, log=print):
    """guards: {name: (argv, env_extra)}. Every guard runs contained. -> {name: [result per row, in row order]}."""
    res = {}
    for name, g in guards.items():
        argv, extra = contain(g[0], room), g[1]
        env = guard_env(room, extra)
        t0 = time.time()
        with cf.ThreadPoolExecutor(workers) as ex:
            res[name] = list(ex.map(lambda r: run_hook(argv, env, room["repo"], r["command"], timeout), rows))
        log("  %-28s %5d rows in %6.1fs" % (name, len(rows), time.time() - t0))
    return res


# ------------------------------------------------------------------ scoring
def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (100 * (c - h) / d, 100 * (c + h) / d)


def tally(rows, results, convention):
    t = collections.Counter({k: 0 for k in ("bad", "tp", "safe", "fp")})
    for p_ in POLICIES:
        t["bad_" + p_] = 0
        t["tp_" + p_] = 0
    for r, v in zip(rows, results):
        s = stops(v["kind"], convention)
        if is_dangerous(r):
            t["bad"] += 1
            t["bad_" + r["policy"]] += 1
            if s:
                t["tp"] += 1
                t["tp_" + r["policy"]] += 1
        else:
            t["safe"] += 1
            t["fp"] += s
    return dict(t)


def fmt_row(name, t):
    lo, hi = wilson(t["tp"], t["bad"])
    flo, fhi = wilson(t["fp"], t["safe"])
    pol = " | ".join("%d/%d" % (t.get("tp_" + p, 0), t.get("bad_" + p, 0)) for p in POLICIES)
    return "| %s | %s of %s (%.1f%%, %.1f to %.1f) | %s | %d of %s (%.1f%%, %.1f to %.1f) |" % (
        name, format(t["tp"], ","), format(t["bad"], ","), 100.0 * t["tp"] / t["bad"], lo, hi, pol,
        t["fp"], format(t["safe"], ","), 100.0 * t["fp"] / t["safe"], flo, fhi)


TABLE_HEAD = ("| guard | dangerous stopped (Wilson 95%) | A staging | B hooks | C data loss | D delete/home | safe wrongly stopped (Wilson 95%) |\n"
              "|---|---|---:|---:|---:|---:|---|")


def odd_rows(rows, results):
    """Crash, timeout, unparseable and exit-2 rows, by id."""
    out = collections.defaultdict(list)
    for r, v in zip(rows, results):
        if v["kind"] in ("crash", "timeout", "unparseable", "block_exit2"):
            out[v["kind"]].append(r["id"])
    return dict(out)


def ours_vs_record(rows, results, bench):
    """Compare ours (hook route) row by row with the stored per-row record res_v30.json, as tools/score_blind_v31.py does.
    DENY must be a hook deny with the same rule name; allow must be allow. UNDO (allowed only on an undo point, record made
    with no cwd) must be the fallback deny OR a plain allow: given a real cwd the guard can read a script the command names
    (or finds it absent) and then allows outright, which is the same under the README convention; those rows are returned
    separately as `soft` so the difference is counted, not hidden.
    -> (n compared, ids that differ, ids the record calls UNDO that the hook allowed outright)."""
    rec = json.load(open(os.path.join(os.path.realpath(bench), EVIDENCE, "scores", "res_v30.json"), encoding="utf-8"))
    if rec.get("guard_sha256") != OURS_SHA:
        refuse("res_v30.json names guard %s, not v30" % rec.get("guard_sha256"))
    differ, soft = [], []
    for r, v in zip(rows, results):
        want = rec["verdicts"].get(r["id"])
        if want is None:
            differ.append(r["id"])
            continue
        if want[0] == "DENY":
            rule = v["reason"].split(":", 1)[0] if ":" in v["reason"] else ""
            ok = v["kind"] == "deny" and rule == want[1]
        elif want[0] == "UNDO":
            ok = v["kind"] in ("undo_fallback", "allow")
            if v["kind"] == "allow":
                soft.append(r["id"])
        else:
            ok = v["kind"] == "allow"
        if not ok:
            differ.append(r["id"])
    return len(rows), differ, soft


# ------------------------------------------------------------------ guards
def ours_guard(bench, root):
    gp = os.path.join(os.path.realpath(bench), "guard.py")
    got = sha256_file(gp)
    if got != OURS_SHA:
        refuse("guard.py sha256 is %s, not v30's %s" % (got, OURS_SHA))
    return gp, got, ([sys.executable, gp], {"AGENT_GUARD_UNDO": "0", "AGENT_GUARD_ROOT": root})


def rival_guards(work):
    """-> ({name: (argv, extra)}, provenance dict). Refuses on any hash that is not the pinned one. Starts nothing."""
    dcg = os.path.join(work, "dcg", "dcg")
    ccsn_dir = os.path.join(work, "ccsn", "node_modules", "cc-safety-net")
    node = shutil.which("node", path=BASE_PATH)
    for p in (dcg, ccsn_dir):
        if not os.path.exists(p):
            refuse("missing %s (see RIVALS_PROVENANCE.md)" % p)
    if not node:
        refuse("node not found on %s" % BASE_PATH)
    dsha = sha256_file(dcg)
    if dsha != RIVAL_PINS["dcg_binary_sha256"]:
        refuse("dcg binary sha256 %s is not the pinned %s" % (dsha, RIVAL_PINS["dcg_binary_sha256"]))
    pkg = json.load(open(os.path.join(ccsn_dir, "package.json"), encoding="utf-8"))
    tsha = tree_sha256(ccsn_dir)
    if pkg.get("version") != RIVAL_PINS["ccsn_version"] or tsha != RIVAL_PINS["ccsn_tree_sha256"]:
        refuse("cc-safety-net %s tree %s is not the pinned %s %s" % (pkg.get("version"), tsha, RIVAL_PINS["ccsn_version"], RIVAL_PINS["ccsn_tree_sha256"]))
    ccsn = [node, os.path.join(ccsn_dir, "dist", "bin", "cc-safety-net.js"), "hook", "--coding-cli"]
    hm = {"CC_SAFETY_NET_HOME": "{home}/.cc-safety-net-home"}
    g = {
        "dcg v0.17.1 (default packs)": ([dcg], {"DCG_HOOK_TIMEOUT_MS": "10000", "DCG_NO_UPDATE_CHECK": "1", "DCG_NO_SELF_HEAL": "1"}),
        "cc-safety-net 2.8.3 standard": (ccsn, dict(hm, CC_SAFETY_NET_LEVEL="standard")),
        "cc-safety-net 2.8.3 strict": (ccsn, dict(hm, CC_SAFETY_NET_LEVEL="strict")),
        "cc-safety-net 2.8.3 paranoid": (ccsn, dict(hm, CC_SAFETY_NET_LEVEL="paranoid")),
    }
    return g, {"dcg_binary_sha256": dsha, "ccsn_version": pkg["version"], "ccsn_tree_sha256": tsha, "node": node}


def fill_home(guards, room):
    return {n: (a, {k: v.replace("{home}", room["home"]) for k, v in e.items()}) for n, (a, e) in guards.items()}


# ------------------------------------------------------------------ report
def sensitivity_rows(rows, room):
    sub = []
    for r in rows:
        if PINNED_ROOT in r["command"]:
            r2 = dict(r)
            r2["command"] = r["command"].replace(PINNED_ROOT, room["repo"])
            sub.append(r2)
    return sub


def report(meta, rows, res, convention_names, odd, sens, rec_check):
    L = ["# RESULTS_v31: guards on blind_v31", "",
         "Made %s by score_rivals_v31.py. Set: %s rows, sha256 %s (checked against LOCK.txt before use). Dangerous = label `expect` is stop (%d), safe = allow (%d)." % (
             meta["when"], format(len(rows), ","), meta["set_sha256"], sum(is_dangerous(r) for r in rows), sum(not is_dangerous(r) for r in rows)),
         "No command was run: each row was handed to each guard as text on stdin, as a PreToolUse hook payload. Each guard ran in a fresh git repo with uncommitted changes, with a throwaway HOME holding files in .ssh, .aws, .claude and Documents; the room was deleted afterwards.", "",
         "## Result", "", TABLE_HEAD]
    for name in convention_names:
        label, conv, key = name
        L.append(fmt_row(label, tally(rows, res[key], conv)))
    L += ["", "Ours is shown two ways (see the script header). `README convention` counts a command the guard would only allow on an undo point as allowed, which is how the README's 1,107 and 36 are counted. `hook as run, undo off` counts that fallback deny as a stop, which is what the hook does when no undo point can be taken. Rivals have no such state.", ""]
    if rec_check:
        n, differ, soft = rec_check
        L += ["## Ours against its stored record", "",
              "Ours (hook route) was compared row by row with docs/evidence/blind_v31/scores/res_v30.json (verdict, and rule name on each deny): %s of %s rows agree%s. Of the record's 103 rows marked allowed-on-an-undo-point, %d were allowed outright here (the hook was given a real working directory; the record was made with none), the same under the README convention." % (
                  format(n - len(differ), ","), format(n, ","), "" if not differ else "; DIFFER: " + ", ".join(differ[:20]), len(soft)), ""]
    L += ["## Crashes, timeouts, unparseable output (each counted as allow for a rival)", ""]
    for key, o in odd.items():
        L.append("- %s: %s" % (key, json.dumps(o) if o else "none"))
    L += ["", "## Sensitivity: the %d rows that name /work/repo" % (len(sens["rows"]) if sens else 0), ""]
    if sens:
        L += ["Those commands name the repo root the set was written for. On this machine that path does not exist, so a rival sees an absolute path outside its working directory. Here the same %d rows are re-scored with /work/repo rewritten to the real fixture repo (ours with its root pinned there too). Headline numbers above are NOT these." % len(sens["rows"]), "",
              "| guard | dangerous stopped | safe wrongly stopped |", "|---|---|---|"]
        for label, conv, key in convention_names:
            t = tally(sens["rows"], sens["res"][key], conv)
            L.append("| %s | %d of %d | %d of %d |" % (label, t["tp"], t["bad"], t["fp"], t["safe"]))
        L.append("")
    L += ["## Provenance", "", "See RIVALS_PROVENANCE.md. This run: " + json.dumps(meta["pins"], sort_keys=True), "",
          "Blind to: whether the labels are right; the real Claude Code payload (no permission_mode or transcript, so cc-safety-net answers deny where a live session could get ask; both count as a stop); user or project rule files for a rival (none present: out-of-the-box policy); policies A to D are ours, a rival never claimed them; /work/repo paths (see the sensitivity table); rival versions newer than the pinned ones; load (dcg's 1 s deadline raised to 10 s)."]
    return "\n".join(L) + "\n"


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--approved", action="store_true", help="run the rivals as hooks (third-party code); needs his approval")
    ap.add_argument("--ours-only", action="store_true", help="score ours only; start no rival")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--bench", default=DEFAULT_BENCH)
    ap.add_argument("--work", default=HERE)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true", help="check every pin and print what would be started; start nothing")
    ap.add_argument("--no-write", action="store_true", help="print only; write no RESULTS/JSON")
    a = ap.parse_args(argv[1:])
    if a.self_test:
        return self_test()
    if not (a.approved or a.ours_only or a.dry_run):
        print("Nothing run. --ours-only scores our guard alone. --approved also starts dcg and cc-safety-net as hooks (third-party code, fed text only).")
        return 2
    work = os.path.realpath(a.work)
    bench = os.path.realpath(a.bench)
    rows, set_sha, set_path = load_set(bench)
    gp, gsha, ours = ours_guard(bench, PINNED_ROOT)
    guards = {"ours v30": ours}
    pins = {"guard_sha256": gsha, "set_sha256": set_sha, "python": platform.python_version(), "platform": platform.platform()}
    if not a.ours_only:
        rg, rp = rival_guards(work)   # hash checks only; starts nothing
        guards.update(rg)
        pins.update(rp)
    print("Measured set: %s (%d rows, sha256 %s)" % (set_path, len(rows), set_sha))
    print("Measured guard: %s (sha256 %s)" % (gp, gsha))
    print("Work folder: %s" % work)
    room = build_room(work)
    try:
        print("Room: cwd %s, HOME %s" % (room["repo"], room["home"]))
        guards = fill_home(guards, room)
        if a.dry_run:
            print("DRY RUN: nothing is started. Pins hold. What --approved would start, each under sandbox-exec (no network, writes only inside the room):")
            for k, (argv_, extra_) in guards.items():
                print("  %-30s argv=%s" % (k, " ".join(argv_)))
                print("  %-30s env=%s" % ("", json.dumps(guard_env(room, extra_), sort_keys=True)))
            print("  sandbox profile: %s" % contain(["<guard>"], room)[2])
            print("OVERALL: DRY RUN, nothing scored")
            return 0
        failed_canary = canary(guards, room)
        if failed_canary:
            print("CANARY FAILED: a guard did not answer as a guard, so nothing was scored. A rival may be mis-invoked (a crash would score as a quiet 0%):")
            print("\n".join("  " + f for f in failed_canary))
            print("OVERALL: FAIL (canary)")
            return 3
        print("canary: every guard stops `%s` and allows `%s`" % (CANARY_BAD, CANARY_OK))
        res = run_matrix(rows, guards, room, a.workers)
        names = [("ours v30, README convention (undo fallback counted allowed)", "readme", "ours v30"),
                 ("ours v30, hook as run, undo off (fallback deny counted stopped)", "hook", "ours v30")]
        names += [(k, "hook", k) for k in guards if k != "ours v30"]
        rec = ours_vs_record(rows, res["ours v30"], bench)
        odd = {k: odd_rows(rows, v) for k, v in res.items()}
        # sensitivity: rows naming /work/repo, re-run with the root rewritten to the real fixture repo
        srows = sensitivity_rows(rows, room)
        sg = {k: ((v[0], dict(v[1], AGENT_GUARD_ROOT=room["repo"])) if k == "ours v30" else v) for k, v in guards.items()}
        sres = run_matrix(srows, sg, room, a.workers)
        sens = {"rows": srows, "res": sres}
        # ours' per-name tallies use the same keys
        meta = {"when": time.strftime("%Y-%m-%d %H:%M %Z"), "set_sha256": set_sha, "pins": pins}
        md = report(meta, rows, res, names, odd, sens, rec)
        print()
        print(md)
        n, differ, soft = rec
        unhealthy = {k: sum(len(v) for kk, v in o.items() if kk in ("crash", "timeout", "unparseable")) for k, o in odd.items()}
        for k, c in unhealthy.items():
            print("HEALTH %-28s crash/timeout/unparseable rows: %d of %d%s" % (k, c, len(rows), "  <-- MORE THAN 1%: its score is not trustworthy" if c > 0.01 * len(rows) else ""))
        for label, conv, key in names:
            t = tally(rows, res[key], conv)
            print("%-66s dangerous %d/%d  safe-wrongly-stopped %d/%d" % (label, t["tp"], t["bad"], t["fp"], t["safe"]))
        print("ours against res_v30.json: %d of %d rows agree (verdict and rule name); %d of its 103 undo-point rows were allowed outright here (cwd given)" % (n - len(differ), n, len(soft)))
        if not a.no_write:
            outdir = work
            suffix = "_ours_only" if a.ours_only else ""
            open(os.path.join(outdir, "RESULTS_v31%s.md" % suffix), "w", encoding="utf-8").write(md)
            js = {"meta": meta, "ids": [r["id"] for r in rows], "labels": {r["id"]: [r["expect"], r["policy"]] for r in rows},
                  "results": {k: [[v["kind"], v["reason"][:120]] for v in vs] for k, vs in res.items()},
                  "odd_rows": odd, "tables": {label: tally(rows, res[key], conv) for label, conv, key in names},
                  "ours_vs_record_differ": differ, "ours_undo_rows_allowed_outright": soft,
                  "sensitivity_ids": [r["id"] for r in srows],
                  "sensitivity_results": {k: [[v["kind"], v["reason"][:120]] for v in vs] for k, vs in sres.items()},
                  "rival_right_ours_wrong": {k: [r["id"] for r, v, o in zip(rows, vs, res["ours v30"])
                                                 if stops(v["kind"], "hook") == is_dangerous(r) and stops(o["kind"], "readme") != is_dangerous(r)]
                                             for k, vs in res.items() if k != "ours v30"}}
            json.dump(js, open(os.path.join(outdir, "rival_scores_v31%s.json" % suffix), "w"), indent=1)
            print("wrote RESULTS_v31%s.md and rival_scores_v31%s.json in %s" % (suffix, suffix, outdir))
        rc = 0 if not differ else 1
    finally:
        shutil.rmtree(room["root"], ignore_errors=True)
    print("room deleted: %s" % (not os.path.exists(room["root"])))
    print("OVERALL: %s" % ("PASS (ours reproduces its record)" if rc == 0 else "FAIL (ours differs from its record)"))
    return rc


# ------------------------------------------------------------------ self-test (starts no rival)
STAND_IN = r'''
import json, os, subprocess, sys
mode = sys.argv[1]
p = json.load(sys.stdin)
cmd = p["tool_input"]["command"]
if mode == "env":
    # deny only when the room is the one the scorer promised: cwd is a git repo with uncommitted changes, HOME inside it,
    # nothing inherited from the parent, and a fixture file present
    ok = []
    ok.append(os.path.isdir(os.path.join(p["cwd"], ".git")))
    st = subprocess.run(["git", "status", "--porcelain"], cwd=p["cwd"], capture_output=True, text=True).stdout
    ok.append("README.md" in st and "notes.txt" in st)
    ok.append(os.path.realpath(os.environ["HOME"]).startswith(os.environ["ROOM_PARENT"]))
    ok.append(os.path.isfile(os.path.join(os.environ["HOME"], ".ssh", "id_ed25519")))
    ok.append("LEAK_CANARY" not in os.environ)
    ok.append(os.path.realpath(p["cwd"]) == os.path.realpath(os.getcwd()))
    if all(ok):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "env ok"}}))
    sys.exit(0)
if mode == "deny_reset":
    if "reset --hard" in cmd:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "core.git: reset"}}))
    sys.exit(0)
if mode == "contain_probe":
    import socket
    res = []
    for label, fn in (("inside", lambda: open(os.path.join(os.environ["HOME"], "probe.txt"), "w").write("x")),
                      ("outside", lambda: open(os.environ["PROBE_OUTSIDE"], "w").write("x")),
                      ("net", lambda: socket.create_connection(("127.0.0.1", 9), 2))):
        try:
            fn(); res.append(label + "=ok")
        except PermissionError:
            res.append(label + "=EPERM")
        except OSError as e:
            res.append(label + "=" + type(e).__name__)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": " ".join(res)}}))
    sys.exit(0)
if mode == "allow_all":
    sys.exit(0)
if mode == "deny_danger":      # denies exactly the rows containing DANGER
    if "DANGER" in cmd:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "rule_x: danger"}}))
    sys.exit(0)
if mode == "ask_danger":
    if "DANGER" in cmd:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": "ask"}}))
    sys.exit(0)
if mode == "crash":
    sys.stderr.write("boom\n"); sys.exit(7)
if mode == "garbage":
    print("this is not json"); sys.exit(0)
if mode == "sleep":
    import time; time.sleep(30)
if mode == "fallback":
    if "DANGER" in cmd:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "x: none could be taken here (AGENT_GUARD_UNDO=0)"}}))
    sys.exit(0)
'''


def self_test():
    passed = failed = 0
    lines = []
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="selftest-", dir=HERE))

    def check(name, cond, detail=""):
        nonlocal passed, failed
        passed, failed = passed + bool(cond), failed + (not cond)
        lines.append("%s  %s%s" % ("pass" if cond else "FAIL", name, ("   [" + str(detail) + "]") if (detail and not cond) else ""))

    try:
        # a stand-in bench checkout: a 6-row set with a lock, and the evidence folder the loader expects
        bench = os.path.join(tmp, "bench")
        ev = os.path.join(bench, EVIDENCE)
        os.makedirs(ev)
        mini = [("T1", "echo DANGER one", "stop", "A"), ("T2", "echo DANGER two", "stop", "C"), ("T3", "echo DANGER three", "stop", "D"),
                ("T4", "echo fine one", "allow", "none"), ("T5", "echo fine two", "allow", "none"), ("T6", "echo " + PINNED_ROOT + " fine", "allow", "none")]
        rows_txt = "".join(json.dumps({"id": i, "command": c, "expect": e, "policy": p, "route": "x"}) + "\n" for i, c, e, p in mini)
        open(os.path.join(ev, "blind_v31_set.jsonl"), "w").write(rows_txt)
        mini_sha = hashlib.sha256(rows_txt.encode()).hexdigest()
        lockp = os.path.join(ev, "LOCK.txt")
        open(lockp, "w").write("blind_v31_set.jsonl sha256 %s\nrows 6\n" % mini_sha)
        stand = os.path.join(tmp, "stand_in.py")
        open(stand, "w").write(STAND_IN)

        def hook(mode):
            return [sys.executable, stand, mode]

        # 1. the set and its lock. Clean control, then planted: one byte changed.
        rows, sha, path = load_set(bench)
        check("clean control: a set that matches its lock loads (measured %s)" % path, len(rows) == 6 and sha == mini_sha
              and path == os.path.join(os.path.realpath(bench), EVIDENCE, "blind_v31_set.jsonl"))
        b2 = os.path.join(tmp, "bench_planted")
        shutil.copytree(bench, b2)
        raw = bytearray(open(os.path.join(b2, EVIDENCE, "blind_v31_set.jsonl"), "rb").read())
        raw[raw.index(b"fine") ] = ord("F")
        open(os.path.join(b2, EVIDENCE, "blind_v31_set.jsonl"), "wb").write(bytes(raw))
        try:
            load_set(b2)
            check("planted: one byte of the set changed is refused", False)
        except Refuse as e:
            check("planted: one byte of the set changed is refused", "DOES NOT MATCH ITS LOCK" in str(e))
        # a row whose label is neither stop nor allow is refused (the label field is the contract)
        b3 = os.path.join(tmp, "bench_badlabel")
        shutil.copytree(bench, b3)
        bad_txt = rows_txt.replace('"expect": "allow"', '"expect": "maybe"', 1)
        open(os.path.join(b3, EVIDENCE, "blind_v31_set.jsonl"), "w").write(bad_txt)
        open(os.path.join(b3, EVIDENCE, "LOCK.txt"), "w").write("blind_v31_set.jsonl sha256 %s\n" % hashlib.sha256(bad_txt.encode()).hexdigest())
        try:
            load_set(b3)
            check("planted: a row labelled neither stop nor allow is refused", False)
        except Refuse as e:
            check("planted: a row labelled neither stop nor allow is refused", "neither stop nor allow" in str(e))

        # 2. the room: built fresh, under the folder asked for, dirty repo, populated home; deleted after
        room = build_room(tmp)
        st = subprocess.run(["git", "status", "--porcelain"], cwd=room["repo"], capture_output=True, text=True,
                            env={"PATH": BASE_PATH, "HOME": room["home"]}).stdout
        check("room: the fixture repo is under the folder this test measured (%s)" % tmp, room["root"].startswith(tmp + os.sep))
        check("room: uncommitted edit and untracked file present, hooksPath set", " M README.md" in st and "?? notes.txt" in st
              and subprocess.run(["git", "config", "core.hooksPath"], cwd=room["repo"], capture_output=True, text=True).stdout.strip() == ".githooks")
        check("room: home has files in .ssh, .aws, .claude, Documents", all(
            os.listdir(os.path.join(room["home"], d)) for d in (".ssh", ".aws", ".claude", "Documents")))
        # 2b. the environment seen by a guard is the built one: a stand-in denies only if all of that holds
        os.environ["LEAK_CANARY"] = "1"
        res = run_matrix(rows[:2], {"env": (hook("env"), {"ROOM_PARENT": tmp})}, room, 2, log=lambda *_: None)
        del os.environ["LEAK_CANARY"]
        check("room: a hook sees a dirty git repo cwd, HOME inside the room, and no inherited variable", [v["kind"] for v in res["env"]] == ["deny", "deny"],
              [v for v in res["env"]])
        wrong = build_room(tmp)
        shutil.rmtree(os.path.join(wrong["repo"], ".git"))
        res = run_matrix(rows[:1], {"env": (hook("env"), {"ROOM_PARENT": tmp})}, wrong, 1, log=lambda *_: None)
        check("room: planted, a cwd that is not a git repo is NOT seen as the promised room (stand-in allows)", res["env"][0]["kind"] == "allow")
        shutil.rmtree(wrong["root"])

        # 3. decisions and labels. planted: stand-in that stops DANGER rows; clean control: stand-in that allows everything
        g = {"deny": (hook("deny_danger"), {}), "ask": (hook("ask_danger"), {}), "allow": (hook("allow_all"), {}),
             "crash": (hook("crash"), {}), "garbage": (hook("garbage"), {}), "fallback": (hook("fallback"), {})}
        res = run_matrix(rows, g, room, 3, log=lambda *_: None)
        t = tally(rows, res["deny"], "hook")
        check("planted: a guard that denies the 3 dangerous rows scores 3 of 3, 0 of 3 safe wrongly stopped (by policy A, C, D)",
              (t["tp"], t["bad"], t["fp"], t["safe"], t.get("tp_A"), t.get("tp_C"), t.get("tp_D"), t.get("tp_B", 0)) == (3, 3, 0, 3, 1, 1, 1, 0), t)
        t = tally(rows, res["ask"], "hook")
        check("planted: ask counts as a stop", (t["tp"], t["fp"]) == (3, 0), t)
        t = tally(rows, res["allow"], "hook")
        check("clean control: a guard that allows everything scores 0 of 3, 0 of 3", (t["tp"], t["bad"], t["fp"], t["safe"]) == (0, 3, 0, 3), t)
        t = tally(rows, res["crash"], "hook")
        check("planted: a crashing guard counts as allow and is listed by row id", t["tp"] == 0 and odd_rows(rows, res["crash"]).get("crash") == [r["id"] for r in rows],
              odd_rows(rows, res["crash"]))
        check("planted: unparseable output counts as allow and is listed", tally(rows, res["garbage"], "hook")["tp"] == 0
              and len(odd_rows(rows, res["garbage"]).get("unparseable", [])) == 6)
        check("boundary, outside the blind spot: valid deny JSON is still read as a stop on the same run", tally(rows, res["deny"], "hook")["tp"] == 3)
        tr, th = tally(rows, res["fallback"], "readme"), tally(rows, res["fallback"], "hook")
        check("ours convention: the undo fallback deny is allowed under README convention and stopped as the hook runs it",
              (tr["tp"], th["tp"]) == (0, 3), (tr, th))
        # timeout: a stand-in that sleeps, with a 1 s timeout
        r1 = run_hook(hook("sleep"), guard_env(room), room["repo"], "echo x", timeout=1)
        check("planted: a hook that outlives the timeout counts as allow and is listed as timeout", r1["kind"] == "timeout" and not stops(r1["kind"], "hook"))

        # 4. the record comparison for ours (stand-in record): clean control agrees, planted verdict flip differs
        recdir = os.path.join(ev, "scores")
        os.makedirs(recdir)
        verd = {"T1": ["DENY", "rule_x"], "T2": ["DENY", "rule_x"], "T3": ["DENY", "rule_x"], "T4": ["allow", ""], "T5": ["allow", ""], "T6": ["allow", ""]}
        json.dump({"guard_sha256": OURS_SHA, "verdicts": verd}, open(os.path.join(recdir, "res_v30.json"), "w"))
        n, differ, soft = ours_vs_record(rows, res["deny"], bench)
        check("clean control: a hook that matches the record row for row has 0 differences", n == 6 and differ == [], differ)
        verd["T2"] = ["allow", ""]
        json.dump({"guard_sha256": OURS_SHA, "verdicts": verd}, open(os.path.join(recdir, "res_v30.json"), "w"))
        n, differ, soft = ours_vs_record(rows, res["deny"], bench)
        check("planted: one verdict in the record changed is found as exactly that row", differ == ["T2"], differ)
        verd["T2"] = ["DENY", "rule_y"]
        json.dump({"guard_sha256": OURS_SHA, "verdicts": verd}, open(os.path.join(recdir, "res_v30.json"), "w"))
        n, differ, soft = ours_vs_record(rows, res["deny"], bench)
        check("planted: a rule name that differs is found", differ == ["T2"], differ)
        # UNDO in the record: the fallback deny and a plain allow both agree (the plain allow is counted as soft); a deny does not
        verd["T2"] = ["DENY", "rule_x"]
        verd["T4"] = ["UNDO", ""]
        verd["T5"] = ["UNDO", ""]
        json.dump({"guard_sha256": OURS_SHA, "verdicts": verd}, open(os.path.join(recdir, "res_v30.json"), "w"))
        n, differ, soft = ours_vs_record(rows, res["deny"], bench)
        check("record UNDO and the hook allowed outright: agrees, and is counted as soft (T4, T5)", differ == [] and soft == ["T4", "T5"], (differ, soft))
        n, differ, soft = ours_vs_record(rows, res["fallback"], bench)
        check("record UNDO and the hook gave the fallback deny: agrees (clean control: the T1 to T3 DENY rows now differ, rule name)",
              "T4" not in differ and "T5" not in differ and differ == ["T1", "T2", "T3"], (differ, soft))
        verd["T4"] = ["allow", ""]
        verd["T5"] = ["allow", ""]
        json.dump({"guard_sha256": OURS_SHA, "verdicts": verd}, open(os.path.join(recdir, "res_v30.json"), "w"))
        n, differ, soft = ours_vs_record(rows, {"T": res["deny"]}["T"][:3] + [{"kind": "deny", "reason": "rule_z: x"}] + res["deny"][4:], bench)
        check("planted: the record says allow and the hook denied: found", differ == ["T4"], differ)

        # 5. the hash pins refuse before anything starts
        w = os.path.join(tmp, "work_planted")
        os.makedirs(os.path.join(w, "dcg"))
        os.makedirs(os.path.join(w, "ccsn", "node_modules", "cc-safety-net"))
        open(os.path.join(w, "dcg", "dcg"), "w").write("#!/bin/sh\ntouch %s/SHOULD_NOT_EXIST\n" % tmp)
        os.chmod(os.path.join(w, "dcg", "dcg"), 0o755)
        open(os.path.join(w, "ccsn", "node_modules", "cc-safety-net", "package.json"), "w").write('{"version": "2.8.3"}')
        try:
            rival_guards(w)
            check("planted: a dcg binary that is not the pinned one is refused, and not started", False)
        except Refuse as e:
            check("planted: a dcg binary that is not the pinned one is refused, and not started",
                  "not the pinned" in str(e) and not os.path.exists(os.path.join(tmp, "SHOULD_NOT_EXIST")), str(e)[:100])
        check("planted: a missing rival folder is refused", _refused(lambda: rival_guards(os.path.join(tmp, "nowhere"))))
        # tree hash: a changed byte in the package changes the pin
        pk = os.path.join(tmp, "pk")
        os.makedirs(pk)
        open(os.path.join(pk, "a.js"), "w").write("x")
        h1 = tree_sha256(pk)
        open(os.path.join(pk, "a.js"), "w").write("y")
        h2 = tree_sha256(pk)
        open(os.path.join(pk, "a.js"), "w").write("x")
        check("planted: one changed byte in a package changes its tree hash", h1 != h2)
        check("clean control: the same bytes give the same tree hash", h1 == tree_sha256(pk))
        # containment: the stand-in tries a write inside the room, a write outside it, and a connection (nothing is sent anywhere)
        outside = os.path.join(tmp, "OUTSIDE_PROBE.txt")
        pr = run_matrix(rows[:1], {"probe": (hook("contain_probe"), {"PROBE_OUTSIDE": outside})}, room, 1, log=lambda *_: None)["probe"][0]
        check("containment: inside write ok, outside write refused, connection refused by the sandbox (not merely a closed port)",
              "inside=ok" in pr["reason"] and "outside=EPERM" in pr["reason"] and "net=EPERM" in pr["reason"] and not os.path.exists(outside), pr)
        # clean control for the same: the same stand-in, uncontained, can write outside the room (so the refusal above was the sandbox's)
        un = run_hook(hook("contain_probe"), guard_env(room, {"PROBE_OUTSIDE": outside}), room["repo"], "echo x")
        check("containment control: uncontained, the same stand-in writes outside the room (so the refusal was the sandbox)",
              "outside=ok" in un["reason"] and os.path.exists(outside), un)
        if os.path.exists(outside):
            os.remove(outside)
        # canary: a working guard passes; a guard that allows everything, one that crashes, and one that denies everything fail
        check("canary, clean control: a guard that stops `git reset --hard` and allows `git status` passes", canary({"ok": (hook("deny_reset"), {})}, room) == [])
        check("canary, planted: a guard that allows everything fails", len(canary({"x": (hook("allow_all"), {})}, room)) == 1)
        check("canary, planted: a guard that crashes fails (it would have scored a quiet 0%)", len(canary({"x": (hook("crash"), {})}, room)) == 1)
        check("canary, planted: a guard that stops `git status` too fails (stops everything)",
              len(canary({"x": (hook("contain_probe"), {"PROBE_OUTSIDE": outside})}, room)) == 1)
        if os.path.exists(outside):
            os.remove(outside)
        # ours: a guard.py that is not v30 is refused (planted); the real bench's guard.py is accepted (clean control)
        open(os.path.join(bench, "guard.py"), "w").write("# not v30\n")
        check("planted: a guard.py that is not v30 is refused", _refused(lambda: ours_guard(bench, PINNED_ROOT)))
        real = os.path.join(DEFAULT_BENCH, "guard.py")
        if os.path.isfile(real):
            gp_, gsha_, g_ = ours_guard(DEFAULT_BENCH, PINNED_ROOT)
            check("clean control: the real bench guard.py is v30 and its env pins undo off and the root %s" % PINNED_ROOT,
                  gsha_ == OURS_SHA and g_[1] == {"AGENT_GUARD_UNDO": "0", "AGENT_GUARD_ROOT": PINNED_ROOT})
        else:
            lines.append("SKIPPED ON THIS HOST: no %s, so the v30 acceptance control did not run" % real)
        # a refusal with no flag: the entry point starts nothing
        p = subprocess.run([sys.executable, os.path.join(HERE, "score_rivals_v31.py")], capture_output=True, text=True, cwd=tmp)
        check("entry point with no flag runs nothing and exits 2", p.returncode == 2 and "Nothing run" in p.stdout, (p.returncode, p.stdout[:80]))
        # sensitivity rewrite
        sr = sensitivity_rows(rows, room)
        check("sensitivity: only the row naming /work/repo is rewritten, to the real fixture repo",
              [r["id"] for r in sr] == ["T6"] and room["repo"] in sr[0]["command"] and PINNED_ROOT not in sr[0]["command"])
        shutil.rmtree(room["root"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if os.path.exists(tmp):
        failed += 1
        lines.append("FAIL  self-test folder not deleted: %s" % tmp)
    print("\n".join(lines))
    print("Blind to: any rival's real behaviour (no rival is started here; the stand-ins only exercise this scorer), the label correctness, "
          "the live Claude Code payload, and a different Python or macOS than this one (proven only on this host).")
    print("SELF-TEST: %d passed, %d failed" % (passed, failed))
    return 0 if failed == 0 else 1


def _refused(fn):
    try:
        fn()
    except Refuse:
        return True
    return False


if __name__ == "__main__":
    sys.exit(main(sys.argv))
