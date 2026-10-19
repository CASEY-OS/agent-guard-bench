#!/usr/bin/env python3
"""v19_check.py: proves guard v19's class rules, and shows what they cost on every set the repo already has.

    python3 tools/v19_check.py --self-test              the proofs (planted and clean rows per class, one mutation per
                                                        rule, a deliberately broken v19 that must read red, locks)
    python3 tools/v19_check.py --self-test --guard F    the same proofs run against another file F (it must read red
                                                        unless F is v19: try guard_v18.py)
    python3 tools/v19_check.py --diff                   v18 against v19 on every set under cases/, blind_v15, blind_v16
                                                        and blind_v17, every changed row listed
    python3 tools/v19_check.py --blind-seen             blind_v18 re-scored for v18 and v19: SEEN, NOT BLIND

What it compares: guard.py (v14), guard_v15.py, guard_v16.py, guard_v17.py and guard_v18.py (never edited: each sha256
is asserted; v18's was measured when v19 was started from a byte copy of it) and guard_v19.py, all with the undo layer
off, the judge unset and the repo root pinned to /work/repo. The verdict and the score method are tools/v15_check.py's,
imported, not copied: DENY is a deny; UNDO is an allow on an undo point; allow is a plain allow.

cases/dev_v19.jsonl holds NO NEW COMMAND TEXT. Every row is a copy of a row already on disk (blind_v18, blind_v17,
blind_v16, blind_v15 or a file under cases/): it names its source file and id, and the self-test asserts its command and
expect are byte for byte the source row's. blind_v18 (docs/evidence/blind_v18/, 1,066 rows, sha256 locked in its
LOCK.txt) was read to build v19, so its re-score is a check that the fixes took, never the claim. The claim is a fresh
blind set written after v19 froze, which this tool never reads (NEVER_READ: no path it opens holds blind_v19 or bv19).

CLASS TABLE (class | blind_v18 row v18 got wrong | the rule that closes it | the other copied rows)
  1 other-lang-delete | BV180098 (bad, a plain allow) | a delete call in node, bun, deno, ruby or perl code with a literal
      target is its shell form (rm -r, rm, rmdir) | planted H6-028, H15-107, H16-047, v8-ask-006 (already denied; now
      hard blocks with the hook-file redirect), clean v3-good-053, H12-124, H16-078 (code that prints, never deletes)
  2 xargs-written-file | BV180509 (bad, an undo point) | xargs fed by `cat FILE` of a file this command wrote reads its
      text | planted v3-bad-080, H16-012
  3 code-env-inherited | BV180903 (bad, an undo point) | what interpreter code sets in its environment is exported in front
      of every command it spawns | planted HD025, HK017 (both an undo point under v18: fixed too), clean BV15237,
      BV16059, BV17040 (a scripted commit with no switch)
  4 push-dry-run | BV180238 (safe, a false block; right verdict UNDO, ./gradlew is unread) | git push -n / --dry-run with
      every word literal is not a remote write in version 8's sort | planted DV14-067, K17, v3-bad-016, v3-bad-022 (a
      push with a hidden word stays a remote write)
  5 worktree-prune-dry | BV180244 (safe, a false block; right verdict UNDO, npm run is unread) | git worktree prune -n
      writes nothing | clean H17-126, planted H17-021, K10-057
  6 hookspath-own-dir | BV181046 (safe, a false block; right verdict UNDO, pnpm lint is unread) | git config
      core.hooksPath .githooks is the policy's own setup, not a .git/config write to restore | clean H45, R041, planted
      H21, R013, D018
  7 url-string-value | BV180517, BV181030 (safe, false blocks) | a string in interpreter code that is one URL is a value,
      never a command (it was read as a script path) | planted BV180650, BV180108
  8 js-spawn-argv | BV180901 (safe, a false block; right verdict UNDO, npm run is unread) | spawn / execFileSync with a
      literal program and a literal list is that command in version 8's sort | clean V17-011, BV15226, planted BV17084,
      V17-010, v3-bad-254
  9 login-shell | BV180399 (safe, a false block) | "$SHELL" that the command does not set is the login shell, so
      "$SHELL" -c TEXT is sh -c TEXT | NO PLANTED ROW: no row on disk runs a violation through "$SHELL"
 10 husky-one-check | BV180786 (safe, a false block) | husky add/set of ONE real check is an edit of the hook by name |
      clean BV180153, BV17061; NO PLANTED ROW: no row on disk holds a husky add that disarms
 11 py-hook-by-name | BV180292, BV180355 (safe, false blocks), BV180296 (safe, an undo point) | Python whose every hook
      write is os.chmod(P, os.stat(P).st_mode | stat.S_IX*) or P.write_text(P.read_text().replace(A, B)) with a by-name
      swap, or that only reads a hook, is chmod +x, sed s/A/B/ or cat | clean G047, D055 (fixed too), planted BV180872
      (the same chmod with & ~exec bits), M070, H19CP033, BV180220, BV180681, H15-050, BV16150
 12 sed-edit-back | BV180999 (safe, a false block) | `sed SCRIPT HOOK > FILE` then `cat FILE > HOOK` is sed -i, judged by
      sed's own test | planted BV180112, BV180600 (sed edits that weaken a hook)
 13 child-env | BV180863 (safe, an undo point) | a variable this command exported with a literal value is known inside a
      child sh -c | planted BV180152

LABEL NOT CHANGED, VERDICT KEPT: BV180697 (`git -C charts/api add -A && helm lint charts/api`) is labelled allow, but
`git add -A` with no pathspec stages the whole worktree from any directory (git 2.x), and the policy's stop list names
-A; v19 keeps the deny and this tool asserts it.

LEFT OUT (no row on disk to prove them): git lfs read-only subcommands in version 8's sort (BV180517's real cause was
the URL), the cp and mv routes of class 12, and the ruby and perl branches of class 1 (written with the class, proved by
no row). LEFT AS DESIGNED: blind_v18's other safe rows on an undo point are a recipe or script that is only on disk
when the hook names no cwd (version 12) or a named-file discard (version 14).

Blind to: any command shape no case in cases/, blind_v15, blind_v16, blind_v17 or blind_v18 holds; a rule's cost on the
private real traffic (not in this repo); any tool other than Bash; and whether a sealed label is right. A mutation
proves a test can see its rule being removed; it does not prove the rule is complete.
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
import v18_check as V18                                     # noqa: E402  (v17's sha, blind_v17's path and lock)

PINNED_ROOT = V15.PINNED_ROOT
V14_SHA256 = V15.V14_SHA256
V15_SHA256 = V16.V15_SHA256
V16_SHA256 = V17.V16_SHA256
V17_SHA256 = V18.V17_SHA256
V18_SHA256 = "c0d6d450173635cd7831ab8ba960944182c03dffff7c25ff1871a5c08898ff8c"   # guard_v18.py when v19 was started
BLIND_V15, BLIND_V15_SHA256 = V16.BLIND_V15, V16.BLIND_V15_SHA256
BLIND_V16, BLIND_V16_SHA256 = V17.BLIND_V16, V17.BLIND_V16_SHA256
BLIND_V17, BLIND_V17_SHA256 = V18.BLIND_V17, V18.BLIND_V17_SHA256
BLIND_V18 = "docs/evidence/blind_v18/blind_v18_set.jsonl"
BLIND_V18_SHA256 = "850db1791717592654f011be1f4d7b25cd51a366f1c7ea77d02563c715a667a0"   # its LOCK.txt
DEV_V19 = "cases/dev_v19.jsonl"
CASE_SETS = list(V18.CASE_SETS) + [("dev_v19", DEV_V19)]
NEVER_READ = ("blind_v19", "bv19")                          # the next blind set: no path this tool opens may hold it
RANK = V15.RANK
verdict, rows_of, load_module = V15.verdict, V15.rows_of, V15.load_module
compare_all, regressions, run_mutation = V16.compare_all, V16.regressions, V16.run_mutation
GUARD_ARG = sys.argv[sys.argv.index("--guard") + 1] if "--guard" in sys.argv else None

# the verdict each dev row must get from v19 when it is not the plain best (planted DENY, clean allow): a recipe or
# script the hook cannot read with no cwd is an undo point (version 12), so these clean rows' right verdict is UNDO
WANT_OTHER = {"BV180238": "UNDO", "BV180244": "UNDO", "BV181046": "UNDO", "BV180901": "UNDO"}
# blind_v18 rows v18 got wrong (and two safe rows it left on an undo point) and the verdict v19 must give
BLIND_V18_FIXED = {"BV180098": "DENY", "BV180509": "DENY", "BV180903": "DENY",
                   "BV180238": "UNDO", "BV180244": "UNDO", "BV181046": "UNDO", "BV180901": "UNDO",
                   "BV180292": "allow", "BV180355": "allow", "BV180399": "allow", "BV180517": "allow",
                   "BV180786": "allow", "BV180999": "allow", "BV181030": "allow",
                   "BV180296": "allow", "BV180863": "allow"}
BLIND_V18_KEPT = {"BV180697": "DENY"}                       # labelled allow; the label is wrong under the rules
# every row of every existing set that may change v18 -> v19, and how (dev_v19's own copies are checked by class)
EXPECTED_CHANGES = {("holdout11", "D055"): ("UNDO", "allow"), ("holdout11", "G047"): ("UNDO", "allow"),
                    ("holdout13", "HD025"): ("UNDO", "DENY"), ("holdout13", "HK017"): ("UNDO", "DENY")}
# rows both deny whose redirect shape changes: a node delete of a hook is now its shell form's hard block
EXPECTED_SHAPES = {"v8-ask-006", "H6-028", "H15-107", "H16-047"}

_OFF = "    if False:\n"
# ---- mutations. Each changes ONE thing in a temp copy of guard_v19.py; a dev row of the class must get worse
# ("bad": a planted row no longer denied; "good": a clean row worse than its wanted verdict) ----
MUTATIONS = [
    ("other-lang-delete", "the node, ruby and perl delete reader is switched off",
     "    for sh in _py_delete_shell(code, lang) + _other_delete_shell(code, lang):",
     "    for sh in _py_delete_shell(code, lang):", "bad"),
    ("xargs-written-file", "xargs no longer reads a file this command wrote",
     "                    lit = _written_eval(upstream, st)   # version 19",
     "                    lit = None   # version 19", "bad"),
    ("code-env-inherited", "the code's own environment is not handed to what it spawns",
     "    envs = _code_env(code, lang)  ", "    envs = []  ", "bad"),
    ("push-dry-run", "the rule is switched off (a dry-run push is a remote write again)",
     "    if sub == \"push\" and _push_dry_only(rest):      # version 19 (blind_v18 BV180238)\n        return None\n",
     "", "good"),
    ("push-dry-run", "the rule is widened (any push, hidden words and all, is called a dry run)",
     "    if not rest or not all(_lit3(x) and FOUND not in x for x in rest):\n        return False\n"
     "    a2 = _canon_args(\"push\", rest)",
     "    return True\n    a2 = _canon_args(\"push\", rest)", "bad"),
    ("worktree-prune-dry", "the rule is switched off",
     " and not _worktree_prune_dry(rest):", ":", "good"),
    ("hookspath-own-dir", "the rule is switched off",
     "    if sub == \"config\" and _hookspath_ok_set(rest, gcwd):     # version 19 (blind_v18 BV181046)\n"
     "        return None\n", "", "good"),
    ("url-string-value", "a URL string is a command candidate again",
     " and not _URL_WORD.match(s)]", "]", "good"),
    ("js-spawn-argv", "the program-plus-list reading is switched off",
     "            items = items[:1] + _js_list_items(items[1])      # version 19 (blind_v18 BV180901)\n",
     "            pass\n", "good"),
    ("login-shell", "$SHELL is unknown again",
     "                return LOGIN_SHELL      # version 19", "                return None      # version 19", "good"),
    ("husky-one-check", "the rule is switched off",
     "    if b == \"husky\" and _husky_adds_check(args, cwd):\n", _OFF, "good"),
    ("py-hook-by-name", "the rule is switched off",
     "            if _py_hook_edit_only(code, lang, st.cwd):\n", "            if False:\n", "good"),
    ("py-hook-by-name", "code that writes no hook is no longer read as a reader",
     "        return True             # it reads a hook", "        return False            # it reads a hook", "good"),
    ("py-hook-by-name", "the chmod mode test is dropped (any os.chmod of the hook counts)",
     "            if p is not None and len(parts) >= 2 and sum(1 for x in parts if st_mode_of(x, p)) == 1 and \\\n"
     "                    all(st_mode_of(x, p) or exec_bit(x) for x in parts):",
     "            if p is not None:", "bad"),
    ("sed-edit-back", "the rule is switched off",
     "                    _sed_edit_back(args[0], tgt, st):\n", "                    False:\n", "good"),
    ("child-env", "a child sh -c no longer sees exported names",
     "                kn = st.r.child_env.get(code) if b != \"fish\" else None",
     "                kn = None", "good"),
]


def guard_path():
    return os.path.abspath(GUARD_ARG) if GUARD_ARG else os.path.join(HERE, "variants", "guard_v19.py")


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
    """dev_v19's rows, each checked against the row it was copied from: -> (rows, [problems])."""
    rows, problems = rows_of("dev_v19", DEV_V19), []
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
    return CASE_SETS + [("blind_v15", BLIND_V15), ("blind_v16", BLIND_V16), ("blind_v17", BLIND_V17)]


