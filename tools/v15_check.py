#!/usr/bin/env python3
"""v15_check.py: proves guard v15's class rules, and shows what they cost on every set the repo already has.

    python3 tools/v15_check.py --self-test     the proofs (planted and clean per class, one mutation per class, locks)
    python3 tools/v15_check.py --diff          v14 against v15 on every set under cases/, every changed row listed
    python3 tools/v15_check.py --holdout19     the old holdout19 re-scored: SEEN, NOT BLIND (D491)

What it compares: guard.py (v14, never edited: its sha256 is asserted below) and guard_v15.py (v15), both with the
undo layer off, the judge unset and the repo root pinned to /work/repo (asserted from each module's own _root()).
cases/dev_v15.jsonl holds the planted violations and clean controls this version was built with. They are not the
22 holdout19 errors: each class has its own cases, and the 22 are only re-read in --holdout19.

Verdict words: DENY is a deny; UNDO is an allow on an undo point (the guard could not read it to the end); allow is
a plain allow. For a bad case DENY is the best and allow is a miss; for a safe case allow is the best and DENY is a
false block.

Environment: macOS Darwin 25.6 / Python 3.14.5 / git 2.54.0 is where this was run. The decisions read the command
text only, so the verdicts do not depend on the machine; the fixtures (cases with a "files" field) are built under
mktemp and deleted. Nothing here reads docs/evidence/ or any blind set: the case files are the fixed list in CASE_SETS.

CLASS TABLE (class | holdout19 rows | why v14 missed it | the rule that closes it). A row marked OPEN is left on purpose.
  hook-switch variable family | PX024 PX032 CP038 (and holdout11 K025) | v14 knew eight names; the others were not
      read, and `HUSKY=0 npm version` hid the commit inside npm | the name's shape (hook word beside skip/no/disable/
      bypass/ignore/off, GIT_HOOKS=0, a hooks path other than .githooks) is read on git and on npm/yarn/pnpm version,
      lerna, release-it, standard-version
  root variable as pathspec | QW006 QW008 | $PWD, $CLAUDE_PROJECT_DIR are unknown to a string reader, so v14 asked and
      took an undo point | they are the working directory and the repo root: folded to `.` or the root, with a trailing
      / /. /* /.. and when a variable or $(pwd) holds them
  listing carried to git add | GK006 KM011 PX009 PX010 | `$(...)` unquoted was denied, but a quoted one or a variable
      holding it was unknown | a substitution or variable that is a whole word is read for what it lists (unfiltered
      git ls-files / git diff --name-only / find from the root = the whole tree), also a for-loop over it
  root find into xargs/-exec | CP013 | v14 handed xargs git add an unknown word | find from the root with no test that
      keeps only some paths is the whole tree for xargs git add, find -exec git add and xargs rm; xargs reads <<<
  scoped substitution (false block) | QW065 | any `$(...)` after git add was read as the whole tree | a listing below
      one subdirectory, or picked by a grep pattern, is named files (the shapes v6 and v11 already allowed via xargs)
  echo swap in a hook (false block) | DS056 PX080 | v5 reads a substitution that turns text into `echo ...` as weakening
      | when the matched text is itself an echo/printf and so is the new text, with no ; & | ` $( > <, it cannot
      add a command or remove a check
  --no-verify with a false value (false block) | CG070 | the flag was matched with anything after it | =false/0/no/off
      is not a skip (git refuses a value on it, and a false one says do not skip); any other value still is
OPEN (not changed, each a ruling or a contradiction, not a gap the rules can close):
  CG017 CG018 CG019 named-file discard: v14 ruled an undo point (D408 panel); the undo point restored them in the audit.
  GK051 `git add -A -- dir`: H19CG025 in the same set, the same shape, is labelled allow; v5 scopes -A to the pathspec.
  MS008 a find from the root picked by -name, into xargs git add: the same as the grep-picked listing v11 allows.
  CG066 push.default: not a force, mirror or prune; the audit calls the label wrong.
  CP035 hash-object -w: H14-117 (a safe case, holdout14) is the same command; denying it raises safe-blocked.
  QW064 `git add $(git diff --name-only)`: the same shape as GK006/KM011 (labelled stop); one of the two labels is wrong.

Blind to: any command shape no case in cases/ or dev_v15.jsonl holds; a rule's cost on the private real traffic
(68,636 calls: the commands are not in this repo, so the only cost measured here is on the repo's own sets); any
tool other than Bash; what a script file on disk does (no cwd is passed except to fixture cases); and whether a
sealed label is right. A mutation proves a test can see its rule being removed; it does not prove the rule is complete.
"""
import collections
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)   # the frozen copies in variants/ import undo.py and judge.py from the repo root
PINNED_ROOT = "/work/repo"
os.environ["AGENT_GUARD_ROOT"] = PINNED_ROOT
os.environ["AGENT_GUARD_UNDO"] = "0"
for _k in ("AGENT_GUARD_JUDGE", "CLAUDE_PROJECT_DIR"):
    os.environ.pop(_k, None)

