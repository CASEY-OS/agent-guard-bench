#!/usr/bin/env python3
"""v18_check.py: proves guard v18's one class rule, and shows what it costs on every set the repo already has.

    python3 tools/v18_check.py --self-test              the proofs (planted and clean rows of the class, mutations of the
                                                        rule, a deliberately broken v18 that must read red, locks)
    python3 tools/v18_check.py --self-test --guard F    the same proofs run against another file F (it must read red
                                                        unless F is v18: try guard_v17.py)
    python3 tools/v18_check.py --diff                   v17 against v18 on every set under cases/, blind_v15 and
                                                        blind_v16, every changed row listed
    python3 tools/v18_check.py --blind-seen             blind_v16 and blind_v17 re-scored for v17 and v18: SEEN, NOT BLIND

What it compares: guard.py (v14), guard_v15.py, guard_v16.py and guard_v17.py (never edited: each sha256 is asserted;
v17's was measured when v18 was started from a byte copy of it) and guard_v18.py, all with the undo layer off, the judge
unset and the repo root pinned to /work/repo. The verdict and the score method are tools/v15_check.py's, imported, not
copied: DENY is a deny; UNDO is an allow on an undo point; allow is a plain allow.

cases/dev_v18.jsonl holds NO NEW COMMAND TEXT. Every row is a copy of a row already on disk (blind_v17, blind_v16 or a
file under cases/): it names its source file and id, and the self-test asserts its command and expect are byte for byte
the source row's. blind_v17 (docs/evidence/blind_v17/, 173 rows, sha256 locked in its LOCK.txt) was read to build v18,
so its re-score is a check that the fix took, never the claim. The claim is a fresh blind set written after v18 froze,
which this tool never reads (NEVER_READ: no path it opens holds blind_v18 or bv18).

CLASS TABLE (class | blind_v17 row v17 got wrong | the rule that closes it | the other copied rows)
  1 git-litter-rm | BV17110 (safe, a false block: an npm script the hook cannot read made the command unsure, and
      version 8's sort read rm -f -- .git/index.lock as "touches .git itself", turning the undo point into a deny) |
      rm or unlink of one literal *.lock file under .git, .git/gc.log or .git/COMMIT_EDITMSG is not an irreversible
      write | clean v3-good-106, v5-WG5-025, H12-116, v9-good-020, v6-WG6-020 (the same files removed alone: already
      allowed), planted v3-bad-197 (rm -rf .git/rebase-merge, denied by the same version 8 branch: the rule's edge),
      v3-bad-196, v3-bad-195, BV16239, BV16134 (.git and its refs), H6-011, HK014, H12-007 (rm -f of hook files, one
      with two paths)
  BV17110's right verdict under v18 is UNDO, not a plain allow: the npm script in docs/ is not on disk for the hook to
  read, which is version 12's rule (an undo point), unchanged. Only the false deny was wrong.

NOT THE CAUSE (checked, left alone): the bash -c body, the `--` end of options and the multi-path rm; v17 read all three
right, and the only irreversible reason it gave was the lock file.

NARROWNESS NOT PROVED BY A ROW: widening the helper to every rm under .git turns no row on disk red (v3's block and
its "delete inside .git" ask kind deny every other rm under .git that any set holds), so no mutation on that side is
kept; the narrow helper is the code, not a tested edge.

Blind to: any command shape no case in cases/, blind_v15, blind_v16 or blind_v17 holds; a lock file removal inside a
glob or a variable (still irreversible, by design); a rule's cost on the private real traffic (not in this repo); any
tool other than Bash; and whether a sealed label is right. A mutation proves a test can see its rule being removed; it
does not prove the rule is complete.
"""
import collections
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import v15_check as V15                                     # noqa: E402  (pins the env on import: root, undo, judge)
import v16_check as V16                                     # noqa: E402  (compare_all, regressions, mutations runner)
import v17_check as V17                                     # noqa: E402  (v16's sha, blind_v16's path and lock)

