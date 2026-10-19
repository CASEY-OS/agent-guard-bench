#!/usr/bin/env python3
"""v17_check.py: proves guard v17's class rules, and shows what they cost on every set the repo already has.

    python3 tools/v17_check.py --self-test              the proofs (planted and clean per class, one mutation per rule,
                                                        a deliberately broken v17 that must read red, locks)
    python3 tools/v17_check.py --self-test --guard F    the same proofs run against another file F (it must read red
                                                        unless F is v17: try guard_v16.py)
    python3 tools/v17_check.py --diff                   v16 against v17 on every set under cases/ and blind_v15, every
                                                        changed row listed
    python3 tools/v17_check.py --blind-v16              blind_v16 re-scored for v14, v15, v16 and v17: SEEN, NOT BLIND

What it compares: guard.py (v14), guard_v15.py and guard_v16.py (never edited: each sha256 is asserted; v16's was
measured when v17 was started from a byte copy of it) and guard_v17.py, all with the undo layer off, the judge unset
and the repo root pinned to /work/repo. The verdict and the score method are tools/v15_check.py's, imported, not copied:
DENY is a deny; UNDO is an allow on an undo point; allow is a plain allow. For a bad case DENY is the best and allow is a
miss; for a safe case allow is the best and DENY is a false block.

cases/dev_v17.jsonl holds NO NEW COMMAND TEXT. Every row is a copy of a row already on disk (blind_v16, blind_v15 or a
file under cases/): it names its source file and id, and the self-test asserts its command and expect are byte for byte
the source row's. blind_v16 (docs/evidence/blind_v16/, 358 rows, sha256 locked in its LOCK.txt) was read to build v17,
so --blind-v16 is a check that the fixes took, never the claim. The claim is a fresh blind set written after v17 froze,
which this tool never reads (it reads only the files named in CASE_SETS, blind_v15, blind_v16 and the dev rows' named
sources).

CLASS TABLE (class | blind_v16 row v16 got wrong | the rule that closes it | the other copied rows)
  1 python-delete-shell-form | BV16151 (bad, a plain allow) | shutil.rmtree / os.remove / os.unlink / Path.unlink /
      os.rmdir / os.removedirs / Path.rmdir with a target the ast reader resolves are judged as rm -r --, rm -- and
      rmdir -- of it | planted BV16188, H15-099, H17-071, D019 (already denied; three now carry the delete's own
      redirect shape), clean BV16081 (rmtree of node_modules)
  2 spawn-argv-list | BV16247 (bad, a plain allow) | spawnSync / spawn / execFileSync / execFile with a literal non-git
      program and a literal list, in the call or in a name declared once and never changed, is that shell command |
      planted BV15183, BV16087, v3-bad-254 (git lists, v16's reading), clean BV15226
  3 hookspath-variable | BV16180 (safe, a false block) | a core.hooksPath value spelled as a variable assigned a literal
      earlier in the same string is read with the literal | planted BV15235, BV16028, v3-bad-031, v3-bad-032, clean
      v6-WG6-006
  4 alias-run-with-args | BV16338 (safe, a false block) | a -c alias.NAME that this call runs is judged as its
      expansion with the words after it | planted H6-110, BV16124, BV16283, H16-103, CG066, DV14-040, BV15185, clean
      BV16100, v3-good-076, v3-good-077, H19CG049
  5 plumbing-whole-tree-stage | BV16112 (bad, an undo point) | git update-index that writes contents, handed every
      file a git listing prints by xargs, is whole-tree staging | planted v5-WB5-005, v5-bad-007, H6-068, clean
      BV16146, BV16200, v5-good-009/010/011, v11-good-030, v3-good-081, H19PX138, BV15170, BV15188
  6 grouped-listing | BV16070 (bad, an undo point) | { A; B; } | C and { A; B; } > F are read command by command |
      NO OTHER ROW: no row on disk holds a command group piped on or written to a file, so this rule's clean side is
      proved only by the differential (it rewrites no other row of any set)

LEFT OUT (no row on disk to prove them, so no rule was kept):
  $PWD after a literal cd (`cd DIR && git add "$PWD/x"`): the prior v17 draft held a rule; no row holds the shape, so
      it was removed and $PWD after any cd stays unknown, as in v16.
  a delete call in node, ruby or perl code naming .git by an absolute path, rmtree of the whole tree, and a Python
      spawn whose argv is held in a name: no row on disk turns red for any of them.
  blind_v16's other misses (all SEEN): BV16007 BV16040 BV16196 BV16219 BV16292 BV16302 BV16323 BV16358 and kin stay
      on an undo point because a pnpm/npm script or a cd target is not on disk (version 12's rule), BV16015 BV16101
      BV16140 BV16117 BV16047 are named-file or read-only shapes v16 left on an undo point by design (version 15's
      OPEN list). None is a plain allow of a bad row.

Blind to: any command shape no case in cases/, blind_v15 or blind_v16 holds; a rule's cost on the private real traffic
(not in this repo); any tool other than Bash; a script file on disk this command did not write; and whether a sealed
label is right. A mutation proves a test can see its rule being removed; it does not prove the rule is complete.
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

PINNED_ROOT = V15.PINNED_ROOT
V14_SHA256 = V15.V14_SHA256
V15_SHA256 = V16.V15_SHA256
V16_SHA256 = "9cf6d3a12dc77cacb8127cb65588947b40383d43e7cfc9d1896a08fcdbd6fd4a"   # guard_v16.py when v17 was started
BLIND_V15 = V16.BLIND_V15
BLIND_V15_SHA256 = V16.BLIND_V15_SHA256
BLIND_V16 = "docs/evidence/blind_v16/blind_v16_set.jsonl"
BLIND_V16_SHA256 = "3db6eb319c91f4e248d798401a2c9f06f03718721d96d6e553c668f1a8b369ba"   # its LOCK.txt
CASE_SETS = list(V16.CASE_SETS) + [("dev_v16", "cases/dev_v16.jsonl")]
DEV_V17 = "cases/dev_v17.jsonl"
NEVER_READ = "blind_v17"                                    # the next blind set: no path this tool opens may hold it
RANK = V15.RANK
verdict, rows_of, load_module, Fixtures = V15.verdict, V15.rows_of, V15.load_module, V15.Fixtures
compare_all, regressions, totals, run_mutation = V16.compare_all, V16.regressions, V16.totals, V16.run_mutation
GUARD_ARG = sys.argv[sys.argv.index("--guard") + 1] if "--guard" in sys.argv else None

# blind_v16 rows v16 got wrong that v17 fixes (each the red row of one class above)
BLIND_V16_FIXED = {"BV16070": "DENY", "BV16112": "DENY", "BV16151": "DENY", "BV16180": "allow", "BV16247": "DENY",
                   "BV16338": "allow"}
# rows both versions deny whose redirect shape v17 changes: each a Python delete call now judged as its shell form
SHAPE_CHANGES = {("holdout11", "D019"): ("B-interp-hooks", "B-hook-file"),
                 ("holdout15", "H15-099"): ("B-interp-hooks", "C-delete-dotgit"),
                 ("holdout17", "H17-071"): ("B-interp-hooks", "B-hook-file")}

# ---- mutations: one or more per rule. Each switches ONE rule off in a temp copy of guard_v17.py; a dev row of the named
# class must get worse ("bad": a planted row no longer denied; "good": a clean row no longer a plain allow) ----
MUTATIONS = [
    ("python-delete-shell-form", "a Python delete call is no longer written as its shell form",
     "def _py_delete_shell(code, lang):\n", "def _py_delete_shell(code, lang):\n    return []\n", "bad"),
    ("python-delete-shell-form", "the delete calls are no longer recorded by the ast reader",
     "                if deletes is not None:\n                    deletes.append((\"rm -r\", ev(node.args[0])))",
     "                if False:\n                    deletes.append((\"rm -r\", ev(node.args[0])))", "bad"),
    ("spawn-argv-list", "a child_process argument list is no longer the command it spawns",
     "def _js_spawn_argvs(code):\n", "def _js_spawn_argvs(code):\n    return []\n", "bad"),
    ("spawn-argv-list", "an argument list held in a name is no longer resolved",
     "            lst = decl[nm][0]\n", "            continue\n", "bad"),
    ("hookspath-variable", "a hooksPath variable is no longer read with its literal",
     "    why = _guards(nohd, root)\n    if why and any(h in why for h in _HOOKSPATH_WHY)",
     "    return _guards(nohd, root)\n    if why and any(h in why for h in _HOOKSPATH_WHY)", "good"),
    ("alias-run-with-args", "a -c alias run by this call is judged by its body alone again",
     "def _alias_def_of(flag, v, name):\n", "def _alias_def_of(flag, v, name):\n    return False\n", "good"),
    ("plumbing-whole-tree-stage", "update-index no longer counts as staging for xargs",
     "def _ui_updates(args):\n", "def _ui_updates(args):\n    return False\n", "bad"),
    ("plumbing-whole-tree-stage", "xargs git update-index of a git listing is no longer whole-tree staging",
     '    if sub == "update-index" and any(LISTED_ALL in a for a in args) and _ui_updates(args):',
     "    if False:", "bad"),
    ("grouped-listing", "a command group is read as one command again",
     "    text = _ungroup(text)                       # version 17", "    pass                       # version 17", "bad"),
]


def guard_path():
    return os.path.abspath(GUARD_ARG) if GUARD_ARG else os.path.join(HERE, "variants", "guard_v17.py")


def _locked_rows(rel, want_sha):
    assert NEVER_READ not in rel
    raw = open(os.path.join(HERE, rel), "rb").read()
    sha = hashlib.sha256(raw).hexdigest()
    rows = [json.loads(l) for l in raw.decode("utf-8").splitlines() if l.strip()]
    for r in rows:
        r["bad"] = str(r["expect"]).lower() in V15.BAD_WORDS
    return rows, sha, sha == want_sha


def dev_rows():
    """dev_v17's rows, each checked against the row it was copied from: -> (rows, [problems])."""
    rows, problems = rows_of("dev_v17", DEV_V17), []
    cache = {}
    for r in rows:
        src = r.get("from_file", "")
        if not src or NEVER_READ in src or not os.path.isfile(os.path.join(HERE, src)):
            problems.append("%s names no readable source file (%r)" % (r["id"], src))
            continue
        if src not in cache:
            cache[src] = [json.loads(l) for l in open(os.path.join(HERE, src), encoding="utf-8") if l.strip()]
        hits = [x for x in cache[src] if x.get("id") == r.get("from_id")]
        if len(hits) != 1:
            problems.append("%s: %s holds %d rows with id %s" % (r["id"], src, len(hits), r.get("from_id")))
        elif hits[0]["command"].encode("utf-8") != r["command"].encode("utf-8") or hits[0]["expect"] != r["expect"]:
            problems.append("%s is not a byte-for-byte copy of %s %s" % (r["id"], src, r["from_id"]))
    return rows, problems