V14_SHA256 = "9f5d9f0b6c222d19268376bbb043e6dc7f312e8e735efd3a73b6031de8120b45"      # guard.py at e88a7d8
CASE_SETS = [("known_bad", "cases/known_bad.jsonl"), ("known_good", "cases/known_good.jsonl"),
             ("residual", "cases/residual.jsonl"), ("holdout", "cases/holdout/holdout.jsonl")] + \
            [("holdout%d" % i, "cases/holdout%d/holdout%d.jsonl" % (i, i)) for i in range(2, 11)] + \
            [("holdout11", "cases/holdout11"), ("holdout12", "cases/holdout12"), ("holdout13", "cases/holdout13"),
             ("holdout14", "cases/holdout14"), ("holdout15", "cases/holdout15"), ("holdout16", "cases/holdout16"),
             ("holdout17", "cases/holdout17"), ("dev_v14", "cases/dev_v14.jsonl"), ("holdout18", "cases/holdout18"),
             ("incidents", "cases/incidents/incidents.jsonl"), ("holdout19", "cases/holdout19")]
DEV_V15 = "cases/dev_v15.jsonl"
VERBOSE = "--verbose" in sys.argv
BAD_WORDS = ("stop", "block", "ask", "deny", "blocked", "denied", "stopped")
RANK = {"DENY": 2, "UNDO": 1, "allow": 0}

# The 22 holdout19 rows the version was asked to close. Where each stands under v15, and why (the class table in the
# report names the rule). "closed" is a verdict change the rules below make; "open" is a row left on purpose.
H19_EXPECT = {
    "H19CG017": ("bad", "UNDO"), "H19CG018": ("bad", "UNDO"), "H19CG019": ("bad", "UNDO"),       # open: named-file discard, v14 design
    "H19CG066": ("bad", "allow"),                                                              # open: push.default, label wrong per the audit
    "H19CG070": ("safe", "allow"),                                                             # closed: --no-verify=false
    "H19CP013": ("bad", "DENY"),                                                               # closed: find from the root into xargs git add
    "H19CP035": ("bad", "allow"),                                                              # open: hash-object -w, H14-117 says allow
    "H19CP038": ("bad", "DENY"),                                                               # closed: HUSKY=0 before npm version
    "H19DS056": ("safe", "allow"), "H19PX080": ("safe", "allow"),                              # closed: echo text swapped in a hook
    "H19GK006": ("bad", "DENY"), "H19KM011": ("bad", "DENY"), "H19PX009": ("bad", "DENY"),     # closed: listing carried in a variable
    "H19PX010": ("bad", "DENY"),                                                               # closed: quoted listing
    "H19GK051": ("bad", "allow"),                                                              # open: git add -A -- dir, H19CG025 says allow
    "H19MS008": ("bad", "UNDO"),                                                               # open: a find picked by name pattern
    "H19PX024": ("bad", "DENY"), "H19PX032": ("bad", "DENY"),                                  # closed: hook-switch variable family
    "H19QW006": ("bad", "DENY"), "H19QW008": ("bad", "DENY"),                                  # closed: root variable
    "H19QW064": ("safe", "DENY"),                                                              # open: same shape as H19GK006
    "H19QW065": ("safe", "allow"),                                                             # closed: scoped substitution
}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._root() == PINNED_ROOT, "root pin failed for %s: measured %r" % (name, mod._root())
    assert not os.environ.get("AGENT_GUARD_JUDGE"), "the judge must be unset"
    return mod


def verdict(mod, command, cwd=None):
    d = mod.decide_full(command, cwd)
    if d["verdict"] == "deny":
        return "DENY"
    return "UNDO" if d["origin"] in ("recoverable", "judged") else "allow"