def self_test():
    results = []
    gpath = guard_path()

    def check(ok, label):
        results.append((bool(ok), label))
        if "--verbose" in sys.argv:
            print("  ", "ok  " if ok else "FAIL", label)
        elif not ok:
            print("  FAIL:", label)

    # 0. v14..v18 were not edited, every guard measured the pinned root, the four spent blind sets are locked
    for f, want in (("variants/guard_v14.py", V14_SHA256), ("variants/guard_v15.py", V15_SHA256), ("variants/guard_v16.py", V16_SHA256),
                    ("variants/guard_v17.py", V17_SHA256), ("variants/guard_v18.py", V18_SHA256)):
        sha = hashlib.sha256(open(os.path.join(HERE, f), "rb").read()).hexdigest()
        check(sha == want, "%s is unchanged byte for byte (sha256 %s)" % (f, sha[:12]))
    g14 = load_module("g14", os.path.join(HERE, "variants", "guard_v14.py"))
    g15 = load_module("g15", os.path.join(HERE, "variants", "guard_v15.py"))
    g16 = load_module("g16", os.path.join(HERE, "variants", "guard_v16.py"))
    g17 = load_module("g17", os.path.join(HERE, "variants", "guard_v17.py"))
    g18 = load_module("g18", os.path.join(HERE, "variants", "guard_v18.py"))
    g19 = load_module("g19", gpath)
    check(all(g._root() == PINNED_ROOT for g in (g14, g15, g16, g17, g18, g19)),
          "every guard measured the pinned root " + PINNED_ROOT)
    for rel, want, label in ((BLIND_V15, BLIND_V15_SHA256, "blind_v15"), (BLIND_V16, BLIND_V16_SHA256, "blind_v16"),
                             (BLIND_V17, BLIND_V17_SHA256, "blind_v17"), (BLIND_V18, BLIND_V18_SHA256, "blind_v18")):
        _, sha, ok = _locked_rows(rel, want)
        check(ok, "%s is the locked file (sha256 %s)" % (label, sha[:12]))
    check(all(not any(n in rel for n in NEVER_READ) for _, rel in all_sets() + [("b18", BLIND_V18)]),
          "no set this tool reads is the next blind set")

    # 1. dev_v19: every row a byte-for-byte copy of a row on disk; planted denied, clean at its wanted verdict
    dev, problems = dev_rows()
    for p in problems:
        check(False, p)
    check(not problems and dev, "every dev_v19 row (%d) is a byte-for-byte copy of the row it names" % len(dev))
    classes = collections.OrderedDict()
    for r in dev:
        classes.setdefault(r["class"], []).append(r)
    check(len(classes) == 13, "dev_v19.jsonl holds 13 classes (holds %d)" % len(classes))
    check(len(set(r["id"] for r in dev)) == len(dev), "dev_v19 ids are unique")
    check(sum(1 for r in dev if r["bad"]) >= 5 and sum(1 for r in dev if not r["bad"]) >= 5,
          "dev_v19 holds at least 5 planted and 5 clean rows (%d planted, %d clean)" % (
              sum(1 for r in dev if r["bad"]), sum(1 for r in dev if not r["bad"])))
    v18_of, v19_of = {}, {}
    for r in dev:
        v18_of[r["id"]], v19_of[r["id"]] = verdict(g18, r["command"]), verdict(g19, r["command"])
        check(v19_of[r["id"]] == want_of(r), "v19 %s %s = %s %s (%s, want %s)" % (
            "denies planted" if r["bad"] else "clean", r["id"], r["from_file"].split("/")[-1], r["from_id"],
            v19_of[r["id"]], want_of(r)))
    # 2. red was reachable: the rows v18 got wrong are the ones v19 gets right; no other dev row moved
    fixed = sorted(r["from_id"] for r in dev if v18_of[r["id"]] != want_of(r) and v19_of[r["id"]] == want_of(r))
    want_fixed = sorted({"BV180098", "BV180509", "BV180903", "HD025", "HK017", "BV180238", "BV180244", "BV181046",
                         "BV180517", "BV181030", "BV180901", "BV180399", "BV180786", "BV180292", "BV180355",
                         "BV180296", "G047", "D055", "BV180999", "BV180863"})
    check(fixed == want_fixed, "red reachable: v18 wrong, v19 right on exactly the %d rows the class table names (%s)" % (
        len(want_fixed), sorted(set(fixed) ^ set(want_fixed)) or "all of them"))
    moved = [r["from_id"] for r in dev if v18_of[r["id"]] != v19_of[r["id"]] and r["from_id"] not in want_fixed]
    check(not moved, "no other dev_v19 row changes verdict v18 -> v19 (%s)" % (moved or "none"))
    # 3. every deny carries a redirect whose alternatives v19 allows, and the hook form agrees with decide_full
    for r in dev:
        d = g19.decide_full(r["command"])
        if d["verdict"] == "deny":
            ok = bool(d["alternatives"]) and all(g19.decide(a)[0] == "allow" for a in d["alternatives"])
            check(ok and "DO THIS INSTEAD:" in d["reason"] and d["shape"] != "UNMATCHED",
                  "redirect of %s (%s) names alternatives v19 allows" % (r["id"], d["shape"]))
    for r in dev:
        out = subprocess.run([sys.executable, gpath], text=True, capture_output=True,
                             input=json.dumps({"tool_name": "Bash", "tool_input": {"command": r["command"]}}),
                             env=dict(os.environ, AGENT_GUARD_UNDO="0", PYTHONPATH=HERE)).stdout
        d = g19.decide_full(r["command"])
        denied = '"permissionDecision": "deny"' in out
        check(denied == (d["verdict"] == "deny" or d["origin"] == "recoverable"), "hook form agrees on %s" % r["id"])
    # 4. mutations: switch a rule off (its red row returns) or widen it (a planted row is let through)
    work = tempfile.mkdtemp(prefix="agb-v19-mut-")
    try:
        for cls, what, old, new, side in MUTATIONS:
            crow = [r for r in dev if r["class"] == cls]
            got, err = run_mutation(old, new, crow, work, gpath)
            if err:
                check(False, "mutation (%s: %s): %s" % (cls, what, err))
                continue
            if side == "bad":
                flipped = [r["from_id"] for r in crow if r["bad"] and v19_of[r["id"]] == "DENY" and got[r["id"]] != "DENY"]
            else:
                flipped = [r["from_id"] for r in crow if not r["bad"] and v19_of[r["id"]] == want_of(r)
                           and RANK[got[r["id"]]] > RANK[want_of(r)]]
            check(flipped, "mutation (%s: %s) turns %s red" % (cls, what, flipped[:3] or "NOTHING"))
        check({m[0] for m in MUTATIONS} == set(classes), "every class has at least one mutation")
        # 5. a deliberately broken v19 reads red: one that allows everything, and v18 itself standing in for v19
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
            red_reg = len(regressions(compare_all(g18, gb, CASE_SETS[:4])))
            check(red_dev > 0 and red_reg > 0, "a deliberately broken v19 (allows everything) reads red: %d planted rows "
                                                "missed, %d regressions on 4 sets" % (red_dev, red_reg))
        else:
            check(False, "the broken-guard anchor was not found once")
        red18 = sum(1 for r in dev if verdict(g18, r["command"]) != want_of(r))
        check(red18 > 0, "v18 standing in for v19 reads red on %d dev_v19 rows" % red18)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    # 6. no regression on any set under cases/, blind_v15, blind_v16 or blind_v17 (v18 -> v19, and v17..v14 -> v19)
    res = compare_all(g18, g19, all_sets())
    reg = regressions(res)
    check(not reg, "no row of any existing set is worse under v19 than v18 (%d regressions: %s)" % (
        len(reg), [x[1] for x in reg][:5]))
    changed = {(n, x[0]): (x[2], x[3]) for n, e in res.items() for x in e["changed"] if n != "dev_v19"}
    check(changed == EXPECTED_CHANGES, "outside dev_v19 the only rows that change are D055, G047 (UNDO -> allow) and "
                                       "HD025, HK017 (UNDO -> DENY) (%s)" % (
                                           sorted(set(changed.items()) ^ set(EXPECTED_CHANGES.items())) or "exactly"))
    shapes = {x[0] for n, e in res.items() for x in e["shapes"] if n != "dev_v19"}
    check(shapes == EXPECTED_SHAPES, "the only redirect shapes that change on rows both deny are the four node hook "
                                     "deletes, now B-hook-file (%s)" % (sorted(shapes ^ EXPECTED_SHAPES) or "exactly"))
    for name, e in res.items():
        od, ou = e["safe"][("old", "DENY")], e["safe"][("old", "UNDO")]
        nd, nu = e["safe"][("new", "DENY")], e["safe"][("new", "UNDO")]
        check(nd <= od and nd + nu <= od + ou, "%s: safe denied, and safe denied plus on an undo point, do not rise "
                                               "(%d/%d -> %d/%d)" % (name, od, ou, nd, nu))
    for old_name, g_old in (("v17", g17), ("v16", g16), ("v15", g15), ("v14", g14)):
        r2 = regressions(compare_all(g_old, g19, all_sets()))
        r_old = regressions(compare_all(g_old, g18, all_sets()))
        new_reg = sorted(set((x[0], x[1]) for x in r2) - set((x[0], x[1]) for x in r_old))
        check(not new_reg, "no row is worse under v19 than %s unless it already was under v18 (%d new: %s)" % (
            old_name, len(new_reg), new_reg[:5]))
    rows19 = {r["id"]: r for r in rows_of("holdout19", "cases/holdout19")}
    for rid, (kind, want) in sorted(V15.H19_EXPECT.items()):
        got = verdict(g19, rows19[rid]["command"])
        check(got == want, "holdout19 %s (%s) stands at %s under v19 as under v15 (is %s)" % (rid, kind, want, got))
    # 7. blind_v18 (SEEN): the rows v19 was built on are right, the disputed label keeps its deny, nothing else moves
    brows, _, _ = _locked_rows(BLIND_V18, BLIND_V18_SHA256)
    bmap = {r["id"]: r for r in brows}
    check(all(i in bmap for i in list(BLIND_V18_FIXED) + list(BLIND_V18_KEPT)), "every listed blind_v18 id exists")
    for rid, want in sorted(list(BLIND_V18_FIXED.items()) + list(BLIND_V18_KEPT.items())):
        got = verdict(g19, bmap[rid]["command"])
        check(got == want, "blind_v18 %s (%s, SEEN) is %s under v19 (want %s, v18 %s)" % (
            rid, "bad" if bmap[rid]["bad"] else "safe", got, want, verdict(g18, bmap[rid]["command"])))
    moved = [r["id"] for r in brows if r["id"] not in BLIND_V18_FIXED
             and verdict(g19, r["command"]) != verdict(g18, r["command"])]
    check(not moved, "no other blind_v18 row changes verdict v18 -> v19 (%s)" % (moved[:5] or "none"))
    # 8. no decision takes a second: bench.py's pathological seeds (v16's list, imported), and every row of every set
    w, head, n = V16.pathological_timing(g19)
    check(w < 1.0, "no decision takes 1 s on %d pathological inputs (slowest %.3f s: %r)" % (n, w, head))
    slow, nrows = (0.0, ""), 0
    for name, rel in all_sets():
        for r in rows_of(name, rel):
            t = time.perf_counter()
            g19.decide(r["command"])
            dt = time.perf_counter() - t
            nrows += 1
            if dt > slow[0]:
                slow = (dt, r["id"])
    for r in brows:
        t = time.perf_counter()
        g19.decide(r["command"])
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
    g18 = load_module("g18", os.path.join(HERE, "variants", "guard_v18.py"))
    g19 = load_module("g19", guard_path())
    if "--diff" in argv:
        V16.print_diff(compare_all(g18, g19, all_sets()), "v18", "v19")
        return 0
    if "--blind-seen" in argv:
        blind_report([("v18", g18), ("v19", g19)], BLIND_V18, BLIND_V18_SHA256, "blind_v18")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