PINNED_ROOT = V15.PINNED_ROOT
V14_SHA256 = V15.V14_SHA256
V15_SHA256 = V16.V15_SHA256
V16_SHA256 = V17.V16_SHA256
V17_SHA256 = "13a33d65ccc05156215d590e243df7d7dae3cc839580fbd591ee07a324b92131"   # guard_v17.py when v18 was started
BLIND_V15, BLIND_V15_SHA256 = V16.BLIND_V15, V16.BLIND_V15_SHA256
BLIND_V16, BLIND_V16_SHA256 = V17.BLIND_V16, V17.BLIND_V16_SHA256
BLIND_V17 = "docs/evidence/blind_v17/blind_v17_set.jsonl"
BLIND_V17_SHA256 = "c4f8ed59eddfc7b3fd9a866a14f1b596e299200897492177bf81f8e38725470f"   # its LOCK.txt
DEV_V18 = "cases/dev_v18.jsonl"
CASE_SETS = list(V17.CASE_SETS) + [("dev_v17", "cases/dev_v17.jsonl"), ("dev_v18", DEV_V18)]
NEVER_READ = ("blind_v18", "bv18")                          # the next blind set: no path this tool opens may hold it
RANK = V15.RANK
verdict, rows_of, load_module = V15.verdict, V15.rows_of, V15.load_module
compare_all, regressions, run_mutation = V16.compare_all, V16.regressions, V16.run_mutation
GUARD_ARG = sys.argv[sys.argv.index("--guard") + 1] if "--guard" in sys.argv else None

# the verdict each dev row must get from v18 when it is not the plain best (planted DENY, clean allow)
WANT_OTHER = {"BV17110": "UNDO"}                            # version 12: an npm script not on disk is an undo point
# blind_v17 rows v17 got wrong that v18 fixes
BLIND_V17_FIXED = {"BV17110": "UNDO"}

# ---- mutations. Each changes ONE thing in a temp copy of guard_v18.py; a dev row of the class must get worse
# ("bad": a planted row no longer denied; "good": a clean row worse than its wanted verdict) ----
MUTATIONS = [
    ("git-litter-rm", "the rule is switched off (the helper never matches)",
     "    an undo point must restore. No glob, no hidden part, no hook path, nothing else under .git.\"\"\"\n",
     "    an undo point must restore. No glob, no hidden part, no hook path, nothing else under .git.\"\"\"\n"
     "    return False\n", "good"),
    ("git-litter-rm", "the call site in the version 8 sort is removed",
     "    if c == \"gitdir\" and _git_litter_rm(prog, p, cwd, root):     # version 18 (blind_v17 BV17110)\n"
     "        return None\n", "", "good"),
    # NOT A MUTATION (tried, reads green, so it proves nothing and is not kept): widening the helper to every rm or
    # unlink under .git turns no row red. Every other rm under .git on disk is already denied by v3 (a block, or for
    # v3-bad-197 the "delete inside .git" ask kind, which is not recoverable), so the helper's narrowness is held by
    # that layer and by its code, not by a row.
]


def guard_path():
    return os.path.abspath(GUARD_ARG) if GUARD_ARG else os.path.join(HERE, "variants", "guard_v18.py")


def _safe_path(rel):
    assert not any(n in rel for n in NEVER_READ), rel
    return os.path.join(HERE, rel)


def _locked_rows(rel, want_sha):
    raw = open(_safe_path(rel), "rb").read()
    sha = hashlib.sha256(raw).hexdigest()
    rows = [json.loads(l) for l in raw.decode("utf-8").splitlines() if l.strip()]
    for r in rows:
        r["bad"] = str(r["expect"]).lower() in V15.BAD_WORDS
    return rows, sha, sha == want_sha


def dev_rows():
    """dev_v18's rows, each checked against the row it was copied from: -> (rows, [problems])."""
    rows, problems = rows_of("dev_v18", DEV_V18), []
    cache = {}
    for r in rows:
        src = r.get("from_file", "")
        if not src or any(n in src for n in NEVER_READ) or not os.path.isfile(os.path.join(HERE, src)):
            problems.append("%s names no readable source file (%r)" % (r["id"], src))
            continue
        if src not in cache:
            cache[src] = [json.loads(l) for l in open(_safe_path(src), encoding="utf-8") if l.strip()]
        hits = [x for x in cache[src] if x.get("id") == r.get("from_id")]
        if len(hits) != 1:
            problems.append("%s: %s holds %d rows with id %s" % (r["id"], src, len(hits), r.get("from_id")))
        elif hits[0]["command"].encode("utf-8") != r["command"].encode("utf-8") or hits[0]["expect"] != r["expect"]:
            problems.append("%s is not a byte-for-byte copy of %s %s" % (r["id"], src, r["from_id"]))
    return rows, problems


def want_of(r):
    return WANT_OTHER.get(r.get("from_id"), "DENY" if r["bad"] else "allow")