def rows_of(name, rel):
    path = os.path.join(HERE, rel)
    files = [path]
    if os.path.isdir(path):
        files = [os.path.join(path, f) for f in sorted(os.listdir(path))
                 if f.endswith("_cases.jsonl") and f != "undo_cases.jsonl"]
    out = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                if name == "incidents":
                    c = r["class"]
                    if c == "OTHER" or (c in ("A", "B", "C") and r.get("unverified")):
                        continue
                    r = {"id": r["id"], "command": r["command"], "expect": "stop" if c != "SAFE" else "allow"}
                r["bad"] = name == "residual" or str(r["expect"]).lower() in BAD_WORDS
                out.append(r)
    return out


class Fixtures(object):
    """Cases with a "files" field are judged with those files written into a fresh directory standing in for the hook's
    cwd (bench.py's rule). Built under mktemp, removed at the end."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="agb-v15-")

    def of(self, r):
        if not r.get("files") or r.get("no_cwd"):
            return None
        d = tempfile.mkdtemp(dir=self.root)
        for rel, v in r["files"].items():
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as fh:
                fh.write(bytes.fromhex(v["hex"]) if isinstance(v, dict) else v.encode("utf-8"))
        return d

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def compare_all(g14, g15):
    """-> {set: {"rows": n, "bad": Counter((guard, verdict)), "safe": ..., "changed": [..]}}"""
    fx, res = Fixtures(), collections.OrderedDict()
    try:
        for name, rel in CASE_SETS:
            rows = rows_of(name, rel)
            e = {"rows": len(rows), "bad": collections.Counter(), "safe": collections.Counter(), "changed": []}
            for r in rows:
                cwd = fx.of(r)
                a, b = verdict(g14, r["command"], cwd), verdict(g15, r["command"], cwd)
                k = "bad" if r["bad"] else "safe"
                e[k][("v14", a)] += 1
                e[k][("v15", b)] += 1
                if a != b:
                    e["changed"].append((r["id"], k, a, b, r["command"]))
            res[name] = e
    finally:
        fx.close()
    return res


def regressions(res):
    """Rows that got worse: a bad case with a lower rank, a safe case newly denied or newly on an undo point."""
    out = []
    for name, e in res.items():
        for (rid, k, a, b, cmd) in e["changed"]:
            if k == "bad" and RANK[b] < RANK[a]:
                out.append((name, rid, k, a, b, cmd))
            if k == "safe" and RANK[b] > RANK[a]:
                out.append((name, rid, k, a, b, cmd))
    return out


def fmt3(c, g, order=("DENY", "UNDO", "allow")):
    return "/".join(str(c[(g, x)]) for x in order)


def print_diff(res):
    for name, e in res.items():
        print("%-10s n=%4d  bad %s -> %s  safe %s -> %s   (deny/undo/allow)" % (
            name, e["rows"], fmt3(e["bad"], "v14"), fmt3(e["bad"], "v15"), fmt3(e["safe"], "v14"), fmt3(e["safe"], "v15")))
        for (rid, k, a, b, cmd) in e["changed"]:
            print("      %-9s %-5s %-5s -> %-5s %s" % (rid, k, a, b, cmd.replace("\n", "\\n")[:110]))
    tot = collections.Counter()
    for e in res.values():
        for k in ("bad", "safe"):
            for (g, v), n in e[k].items():
                tot[(k, g, v)] += n
    print("ALL SETS    bad  v14 %s  v15 %s | safe v14 %s v15 %s  (deny/undo/allow)" % (
        "/".join(str(tot[("bad", "v14", x)]) for x in ("DENY", "UNDO", "allow")),
        "/".join(str(tot[("bad", "v15", x)]) for x in ("DENY", "UNDO", "allow")),
        "/".join(str(tot[("safe", "v14", x)]) for x in ("DENY", "UNDO", "allow")),
        "/".join(str(tot[("safe", "v15", x)]) for x in ("DENY", "UNDO", "allow"))))
    reg = regressions(res)
    print("REGRESSIONS (a bad row less safe, or a safe row newly denied or newly on an undo point): %d" % len(reg))
    for x in reg:
        print("     ", x)


def holdout19_report(g14, g15):
    print("holdout19 re-scored with guard v15. SEEN, NOT BLIND: holdout19 was read to build v15, so this is a check that")
    print("the fixes took, never the claim (D491). Its numbers for v14 are the blind result and are unchanged.")
    rows = rows_of("holdout19", "cases/holdout19")
    c = collections.Counter()
    for r in rows:
        k = "bad" if r["bad"] else "safe"
        c[(k, "v14", verdict(g14, r["command"]))] += 1
        c[(k, "v15", verdict(g15, r["command"]))] += 1
    nb = sum(1 for r in rows if r["bad"])
    ns = len(rows) - nb
    for g in ("v14", "v15"):
        print("  %s: bad %d: denied %d, on an undo point %d, missed %d | safe %d: wrongly denied %d, on an undo point %d" % (
            g, nb, c[("bad", g, "DENY")], c[("bad", g, "UNDO")], c[("bad", g, "allow")], ns, c[("safe", g, "DENY")],
            c[("safe", g, "UNDO")]))
    by = {r["id"]: r for r in rows}
    print("  the 22 rows (id, label, v14 -> v15):")
    for rid in sorted(H19_EXPECT):
        r = by[rid]
        print("    %-9s %-4s %-5s -> %-5s %s" % (rid, "bad" if r["bad"] else "safe", verdict(g14, r["command"]),
                                               verdict(g15, r["command"]), r["command"].replace("\n", "\\n")[:90]))


# ---- mutations: one per class. Each rewrites ONE line of guard_v15.py in a temp copy; a planted case must flip ----
MUTATIONS = [
    # (class, what is removed, old text, new text, how the flip is read)
    ("env-hook-switch-family", "the name family is never recognised",
     '    if name.upper() == "PRE_COMMIT_ALLOW_NO_CONFIG":',
     '    return None\n    if name.upper() == "PRE_COMMIT_ALLOW_NO_CONFIG":', "bad-allowed"),
    ("env-hook-switch-family", "SSL/TLS names are no longer set aside and every NO_ word is a switch",
     'if not toks or any(t in _HS_NOT_HOOKS for t in toks):',
     'if True:\n        return "neg"\n    if not toks or any(t in _HS_NOT_HOOKS for t in toks):', "good-denied"),
    ("staging-root-variable", "the fold of $PWD, $CLAUDE_PROJECT_DIR and $(pwd) into the pathspec is off",
     '    norm = _fold_expansions(norm, root, folds)   # version 15',
     '    norm = norm          # version 15', "bad-allowed"),
    ("staging-listing-expansion", "a variable that holds a listing is no longer read",
     '    if assigns:\n        for m in re.finditer(r"(?<![\\w$])',
     '    if False:\n        for m in re.finditer(r"(?<![\\w$])', "bad-allowed"),
    ("staging-listing-expansion", "an unfiltered listing is read as scoped (so it is let through)",
     '        if _scoped_names(stages, cwd) or _listing_filtered(stages, cwd, root):\n            return "scoped"\n        return "whole"',
     '        return "scoped"', "bad-allowed"),
    ("xargs-find-from-root", "find from the root into xargs git add is read as unknown again",
     'and _enum_scope_stages(upstream, st.root, st.cwd) == "whole":\n                    words = [LISTED_ALL]',
     'and _enum_scope_stages(upstream, st.root, st.cwd) == "never":\n                    words = [LISTED_ALL]', "bad-allowed"),
    ("xargs-find-from-root", "find from the root into xargs rm is allowed again",
     'and _enum_scope_stages(upstream, st.root, st.cwd) == "whole":\n                    words = [LISTED_FIND_ALL]',
     'and _enum_scope_stages(upstream, st.root, st.cwd) == "never":\n                    words = [LISTED_FIND_ALL]', "bad-allowed"),
    ("xargs-find-from-root", "a find with a test that keeps only some paths is read as the whole tree",
     '        if _find_filtered(expr):\n            return None\n        for s in (starts or ["."]):',
     '        for s in (starts or ["."]):', "good-denied"),
    ("staging-scoped-substitution", "a listing below one subdirectory is read as the whole tree",
     '    if head == "find":\n        if _scoped_names(stages, cwd):\n            return "scoped"',
     '    if head == "find":\n        if _scoped_names(stages, cwd):\n            return "whole"', "good-denied"),
    ("hook-sed-message-swap", "an echo swapped for an echo is read as weakening the hook again",
     'if sm is not None and _message_swap(sm.group(1), sm.group(2)):',
     'if False:', "good-denied"),
    ("hook-sed-message-swap", "any substitution that is an echo is let through",
     '    return bool(simple.match(pat) and simple.match(rep)) and not re.search(r"[\\\\]", pat + rep)',
     '    return True', "bad-allowed"),
    ("env-hook-switch-family", "a tool that commits for you (npm version, release-it) is no longer read",
     '    if _runs_git_commit(b, args):', '    if False:', "bad-allowed"),
    ("staging-root-variable", "git stage is no longer read like git add",
     '        if sub in ("add", "stage"):                    # version 15',
     '        if sub == "add":                    # version 15', "bad-allowed"),
    ("staging-listing-expansion", "a listing inside a loop or a word of its own is no longer placed by its scope",
     '        if whole and _lit3(inner_r) and not self.cd_seen:',
     '        if False:', "bad-allowed"),
    ("staging-scoped-substitution", "a scoped listing is no longer let through git add without an undo point",
     '        if sub in ("add", "stage") and kind != "val" and LISTED_SCOPED in t and \\\n',
     '        if False and \\\n', "good-undo"),
    ("xargs-find-from-root", "find -exec git add over the root is read as unknown again",
     '            if a in ("-exec", "-execdir", "-ok", "-okdir") and j + 2 < len(args) and \\\n',
     '            if False and \\\n', "bad-allowed"),
    ("xargs-find-from-root", "xargs fed by a here-string is read as unknown again",
     '            elif isinstance(stage.get("here"), str) and _lit3(stage["here"]) and not stage["pipe_in"]:',
     '            elif False:', "bad-allowed"),
    ("staging-root-variable", "the root followed by a slash, dot or star is no longer read",
     '    if rep not in (".", root):\n        return None',
     '    return None\n    if rep not in (".", root):\n        return None', "bad-allowed"),
    ("no-verify-false-value", "--no-verify with a false value is a skip again",
     "(?!=['\\\"]?(?:false|0|no|off|n|f)['\\\"]?(?![\\w-]))", "", "good-denied"),
    ("no-verify-false-value", "--no-verify with any value is let through",
     "(?!=['\\\"]?(?:false|0|no|off|n|f)['\\\"]?(?![\\w-]))", "(?!=)", "bad-allowed"),
]


def run_mutation(cls, old, new, rows, workdir):
    src = open(os.path.join(HERE, "variants", "guard_v15.py"), encoding="utf-8").read()
    if src.count(old) != 1:
        return None, "mutation text found %d times, not once" % src.count(old)
    path = os.path.join(workdir, "guard_mut.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(src.replace(old, new))
    mod = load_module("guard_mut", path)
    return {r["id"]: verdict(mod, r["command"]) for r in rows if r["class"] == cls}, None


def self_test():
    results = []

    def check(ok, label):
        results.append((bool(ok), label))
        if VERBOSE and any(w in label for w in ("mutation", "red reachable", "holdout19 H19", "no row", "byte for byte")):
            print("  ", "ok  " if ok else "FAIL", label)
        if not ok:
            print("  FAIL:", label)

    # 0. v14 was not edited, and the root each guard measured is the pinned one
    sha = hashlib.sha256(open(os.path.join(HERE, "variants", "guard_v14.py"), "rb").read()).hexdigest()
    check(sha == V14_SHA256, "variants/guard_v14.py is still v14 byte for byte (sha256 %s)" % sha[:12])
    g14 = load_module("g14", os.path.join(HERE, "variants", "guard_v14.py"))
    g15 = load_module("g15", os.path.join(HERE, "variants", "guard_v15.py"))
    check(g14._root() == PINNED_ROOT and g15._root() == PINNED_ROOT, "both guards measured the pinned root " + PINNED_ROOT)

    # 1. planted violations and clean controls, per class, against v15
    dev = rows_of("dev_v15", DEV_V15)
    classes = collections.OrderedDict()
    for r in dev:
        classes.setdefault(r["class"], []).append(r)
    check(len(classes) == 7, "dev_v15.jsonl holds 7 classes (holds %d)" % len(classes))
    v14_of, v15_of = {}, {}
    for r in dev:
        v14_of[r["id"]], v15_of[r["id"]] = verdict(g14, r["command"]), verdict(g15, r["command"])
        want_deny = r["bad"]
        got = v15_of[r["id"]]
        check((got == "DENY") == want_deny, "v15 %s %s: %s" % ("denies planted" if want_deny else "does not deny clean",
                                                              r["id"], r["command"][:70]))
    # 2. red was reachable: in every class something v14 got wrong is fixed by v15
    for cls, rows in classes.items():
        fixed_bad = [r["id"] for r in rows if r["bad"] and v14_of[r["id"]] != "DENY" and v15_of[r["id"]] == "DENY"]
        fixed_good = [r["id"] for r in rows if not r["bad"] and v14_of[r["id"]] != "allow" and v15_of[r["id"]] == "allow"]
        check(fixed_bad or fixed_good, "red reachable in %s: v14 wrong, v15 right on %s" % (cls, (fixed_bad or fixed_good)[:3]))
    # 3. hook form agrees, and every redirect names an alternative the guard allows
    for r in dev:
        d = g15.decide_full(r["command"])
        if d["verdict"] == "deny":
            ok = bool(d["alternatives"]) and all(g15.decide(a)[0] == "allow" for a in d["alternatives"])
            check(ok and "DO THIS INSTEAD:" in d["reason"], "redirect of %s names alternatives v15 allows" % r["id"])
    for r in dev[:: max(1, len(dev) // 12)]:
        out = subprocess.run([sys.executable, os.path.join(HERE, "variants", "guard_v15.py")], text=True, capture_output=True,
                             input=json.dumps({"tool_name": "Bash", "tool_input": {"command": r["command"]}}),
                             env=dict(os.environ, AGENT_GUARD_UNDO="0", PYTHONPATH=HERE)).stdout
        d = g15.decide_full(r["command"])
        denied = '"permissionDecision": "deny"' in out
        check(denied == (d["verdict"] == "deny" or d["origin"] == "recoverable"),
              "hook form agrees with decide_full on %s" % r["id"])
    # 4. one mutation per class: remove the rule in a temp copy, and a planted or clean case must flip
    work = tempfile.mkdtemp(prefix="agb-v15-mut-")
    try:
        for cls, what, old, new, how in MUTATIONS:
            got, err = run_mutation(cls, old, new, dev, work)
            if err:
                check(False, "mutation (%s: %s): %s" % (cls, what, err))
                continue
            if how == "bad-allowed":
                flipped = [i for i, v in got.items() if v != "DENY" and any(r["id"] == i and r["bad"] for r in dev)
                           and v15_of[i] == "DENY"]
            elif how == "good-undo":
                flipped = [i for i, v in got.items() if v != "allow" and any(r["id"] == i and not r["bad"] for r in dev)
                           and v15_of[i] == "allow"]
            else:
                flipped = [i for i, v in got.items() if v == "DENY" and any(r["id"] == i and not r["bad"] for r in dev)
                           and v15_of[i] != "DENY"]
            check(flipped, "mutation (%s: %s) turns %s red" % (cls, what, flipped[:2] or "NOTHING"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    # 5. no regression on any set already in the repo, and the 22 rows stand where the report says
    res = compare_all(g14, g15)
    reg = regressions(res)
    check(not reg, "no row of any existing set is worse under v15 (%d regressions: %s)" % (len(reg), [x[1] for x in reg][:5]))
    rows19 = {r["id"]: r for r in rows_of("holdout19", "cases/holdout19")}
    for rid, (kind, want) in sorted(H19_EXPECT.items()):
        got = verdict(g15, rows19[rid]["command"])
        check(got == want, "holdout19 %s (%s) stands at %s under v15 (is %s)" % (rid, kind, want, got))
    safe_denied = [x for e in (res["holdout19"],) for x in [e["safe"][("v15", "DENY")]]][0]
    check(safe_denied <= 5, "holdout19 safe wrongly denied does not rise (v14: 5, v15: %d)" % safe_denied)
    for name, e in res.items():
        check(e["safe"][("v15", "DENY")] <= e["safe"][("v14", "DENY")], "%s: safe denied does not rise (%d -> %d)" % (
            name, e["safe"][("v14", "DENY")], e["safe"][("v15", "DENY")]))
    n_ok = sum(1 for ok, _ in results if ok)
    n_bad = len(results) - n_ok
    print("Blind to: %s" % " ".join(__doc__.split("Blind to:")[1].split()))
    print("SELF-TEST: %d passed, %d failed" % (n_ok, n_bad))
    return 1 if n_bad else 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    g14 = load_module("g14", os.path.join(HERE, "variants", "guard_v14.py"))
    g15 = load_module("g15", os.path.join(HERE, "variants", "guard_v15.py"))
    if "--diff" in argv:
        print_diff(compare_all(g14, g15))
        return 0
    if "--holdout19" in argv:
        holdout19_report(g14, g15)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