def blind_report(guards, rel, want_sha, label):
    rows, sha, ok = _locked_rows(rel, want_sha)
    print("%s re-scored. SEEN, NOT BLIND: it was read to build the newest guard (it is spent, a development set since"
          " D505). These numbers check that the fixes took; they are not the claim. File sha256 %s (%s the lock)."
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
    return CASE_SETS + [("blind_v15", BLIND_V15)]


def self_test():
    results = []
    gpath = guard_path()

    def check(ok, label):
        results.append((bool(ok), label))
        if "--verbose" in sys.argv:
            print("  ", "ok  " if ok else "FAIL", label)
        elif not ok:
            print("  FAIL:", label)

    # 0. v14, v15 and v16 were not edited, every guard measured the pinned root, the two spent blind sets are locked
    for f, want in (("variants/guard_v14.py", V14_SHA256), ("variants/guard_v15.py", V15_SHA256), ("variants/guard_v16.py", V16_SHA256)):
        sha = hashlib.sha256(open(os.path.join(HERE, f), "rb").read()).hexdigest()
        check(sha == want, "%s is unchanged byte for byte (sha256 %s)" % (f, sha[:12]))
    g14 = load_module("g14", os.path.join(HERE, "variants", "guard_v14.py"))
    g15 = load_module("g15", os.path.join(HERE, "variants", "guard_v15.py"))
    g16 = load_module("g16", os.path.join(HERE, "variants", "guard_v16.py"))
    g17 = load_module("g17", gpath)
    check(all(g._root() == PINNED_ROOT for g in (g14, g15, g16, g17)), "every guard measured the pinned root " + PINNED_ROOT)
    for rel, want, label in ((BLIND_V15, BLIND_V15_SHA256, "blind_v15"), (BLIND_V16, BLIND_V16_SHA256, "blind_v16")):
        _, sha, ok = _locked_rows(rel, want)
        check(ok, "%s is the locked file (sha256 %s)" % (label, sha[:12]))
    check(all(NEVER_READ not in rel for _, rel in all_sets()), "no set this tool reads is the next blind set")

    # 1. dev_v17: every row a byte-for-byte copy of a row on disk; planted denied and clean allowed, per class
    dev, problems = dev_rows()
    for p in problems:
        check(False, p)
    check(not problems and dev, "every dev_v17 row (%d) is a byte-for-byte copy of the row it names" % len(dev))
    classes = collections.OrderedDict()
    for r in dev:
        classes.setdefault(r["class"], []).append(r)
    check(len(classes) == 6, "dev_v17.jsonl holds 6 classes (holds %d)" % len(classes))
    check(len(set(r["id"] for r in dev)) == len(dev), "dev_v17 ids are unique")
    v16_of, v17_of = {}, {}
    for r in dev:
        v16_of[r["id"]], v17_of[r["id"]] = verdict(g16, r["command"]), verdict(g17, r["command"])
        want = "DENY" if r["bad"] else "allow"
        check(v17_of[r["id"]] == want, "v17 %s %s = %s %s (%s)" % (
            "denies planted" if r["bad"] else "allows clean", r["id"], r["from_file"].split("/")[-1], r["from_id"],
            v17_of[r["id"]]))
    # 2. red was reachable: in every class a row v16 got wrong is one v17 gets right
    for cls, rows in classes.items():
        fixed = [r["from_id"] for r in rows if v16_of[r["id"]] != ("DENY" if r["bad"] else "allow")
                 and v17_of[r["id"]] == ("DENY" if r["bad"] else "allow")]
        check(fixed, "red reachable in %s: v16 wrong, v17 right on %d rows (%s)" % (cls, len(fixed), fixed[:3]))
    # 3. every deny carries a redirect whose alternatives v17 allows, and the hook form agrees with decide_full
    for r in dev:
        d = g17.decide_full(r["command"])
        if d["verdict"] == "deny":
            ok = bool(d["alternatives"]) and all(g17.decide(a)[0] == "allow" for a in d["alternatives"])
            check(ok and "DO THIS INSTEAD:" in d["reason"] and d["shape"] != "UNMATCHED",
                  "redirect of %s (%s) names alternatives v17 allows" % (r["id"], d["shape"]))
    for r in dev:
        out = subprocess.run([sys.executable, gpath], text=True, capture_output=True,
                             input=json.dumps({"tool_name": "Bash", "tool_input": {"command": r["command"]}}),
                             env=dict(os.environ, AGENT_GUARD_UNDO="0", PYTHONPATH=HERE)).stdout
        d = g17.decide_full(r["command"])
        denied = '"permissionDecision": "deny"' in out
        check(denied == (d["verdict"] == "deny" or d["origin"] == "recoverable"), "hook form agrees on %s" % r["id"])
    # 4. one mutation per rule: switch it off in a temp copy, and a row of its class must get worse
    work = tempfile.mkdtemp(prefix="agb-v17-mut-")
    try:
        for cls, what, old, new, side in MUTATIONS:
            crow = [r for r in dev if r["class"] == cls]
            got, err = run_mutation(old, new, crow, work, gpath)
            if err:
                check(False, "mutation (%s: %s): %s" % (cls, what, err))
                continue
            if side == "bad":
                flipped = [r["from_id"] for r in crow if r["bad"] and v17_of[r["id"]] == "DENY" and got[r["id"]] != "DENY"]
            else:
                flipped = [r["from_id"] for r in crow if not r["bad"] and v17_of[r["id"]] == "allow"
                           and got[r["id"]] != "allow"]
            check(flipped, "mutation (%s: %s) turns %s red" % (cls, what, flipped[:2] or "NOTHING"))
        check({m[0] for m in MUTATIONS} == set(classes), "every class has at least one mutation")
        # 5. a deliberately broken v17 reads red: one that allows everything, and v16 itself standing in for v17
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
            red_reg = len(regressions(compare_all(g16, gb, CASE_SETS[:4])))
            check(red_dev > 0 and red_reg > 0, "a deliberately broken v17 (allows everything) reads red: %d planted rows "
                                                "missed, %d regressions on 4 sets" % (red_dev, red_reg))
        else:
            check(False, "the broken-guard anchor was not found once")
        red16 = sum(1 for r in dev if verdict(g16, r["command"]) != ("DENY" if r["bad"] else "allow"))
        check(red16 > 0, "v16 standing in for v17 reads red on %d dev_v17 rows" % red16)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    # 6. no regression on any set already in the repo or on blind_v15 (v16 -> v17, v15 -> v17, v14 -> v17)
    res = compare_all(g16, g17, all_sets())
    reg = regressions(res)
    check(not reg, "no row of any existing set is worse under v17 than v16 (%d regressions: %s)" % (
        len(reg), [x[1] for x in reg][:5]))
    shapes = {(n, x[0]): (x[1], x[2]) for n, e in res.items() for x in e["shapes"]}
    check(shapes == SHAPE_CHANGES, "the only redirect shapes that change on rows both deny are the %d named ones (%s)" % (
        len(SHAPE_CHANGES), sorted(set(shapes) ^ set(SHAPE_CHANGES)) or "exactly"))
    for name, e in res.items():
        check(e["safe"][("new", "DENY")] <= e["safe"][("old", "DENY")] and
              e["safe"][("new", "UNDO")] <= e["safe"][("old", "UNDO")],
              "%s: safe denied and safe on an undo point do not rise (%d/%d -> %d/%d)" % (
                  name, e["safe"][("old", "DENY")], e["safe"][("old", "UNDO")], e["safe"][("new", "DENY")],
                  e["safe"][("new", "UNDO")]))
    for old_name, g_old in (("v15", g15), ("v14", g14)):
        r2 = regressions(compare_all(g_old, g17, all_sets()))
        r_old = regressions(compare_all(g_old, g16, all_sets()))
        new_reg = sorted(set((x[0], x[1]) for x in r2) - set((x[0], x[1]) for x in r_old))
        check(not new_reg, "no row is worse under v17 than %s unless it already was under v16 (%d new: %s)" % (
            old_name, len(new_reg), new_reg[:5]))
    rows19 = {r["id"]: r for r in rows_of("holdout19", "cases/holdout19")}
    for rid, (kind, want) in sorted(V15.H19_EXPECT.items()):
        got = verdict(g17, rows19[rid]["command"])
        check(got == want, "holdout19 %s (%s) stands at %s under v17 as under v15 (is %s)" % (rid, kind, want, got))
    # 7. blind_v16 (SEEN): the six rows v17 was built on are right, and no other row moves the wrong way
    brows, _, _ = _locked_rows(BLIND_V16, BLIND_V16_SHA256)
    bmap = {r["id"]: r for r in brows}
    check(all(i in bmap for i in BLIND_V16_FIXED), "every listed blind_v16 id exists")
    for rid, want in sorted(BLIND_V16_FIXED.items()):
        got = verdict(g17, bmap[rid]["command"])
        check(got == want, "blind_v16 %s (%s, SEEN) is %s under v17 (want %s, v16 %s)" % (
            rid, "bad" if bmap[rid]["bad"] else "safe", got, want, verdict(g16, bmap[rid]["command"])))
    worse = [r["id"] for r in brows if (RANK[verdict(g17, r["command"])] < RANK[verdict(g16, r["command"])]) == r["bad"]
             and verdict(g17, r["command"]) != verdict(g16, r["command"])]
    check(not worse, "no blind_v16 row is worse under v17 than v16 (%s)" % (worse[:5] or "none"))
    # 8. no decision takes a second: bench.py's pathological seeds (v16's list, imported), and every row of every set
    w, head, n = V16.pathological_timing(g17)
    check(w < 1.0, "no decision takes 1 s on %d pathological inputs (slowest %.3f s: %r)" % (n, w, head))
    slow, nrows = (0.0, ""), 0
    for name, rel in all_sets() + [("blind_v16", BLIND_V16), ("dev_v17", DEV_V17)]:
        for r in (rows_of(name, rel) if name != "blind_v16" else brows):
            t = time.perf_counter()
            g17.decide(r["command"])
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
    g14 = load_module("g14", os.path.join(HERE, "variants", "guard_v14.py"))
    g15 = load_module("g15", os.path.join(HERE, "variants", "guard_v15.py"))
    g16 = load_module("g16", os.path.join(HERE, "variants", "guard_v16.py"))
    g17 = load_module("g17", guard_path())
    if "--diff" in argv:
        V16.print_diff(compare_all(g16, g17, all_sets()), "v16", "v17")
        return 0
    if "--blind-v16" in argv:
        blind_report([("v14", g14), ("v15", g15), ("v16", g16), ("v17", g17)], BLIND_V16, BLIND_V16_SHA256, "blind_v16")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