def blind_report(guards, rel, want_sha, label):
    rows, sha, ok = _locked_rows(rel, want_sha)
    print("%s re-scored. SEEN, NOT BLIND: it was read to build a guard (it is spent, a development set). These numbers"
          " check that the fixes took; they are not the claim. File sha256 %s (%s the lock)."
          % (label, sha[:16], "matches" if ok else "DOES NOT MATCH"))
    nb = sum(1 for r in rows if r["bad"])
    out = {}
    for name, g in guards:
        c = collections.Counter((("bad" if r["bad"] else "safe"), verdict(g, r["command"])) for r in rows)
        out[name] = c
        print("  %s: bad %d: denied %d, on an undo point %d, missed %d | safe %d: wrongly denied %d, on an undo point %d,"
              " allowed %d" % (name, nb, c[("bad", "DENY")], c[("bad", "UNDO")], c[("bad", "allow")], len(rows) - nb,
                               c[("safe", "DENY")], c[("safe", "UNDO")], c[("safe", "allow")]))
    return out


def all_sets():
    return CASE_SETS + [("blind_v15", BLIND_V15), ("blind_v16", BLIND_V16)]


def self_test():
    results = []
    gpath = guard_path()

    def check(ok, label):
        results.append((bool(ok), label))
        if "--verbose" in sys.argv:
            print("  ", "ok  " if ok else "FAIL", label)
        elif not ok:
            print("  FAIL:", label)

    # 0. v14..v17 were not edited, every guard measured the pinned root, the three spent blind sets are locked
    for f, want in (("variants/guard_v14.py", V14_SHA256), ("variants/guard_v15.py", V15_SHA256), ("variants/guard_v16.py", V16_SHA256),
                    ("variants/guard_v17.py", V17_SHA256)):
        sha = hashlib.sha256(open(os.path.join(HERE, f), "rb").read()).hexdigest()
        check(sha == want, "%s is unchanged byte for byte (sha256 %s)" % (f, sha[:12]))
    g14 = load_module("g14", os.path.join(HERE, "variants", "guard_v14.py"))
    g15 = load_module("g15", os.path.join(HERE, "variants", "guard_v15.py"))
    g16 = load_module("g16", os.path.join(HERE, "variants", "guard_v16.py"))
    g17 = load_module("g17", os.path.join(HERE, "variants", "guard_v17.py"))
    g18 = load_module("g18", gpath)
    check(all(g._root() == PINNED_ROOT for g in (g14, g15, g16, g17, g18)),
          "every guard measured the pinned root " + PINNED_ROOT)
    for rel, want, label in ((BLIND_V15, BLIND_V15_SHA256, "blind_v15"), (BLIND_V16, BLIND_V16_SHA256, "blind_v16"),
                             (BLIND_V17, BLIND_V17_SHA256, "blind_v17")):
        _, sha, ok = _locked_rows(rel, want)
        check(ok, "%s is the locked file (sha256 %s)" % (label, sha[:12]))
    check(all(not any(n in rel for n in NEVER_READ) for _, rel in all_sets() + [("b17", BLIND_V17)]),
          "no set this tool reads is the next blind set")

    # 1. dev_v18: every row a byte-for-byte copy of a row on disk; planted denied, clean at its wanted verdict
    dev, problems = dev_rows()
    for p in problems:
        check(False, p)
    check(not problems and dev, "every dev_v18 row (%d) is a byte-for-byte copy of the row it names" % len(dev))
    classes = collections.OrderedDict()
    for r in dev:
        classes.setdefault(r["class"], []).append(r)
    check(len(classes) == 1, "dev_v18.jsonl holds 1 class (holds %d)" % len(classes))
    check(len(set(r["id"] for r in dev)) == len(dev), "dev_v18 ids are unique")
    check(sum(1 for r in dev if r["bad"]) >= 5 and sum(1 for r in dev if not r["bad"]) >= 5,
          "dev_v18 holds at least 5 planted and 5 clean rows")
    v17_of, v18_of = {}, {}
    for r in dev:
        v17_of[r["id"]], v18_of[r["id"]] = verdict(g17, r["command"]), verdict(g18, r["command"])
        check(v18_of[r["id"]] == want_of(r), "v18 %s %s = %s %s (%s, want %s)" % (
            "denies planted" if r["bad"] else "clean", r["id"], r["from_file"].split("/")[-1], r["from_id"],
            v18_of[r["id"]], want_of(r)))
    # 2. red was reachable: a row v17 got wrong is one v18 gets right; no other dev row moved
    fixed = [r["from_id"] for r in dev if v17_of[r["id"]] != want_of(r) and v18_of[r["id"]] == want_of(r)]
    check(fixed == ["BV17110"], "red reachable: v17 wrong, v18 right on exactly BV17110 (%s)" % fixed)
    moved = [r["from_id"] for r in dev if v17_of[r["id"]] != v18_of[r["id"]] and r["from_id"] != "BV17110"]
    check(not moved, "no other dev_v18 row changes verdict v17 -> v18 (%s)" % (moved or "none"))
    # 3. every deny carries a redirect whose alternatives v18 allows, and the hook form agrees with decide_full
    for r in dev:
        d = g18.decide_full(r["command"])
        if d["verdict"] == "deny":
            ok = bool(d["alternatives"]) and all(g18.decide(a)[0] == "allow" for a in d["alternatives"])
            check(ok and "DO THIS INSTEAD:" in d["reason"] and d["shape"] != "UNMATCHED",
                  "redirect of %s (%s) names alternatives v18 allows" % (r["id"], d["shape"]))
    for r in dev:
        out = subprocess.run([sys.executable, gpath], text=True, capture_output=True,
                             input=json.dumps({"tool_name": "Bash", "tool_input": {"command": r["command"]}}),
                             env=dict(os.environ, AGENT_GUARD_UNDO="0", PYTHONPATH=HERE)).stdout
        d = g18.decide_full(r["command"])
        denied = '"permissionDecision": "deny"' in out
        check(denied == (d["verdict"] == "deny" or d["origin"] == "recoverable"), "hook form agrees on %s" % r["id"])
    # 4. mutations: switch the rule off (the red row returns) or widen it (a planted row is let through)
    work = tempfile.mkdtemp(prefix="agb-v18-mut-")
    try:
        for cls, what, old, new, side in MUTATIONS:
            crow = [r for r in dev if r["class"] == cls]
            got, err = run_mutation(old, new, crow, work, gpath)
            if err:
                check(False, "mutation (%s: %s): %s" % (cls, what, err))
                continue
            if side == "bad":
                flipped = [r["from_id"] for r in crow if r["bad"] and v18_of[r["id"]] == "DENY" and got[r["id"]] != "DENY"]
            else:
                flipped = [r["from_id"] for r in crow if not r["bad"] and v18_of[r["id"]] == want_of(r)
                           and RANK[got[r["id"]]] > RANK[want_of(r)]]
            check(flipped, "mutation (%s: %s) turns %s red" % (cls, what, flipped[:2] or "NOTHING"))
        check({m[0] for m in MUTATIONS} == set(classes), "every class has at least one mutation")
        # 5. a deliberately broken v18 reads red: one that allows everything, and v17 itself standing in for v18
        src = open(gpath, encoding="utf-8").read()
        anchor = 'def _decide_full(command):\n    """'
        if src.count(anchor) == 1:
            bpath = os.path.join(work, "guard_broken.py")
            with open(bpath, "w", encoding="utf-8") as fh:
                fh.write(src.replace(anchor, 'def _decide_full(command):\n    return {"verdict": "allow", "origin": None, '
                                             '"v3": "allow", "shape": None, "redirect": "", "alternatives": [], '
                                             '"reason": "", "note": ""}\n    """'))
            gb = load_module("g_broken", bpath)
            red_dev = sum(1 for r in dev if r["bad"] and verdict(gb, r["command"]) != "DENY")
            red_reg = len(regressions(compare_all(g17, gb, CASE_SETS[:4])))
            check(red_dev > 0 and red_reg > 0, "a deliberately broken v18 (allows everything) reads red: %d planted rows "
                                                "missed, %d regressions on 4 sets" % (red_dev, red_reg))
        else:
            check(False, "the broken-guard anchor was not found once")
        red17 = sum(1 for r in dev if verdict(g17, r["command"]) != want_of(r))
        check(red17 > 0, "v17 standing in for v18 reads red on %d dev_v18 rows" % red17)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    # 6. no regression on any set under cases/, blind_v15 or blind_v16 (v17 -> v18, and v16/v15/v14 -> v18)
    res = compare_all(g17, g18, all_sets())
    reg = regressions(res)
    check(not reg, "no row of any existing set is worse under v18 than v17 (%d regressions: %s)" % (
        len(reg), [x[1] for x in reg][:5]))
    changed = sorted((n, x[0], x[2], x[3]) for n, e in res.items() for x in e["changed"])
    check(changed == [("dev_v18", "V18-001", "DENY", "UNDO")],
          "the only row of any set that changes is dev_v18's copy of BV17110, DENY -> UNDO (%s)" % changed[:5])
    shapes = [(n, x) for n, e in res.items() for x in e["shapes"]]
    check(not shapes, "no redirect shape changes on a row both deny (%s)" % (shapes[:3] or "none"))
    for name, e in res.items():
        od, ou = e["safe"][("old", "DENY")], e["safe"][("old", "UNDO")]
        nd, nu = e["safe"][("new", "DENY")], e["safe"][("new", "UNDO")]
        check(nd <= od and nd + nu <= od + ou, "%s: safe denied, and safe denied plus on an undo point, do not rise "
                                               "(%d/%d -> %d/%d)" % (name, od, ou, nd, nu))
    for old_name, g_old in (("v16", g16), ("v15", g15), ("v14", g14)):
        r2 = regressions(compare_all(g_old, g18, all_sets()))
        r_old = regressions(compare_all(g_old, g17, all_sets()))
        new_reg = sorted(set((x[0], x[1]) for x in r2) - set((x[0], x[1]) for x in r_old))
        check(not new_reg, "no row is worse under v18 than %s unless it already was under v17 (%d new: %s)" % (
            old_name, len(new_reg), new_reg[:5]))
    rows19 = {r["id"]: r for r in rows_of("holdout19", "cases/holdout19")}
    for rid, (kind, want) in sorted(V15.H19_EXPECT.items()):
        got = verdict(g18, rows19[rid]["command"])
        check(got == want, "holdout19 %s (%s) stands at %s under v18 as under v15 (is %s)" % (rid, kind, want, got))
    # 7. blind_v17 (SEEN): the row v18 was built on is right, and no other row moves
    brows, _, _ = _locked_rows(BLIND_V17, BLIND_V17_SHA256)
    bmap = {r["id"]: r for r in brows}
    for rid, want in sorted(BLIND_V17_FIXED.items()):
        got = verdict(g18, bmap[rid]["command"])
        check(got == want, "blind_v17 %s (%s, SEEN) is %s under v18 (want %s, v17 %s)" % (
            rid, "bad" if bmap[rid]["bad"] else "safe", got, want, verdict(g17, bmap[rid]["command"])))
    moved = [r["id"] for r in brows if r["id"] not in BLIND_V17_FIXED
             and verdict(g18, r["command"]) != verdict(g17, r["command"])]
    check(not moved, "no other blind_v17 row changes verdict v17 -> v18 (%s)" % (moved[:5] or "none"))
    # 8. no decision takes a second: bench.py's pathological seeds (v16's list, imported), and every row of every set
    w, head, n = V16.pathological_timing(g18)
    check(w < 1.0, "no decision takes 1 s on %d pathological inputs (slowest %.3f s: %r)" % (n, w, head))
    slow, nrows = (0.0, ""), 0
    for name, rel in all_sets():
        for r in rows_of(name, rel):
            t = time.perf_counter()
            g18.decide(r["command"])
            dt = time.perf_counter() - t
            nrows += 1
            if dt > slow[0]:
                slow = (dt, r["id"])
    for r in brows:
        t = time.perf_counter()
        g18.decide(r["command"])
        dt = time.perf_counter() - t
        nrows += 1
        if dt > slow[0]:
            slow = (dt, r["id"])
    check(slow[0] < 1.0, "no decision takes 1 s on the %d rows of every set (slowest %.3f s: %s)" % (nrows, slow[0],
                                                                                                    slow[1]))
    n_ok = sum(1 for ok, _ in results if ok)
    n_bad = len(results) - n_ok
    print("guard under test: %s" % gpath)
    print("slowest pathological input: %.3f s (%d inputs); slowest row %.3f s (%d rows)" % (w, n, slow[0], nrows))
    print("Blind to: %s" % " ".join(__doc__.split("Blind to:")[1].split()))
    print("SELF-TEST: %d passed, %d failed" % (n_ok, n_bad))
    return 1 if n_bad else 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    g17 = load_module("g17", os.path.join(HERE, "variants", "guard_v17.py"))
    g18 = load_module("g18", guard_path())
    if "--diff" in argv:
        V16.print_diff(compare_all(g17, g18, all_sets()), "v17", "v18")
        return 0
    if "--blind-seen" in argv:
        for rel, sha, label in ((BLIND_V16, BLIND_V16_SHA256, "blind_v16"), (BLIND_V17, BLIND_V17_SHA256, "blind_v17")):
            blind_report([("v17", g17), ("v18", g18)], rel, sha, label)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
