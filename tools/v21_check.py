#!/usr/bin/env python3
"""v21_check.py: proves guard v21's one class change, and shows what it costs on every set the repo already has.

    python3 tools/v21_check.py --self-test              the proofs (planted rows built in code, switch-off mutations,
                                                        v20 standing in for v21 must read red, locks, every set, timing)
    python3 tools/v21_check.py --self-test --guard F    the same proofs run against another file F (it must read red
                                                        unless F is v21: try variants/guard_v20.py)
    python3 tools/v21_check.py --diff                   v20 against v21 on every set under cases/ and blind_v15 to
                                                        blind_v20, every changed row listed, then every row of every
                                                        .jsonl file under cases/ (undo_cases too) and of the six blind
                                                        sets whose verdict OR origin differs
    python3 tools/v21_check.py --tables                 the before/after table (v20 and v21) for every one of those sets

THE CLASS (the founder's box, 2026-10-19, "Build v21 now (Recommended)": "Main finds the command type behind the 1,100,
fixes that one rule, and proves no loss on all six test sets."). Since version 16 a command that writes a script with a
heredoc (cat > /p/x.py <<'PYEOF' ... PYEOF) and then runs it (python3 /p/x.py; sh, bash, source; awk -f) is read whole,
but the written text was held to MAX_LITERAL (4,096 bytes), so a longer script was unknown and its run denied fail
closed. v21 = guard.py (v20) byte for byte plus one bound: text written to a file through a bare cat (a heredoc, tee,
cat of a file this command wrote) is known up to MAX_SCRIPT = 65,536 bytes. Over that it stays unknown and fails closed
as before. printf, echo and decoder output keep MAX_LITERAL, inside a written file too.

What it compares: variants/guard_v20.py (v20, sha256 asserted) against variants/guard_v21.py, both with the undo layer off, the judge unset and
the repo root pinned to /work/repo (tools/v15_check.py's environment, verdict and score method, imported, not copied).
DENY is a deny; UNDO is an allow on an undo point (origin recoverable or judged); allow is a plain allow.

NO COMMAND STRING IS WRITTEN TO ANY SET. The planted rows below are built in code at run time from a harmless filler
line repeated to a size, with one violating line put in the middle or at the end; they live only in memory. Mutations
change guard CODE only, in a temp copy.

Blind to: any command shape no case on disk or planted row here holds; the cost on the private real traffic (measured
outside this repo, aggregate only); and whether the reader is complete on a long script (a long script is judged by the
same reader as a short one, so it is exactly as complete as that reader is). TIME: the shell walk is superlinear on
some text (version 17's _ungroup rescans the whole text for every group it cannot rewrite), so a pathological script up
to 65,536 bytes can take seconds; a top-level command of the same bytes costs v20 the same (printed by --self-test).
"""
import base64
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
import v20_check as V20                                     # noqa: E402  (the sets, the shas, the blind_v19 lock)

sys.path.insert(0, HERE)
import bench                                                # noqa: E402  (PATHO_SEEDS and its pathological_timing)

PINNED_ROOT = V15.PINNED_ROOT
V20_SHA256 = "1f16f4606e53999958f99f807946b60a1ba7806193bbe94e59ddce8f784dbbad"   # guard.py when v21 was started; now variants/guard_v20.py
BLIND_V19, BLIND_V19_SHA256 = V20.BLIND_V19, V20.BLIND_V19_SHA256
BLIND_V20 = "docs/evidence/blind_v20/blind_v20_set.jsonl"
BLIND_V20_SHA256 = "dcf6cf6e406b1c8f889f009a212ee34bc289cfb73ee779b41daf4c4fc6efbfa4"   # its LOCK.txt
BLIND_LOCKS = ((V20.BLIND_V15, V20.BLIND_V15_SHA256), (V20.BLIND_V16, V20.BLIND_V16_SHA256),
               (V20.BLIND_V17, V20.BLIND_V17_SHA256), (V20.BLIND_V18, V20.BLIND_V18_SHA256),
               (BLIND_V19, BLIND_V19_SHA256), (BLIND_V20, BLIND_V20_SHA256))
RANK = V15.RANK
verdict, rows_of, load_module, Fixtures = V15.verdict, V15.rows_of, V15.load_module, V15.Fixtures
compare_all, regressions, run_mutation = V16.compare_all, V16.regressions, V16.run_mutation
GUARD_ARG = sys.argv[sys.argv.index("--guard") + 1] if "--guard" in sys.argv else None
MAX_SCRIPT, MAX_LITERAL = 65536, 4096
SLOW_S = 1.0                                                # the ruled bound for a planted row and a pathological input

# the v21 edits, each as (v20 text, v21 text): reverting them and dropping the VERSION 21 block must give v20 byte for byte
V21_EDITS = [
    ("MAX_LITERAL = 4096     # bytes of literal input or decoded output the guard will evaluate\n",
     "MAX_LITERAL = 4096     # bytes of literal input or decoded output the guard will evaluate\n"
     "MAX_SCRIPT = 65536     # version 21: bytes of text a command writes to a file (a heredoc through cat or tee) it reads\n"),
    ("def _eval_stages(stages, raw=False):\n", "def _eval_stages(stages, raw=False, limit=MAX_LITERAL):\n"),
    ("        data = _stage(s[\"argv\"], inp, raw)\n        if data is None or len(data) > MAX_LITERAL:\n"
     "            return None\n    return data\n",
     "        data = _stage(s[\"argv\"], inp, raw)\n        if data is None or len(data) > (limit if _passes_text(s[\"argv\"]) "
     "else MAX_LITERAL):\n            return None\n    return data\n\n\ndef _passes_text(argv):\n"
     "    \"\"\"Version 21: a bare cat, which hands on the heredoc or the text it reads unchanged (it decodes and prints nothing\n"
     "    new), so only text written to a file through it gets MAX_SCRIPT; every producer and decoder keeps MAX_LITERAL.\"\"\"\n"
     "    return len(argv) == 1 and posixpath.basename(argv[0]) == \"cat\"\n"),
    ("        data = \"\".join(parts)\n        for sg in stages[1:]:\n",
     "        data = \"\".join(parts)\n        if len(data) > MAX_SCRIPT:\n"
     "            return None                 # version 21: more than MAX_SCRIPT bytes stays unknown\n"
     "        for sg in stages[1:]:\n"),
    ("            data = _stage(sg[\"argv\"], data, True)\n            if data is None or len(data) > MAX_LITERAL:\n",
     "            data = _stage(sg[\"argv\"], data, True)\n            if data is None or len(data) > "
     "(MAX_SCRIPT if _passes_text(sg[\"argv\"]) else MAX_LITERAL):\n"),
    ("    return _eval_stages(stages, raw=True)\n",
     "    return _eval_stages(stages, raw=True, limit=MAX_SCRIPT)   # version 21: a script written whole, up to MAX_SCRIPT\n"),
]
V21_BLOCK_START = "\nVERSION 21. ONE CLASS, A SCRIPT WRITTEN WHOLE AND THEN RUN, OVER 4 KB"
V21_BLOCK_END = "\nBOUND, named not closed:"

# ---- planted rows, built in code (never written to a set) ----
PY_LINE = "total_%d = sum(range(%d))  # harmless arithmetic"
SH_LINE = "echo \"step %d of the build: %d\""
AWK_LINE = "NR == %d { n += %d }"
PY_BAD = (("rmtree", "import shutil; shutil.rmtree(\".git\")"),
          ("push", "import subprocess; subprocess.run([\"git\", \"push\", \"--force\"])"))
SH_BAD = (("push", "git push --force origin main"), ("rmgit", "rm -rf .git"), ("noverify", "git commit --no-verify -m x"),
          ("reset", "git reset --hard HEAD~1"), ("addall", "git add -A"))
AWK_BAD = (("push", "NR == 1 { system(\"git push --force origin main\") }"), ("rmgit", "NR == 2 { system(\"rm -rf .git\") }"))


def _fill(size, fmt):
    lines, n, i = [], 0, 0
    while n < size:
        lines.append(fmt % (i, i))
        n += len(lines[-1]) + 1
        i += 1
    return lines


def _body(size, fmt, bad=None, where="mid"):
    lines = _fill(size, fmt)
    if bad:
        k = len(lines) // 2 if where == "mid" else len(lines)
        lines = lines[:k] + [bad] + lines[k:]
    return "\n".join(lines)


def py_cmd(size, bad=None, where="mid"):
    return ("cat > /tmp/v21_job.py <<'PYEOF'\nimport os\n" + _body(size, PY_LINE, bad, where) + "\nprint('done')\nPYEOF\n"
            "python3 /tmp/v21_job.py")


def sh_cmd(size, bad=None, runner="bash", where="mid"):
    return ("cat > /tmp/v21_job.sh <<'SHEOF'\n#!/bin/sh\n" + _body(size, SH_LINE, bad, where) + "\nSHEOF\n" + runner +
            " /tmp/v21_job.sh")


def tee_cmd(size, bad=None):
    return "tee /tmp/v21_job.sh > /dev/null <<'SHEOF'\n" + _body(size, SH_LINE, bad) + "\nSHEOF\nsh /tmp/v21_job.sh"


def awk_cmd(size, bad=None):
    return ("cat > /tmp/v21_job.awk <<'AWKEOF'\n" + _body(size, AWK_LINE, bad) + "\nEND { print n }\nAWKEOF\n"
            "awk -f /tmp/v21_job.awk /tmp/v21_input.txt")


def catpipe_cmd(size, bad=None):
    return ("cat > /tmp/v21_job.py <<'PYEOF'\n" + _body(size, PY_LINE, bad) + "\nPYEOF\ncat /tmp/v21_job.py | python3 -")


def join_cmd(each, bad=None):
    """Two scripts each under MAX_SCRIPT, joined by cat into one over it."""
    return ("cat > /tmp/v21_a.py <<'PYEOF'\n" + _body(each, PY_LINE) + "\nPYEOF\n"
            "cat > /tmp/v21_b.py <<'PYEOF'\n" + _body(each, PY_LINE, bad) + "\nPYEOF\n"
            "cat /tmp/v21_a.py /tmp/v21_b.py > /tmp/v21_c.py\npython3 /tmp/v21_c.py")


def edge_cmd(data_len):
    """A heredoc whose text, as the guard holds it (the lines plus the closing newline), is exactly data_len bytes."""
    head = "import os\n"
    pad = data_len - 1 - len(head)
    body = head + ("x = 1  # " + "p" * pad)[:pad]
    return "cat > /tmp/v21_edge.py <<'PYEOF'\n" + body + "\nPYEOF\npython3 /tmp/v21_edge.py"


def kept_cmds(size):
    """Routes whose bound v21 keeps at MAX_LITERAL: a decoder, printf and echo writing the script."""
    code = _body(size, PY_LINE)
    b64 = base64.b64encode(code.encode()).decode()
    q = code.replace("'", "")
    return [("kept-base64-%d" % size, "echo " + b64 + " | base64 -d > /tmp/v21_job.py\npython3 /tmp/v21_job.py"),
            ("kept-printf-%d" % size, "printf '%s\\n' '" + q + "' > /tmp/v21_job.py\npython3 /tmp/v21_job.py"),
            ("kept-echo-%d" % size, "echo '" + q + "' > /tmp/v21_job.py\npython3 /tmp/v21_job.py")]


def planted():
    """-> [(id, command, want)] where want is ("is", V) for v21's verdict, ("v20", V) for v20's, ("reader",) for a deny
    that is NOT fail closed (the reader found the violation), ("same",) for v21 == v20 in verdict and origin."""
    out = []
    for size in (5000, 20000, 60000):
        k = "%dk" % (size // 1000)
        out.append(("py-%s-clean" % k, py_cmd(size), [("v20", "DENY"), ("is", "allow")]))
        for name, bad in PY_BAD:
            for where in ("mid", "end"):
                out.append(("py-%s-%s-%s" % (k, name, where), py_cmd(size, bad, where=where), [("is", "DENY"), ("reader",)]))
        for runner in ("bash", "sh", "source"):
            out.append(("%s-%s-clean" % (runner, k), sh_cmd(size, runner=runner), [("v20", "UNDO"), ("is", "allow")]))
            for name, bad in SH_BAD:
                out.append(("%s-%s-%s" % (runner, k, name), sh_cmd(size, bad, runner), [("is", "DENY"), ("reader",)]))
        out.append(("tee-%s-clean" % k, tee_cmd(size), [("v20", "DENY"), ("is", "allow")]))
        out.append(("tee-%s-addall" % k, tee_cmd(size, "git add -A"), [("is", "DENY"), ("reader",)]))
        out.append(("awk-%s-clean" % k, awk_cmd(size), [("v20", "DENY"), ("is", "allow")]))
        for name, bad in AWK_BAD:
            out.append(("awk-%s-%s" % (k, name), awk_cmd(size, bad), [("is", "DENY"), ("reader",)]))
        out.append(("catpipe-%s-clean" % k, catpipe_cmd(size), [("v20", "DENY"), ("is", "allow")]))
        out.append(("catpipe-%s-rmtree" % k, catpipe_cmd(size, PY_BAD[0][1]), [("is", "DENY"), ("reader",)]))
    # over MAX_SCRIPT: still unknown. Python, awk, tee then sh and the joined file deny fail closed; a script a shell runs
    # by path keeps v20's verdict (version 8: an unknown shell script is an undo point), unchanged
    for name, bad in (("clean", None),) + PY_BAD:
        out.append(("py-70k-%s" % name, py_cmd(70000, bad), [("is", "DENY"), ("failclosed",), ("same",)]))
    out.append(("awk-70k-clean", awk_cmd(70000), [("is", "DENY"), ("failclosed",), ("same",)]))
    out.append(("tee-70k-clean", tee_cmd(70000), [("is", "DENY"), ("failclosed",), ("same",)]))
    out.append(("catpipe-70k-clean", catpipe_cmd(70000), [("is", "DENY"), ("failclosed",), ("same",)]))
    for runner in ("bash", "sh", "source"):
        out.append(("%s-70k-clean" % runner, sh_cmd(70000, runner=runner), [("same",)]))
        out.append(("%s-70k-push" % runner, sh_cmd(70000, SH_BAD[0][1], runner), [("same",)]))
    out.append(("join-2x40k-clean", join_cmd(40000), [("is", "DENY"), ("failclosed",)]))
    out.append(("join-2x20k-clean", join_cmd(20000), [("is", "allow")]))
    out.append(("join-2x20k-rmtree", join_cmd(20000, PY_BAD[0][1]), [("is", "DENY"), ("reader",)]))
    # the edge: exactly MAX_SCRIPT bytes is read, one more is not
    out.append(("edge-at-max", edge_cmd(MAX_SCRIPT), [("is", "allow")]))
    out.append(("edge-over-max", edge_cmd(MAX_SCRIPT + 1), [("is", "DENY"), ("failclosed",)]))
    # routes whose bound stays MAX_LITERAL: v21 gives exactly v20's verdict and origin
    for size in (5000, 20000):
        for rid, cmd in kept_cmds(size):
            out.append((rid, cmd, [("same",), ("is", "DENY")]))
    # a heredoc read as stdin code never had the bound
    out.append(("stdin-20k-clean", "python3 - <<'PYEOF'\n" + _body(20000, PY_LINE) + "\nPYEOF", [("same",), ("is", "allow")]))
    return out


# rows a switch-off mutation must turn red, by mutation
MUTATIONS = [
    ("cat passes no text at MAX_SCRIPT (the rule switched off)",
     "    return len(argv) == 1 and posixpath.basename(argv[0]) == \"cat\"\n", "    return False\n",
     ["py-5k-clean", "py-60k-clean", "bash-20k-clean", "tee-20k-clean", "awk-60k-clean", "catpipe-20k-clean"]),
    ("the written path gets MAX_LITERAL again (v20's bound)",
     "    return _eval_stages(stages, raw=True, limit=MAX_SCRIPT)", "    return _eval_stages(stages, raw=True, limit=MAX_LITERAL)",
     ["py-5k-clean", "py-60k-clean", "sh-60k-clean", "awk-20k-clean", "edge-at-max"]),
    ("no upper bound (MAX_SCRIPT unlimited)",
     "MAX_SCRIPT = 65536     #", "MAX_SCRIPT = 10 ** 9     #", ["py-70k-clean", "edge-over-max", "awk-70k-clean"]),
    ("the joined-file bound is removed",
     "        if len(data) > MAX_SCRIPT:\n            return None                 # version 21",
     "        if False:\n            return None                 # version 21", ["join-2x40k-clean"]),
    ("printf and echo writing a file get MAX_SCRIPT too (the kept bound is lost; a decoder is held by _decode_bytes)",
     "        if data is None or len(data) > (limit if _passes_text(s[\"argv\"]) else MAX_LITERAL):",
     "        if data is None or len(data) > limit:", ["kept-printf-5000", "kept-echo-5000"]),
]


def guard_path():
    return os.path.abspath(GUARD_ARG) if GUARD_ARG else os.path.join(HERE, "variants", "guard_v21.py")


def all_sets():
    return V20.all_sets() + [("blind_v19", BLIND_V19), ("blind_v20", BLIND_V20)]


def every_file():
    """Every .jsonl file under cases/ (undo_cases.jsonl too) and the six blind sets: -> [relative path]."""
    out = []
    for d, _, fs in os.walk(os.path.join(HERE, "cases")):
        out += [os.path.relpath(os.path.join(d, f), HERE) for f in fs if f.endswith(".jsonl")]
    return sorted(out) + [rel for rel, _ in BLIND_LOCKS]


def raw_sweep(ga, gb):
    """Every row of every file, judged by both guards with its fixture cwd: -> (rows judged, [(file, id, a, b)]) where
    a and b are (verdict, origin) and differ."""
    fx, n, out = Fixtures(), 0, []
    try:
        for rel in every_file():
            for line in open(os.path.join(HERE, rel), encoding="utf-8"):
                if not line.strip():
                    continue
                r = json.loads(line)
                if not isinstance(r.get("command"), str):
                    continue
                cwd = fx.of(r)
                da, db = ga.decide_full(r["command"], cwd), gb.decide_full(r["command"], cwd)
                n += 1
                a, b = (da["verdict"], da["origin"]), (db["verdict"], db["origin"])
                if a != b:
                    out.append((rel, r.get("id"), a, b))
    finally:
        fx.close()
    return n, out


def _f3(c, g):
    return "/".join(str(c[(g, x)]) for x in ("DENY", "UNDO", "allow"))


def tables(res):
    print("%-14s %6s | %-17s %-17s | %-17s %-17s" % ("set", "rows", "bad v20 D/U/a", "bad v21 D/U/a",
                                                    "safe v20 D/U/a", "safe v21 D/U/a"))
    tot = {k: collections.Counter() for k in ("bad", "safe")}
    n = 0
    for name, e in res.items():
        print("%-14s %6d | %-17s %-17s | %-17s %-17s" % (name, e["rows"], _f3(e["bad"], "old"), _f3(e["bad"], "new"),
                                                        _f3(e["safe"], "old"), _f3(e["safe"], "new")))
        n += e["rows"]
        for k in tot:
            tot[k].update(e[k])
    print("%-14s %6d | %-17s %-17s | %-17s %-17s" % ("TOTAL", n, _f3(tot["bad"], "old"), _f3(tot["bad"], "new"),
                                                    _f3(tot["safe"], "old"), _f3(tot["safe"], "new")))


def _wall_of(src):
    """The superlinear shell walk, measured: n lines of '(' as a written script under v21 and as a top-level command."""
    return "cat > /tmp/v21_p.sh <<'XEOF'\n" + "(\n" * (src // 2) + "XEOF\nbash /tmp/v21_p.sh", "(\n" * (src // 2)


def self_test():
    results = []
    gpath = guard_path()

    def check(ok, label):
        results.append((bool(ok), label))
        if "--verbose" in sys.argv:
            print("  ", "ok  " if ok else "FAIL", label)
        elif not ok:
            print("  FAIL:", label)

    # 0. locks: v20 is guard.py unchanged; v14..v19 unchanged; the six blind sets are their locked files; v21 is v20 plus
    # exactly the listed edits and the VERSION 21 block
    sha20 = hashlib.sha256(open(os.path.join(HERE, "variants", "guard_v20.py"), "rb").read()).hexdigest()
    check(sha20 == V20_SHA256, "variants/guard_v20.py is v20 unchanged byte for byte (sha256 %s)" % sha20[:12])
    for f, want in (("variants/guard_v14.py", V20.V14_SHA256), ("variants/guard_v15.py", V20.V15_SHA256),
                    ("variants/guard_v16.py", V20.V16_SHA256), ("variants/guard_v17.py", V20.V17_SHA256),
                    ("variants/guard_v18.py", V20.V18_SHA256), ("variants/guard_v19.py", V20.V19_SHA256)):
        sha = hashlib.sha256(open(os.path.join(HERE, f), "rb").read()).hexdigest()
        check(sha == want, "%s is unchanged byte for byte (sha256 %s)" % (f, sha[:12]))
    for rel, want in BLIND_LOCKS:
        sha = hashlib.sha256(open(os.path.join(HERE, rel), "rb").read()).hexdigest()
        check(sha == want, "%s is the locked file (sha256 %s)" % (rel.split("/")[-1], sha[:12]))
    src = open(gpath, encoding="utf-8").read()
    back = src
    i, j = back.find(V21_BLOCK_START), back.find(V21_BLOCK_END)
    if 0 <= i < j:
        back = back[:i] + back[j:]
    for old, new in V21_EDITS:
        back = back.replace(new, old, 1) if back.count(new) == 1 else back
    check(hashlib.sha256(back.encode("utf-8")).hexdigest() == V20_SHA256,
          "the guard under test is v20 plus exactly the %d listed edits and the VERSION 21 block" % len(V21_EDITS))
    g20 = load_module("g20", os.path.join(HERE, "variants", "guard_v20.py"))
    g21 = load_module("g21", gpath)
    check(g20._root() == PINNED_ROOT and g21._root() == PINNED_ROOT, "both guards measured the pinned root " + PINNED_ROOT)
    check(getattr(g21, "MAX_SCRIPT", None) == MAX_SCRIPT and g21.MAX_LITERAL == MAX_LITERAL == g20.MAX_LITERAL,
          "MAX_SCRIPT is %d and MAX_LITERAL stays %d" % (MAX_SCRIPT, MAX_LITERAL))

    # 1. planted rows built in code
    rows = planted()
    check(len(set(r[0] for r in rows)) == len(rows), "planted ids are unique (%d rows)" % len(rows))
    got, slow = {}, (0.0, "")
    for rid, cmd, wants in rows:
        t = time.perf_counter()
        d21 = g21.decide_full(cmd)
        dt = time.perf_counter() - t
        if dt > slow[0]:
            slow = (dt, rid)
        d20 = g20.decide_full(cmd)
        v21, v20 = verdict(g21, cmd), verdict(g20, cmd)
        got[rid] = v21
        for w in wants:
            if w[0] == "is":
                check(v21 == w[1], "planted %s (%d bytes): v21 %s (want %s; v20 %s)" % (rid, len(cmd), v21, w[1], v20))
            elif w[0] == "v20":
                check(v20 == w[1], "planted %s: v20 %s (want %s: red is reachable)" % (rid, v20, w[1]))
            elif w[0] == "reader":
                check(d21["verdict"] == "deny" and not d21["reason"].startswith("fail_closed"),
                      "planted %s: v21 denies by reading the script, not fail closed (%s)" % (rid, d21["reason"][:50]))
            elif w[0] == "failclosed":
                check(d21["verdict"] == "deny" and d21["reason"].startswith("fail_closed"),
                      "planted %s: v21 denies fail closed, the text unknown (%s)" % (rid, d21["reason"][:60]))
            elif w[0] == "same":
                check((d21["verdict"], d21["origin"]) == (d20["verdict"], d20["origin"]),
                      "planted %s: v21 = v20 (%s/%s; v20 %s/%s)" % (rid, d21["verdict"], d21["origin"], d20["verdict"],
                                                                    d20["origin"]))
    check(slow[0] < SLOW_S, "no planted row takes %.1f s under v21 (slowest %.4f s: %s)" % (SLOW_S, slow[0], slow[1]))
    # the hook form agrees on the 60 KB rows (stdin JSON, the real route)
    for rid in ("py-60k-clean", "py-60k-rmtree-mid", "bash-60k-clean", "bash-60k-push", "py-70k-clean"):
        cmd = [c for r, c, _ in rows if r == rid][0]
        t = time.perf_counter()
        out = subprocess.run([sys.executable, gpath], text=True, capture_output=True,
                             input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}),
                             env=dict(os.environ, AGENT_GUARD_UNDO="0", PYTHONPATH=HERE)).stdout
        dt = time.perf_counter() - t
        denied = '"permissionDecision": "deny"' in out
        check(denied == (got[rid] == "DENY"), "hook form agrees on %s (%s, %.2f s with interpreter start)" % (
            rid, "deny" if denied else "no deny", dt))

    # 2. mutations: switch the change off; a named planted row turns red
    work = tempfile.mkdtemp(prefix="agb-v21-mut-")
    try:
        mrows = [{"id": rid, "command": cmd} for rid, cmd, _ in rows]
        for what, old, new, must in MUTATIONS:
            res, err = run_mutation(old, new, [r for r in mrows if r["id"] in must], work, gpath)
            if err:
                check(False, "mutation (%s): %s" % (what, err))
                continue
            flipped = [rid for rid in must if res[rid] != got[rid]]
            check(flipped, "mutation (%s) turns %s red" % (what, flipped[:4] or "NOTHING"))
        # v20 standing in for v21 reads red; a guard that allows everything reads red
        red20 = [rid for rid, cmd, wants in rows if any(w[0] == "is" and verdict(g20, cmd) != w[1] for w in wants)]
        check(red20, "v20 standing in for v21 reads red on %d planted rows" % len(red20))
        anchor = 'def _decide_full(command):\n    """'
        if src.count(anchor) == 1:
            bpath = os.path.join(work, "guard_broken.py")
            with open(bpath, "w", encoding="utf-8") as fh:
                fh.write(src.replace(anchor, 'def _decide_full(command):\n    return {"verdict": "allow", "origin": None, '
                                             '"v3": "allow", "shape": None, "redirect": "", "alternatives": [], '
                                             '"reason": "", "note": ""}\n    """'))
            gb = load_module("g_broken", bpath)
            red_b = sum(1 for rid, cmd, wants in rows if any(w[0] == "is" and w[1] == "DENY" for w in wants)
                        and verdict(gb, cmd) != "DENY")
            check(red_b > 0, "a deliberately broken v21 (allows everything) reads red on %d planted rows" % red_b)
        else:
            check(False, "the broken-guard anchor was not found once")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # 3. every set: no row changes verdict v20 -> v21 (scored sets), and no row of any file changes verdict or origin
    res = compare_all(g20, g21, all_sets())
    reg = regressions(res)
    check(not reg, "no row of any set is worse under v21 than v20 (%d regressions: %s)" % (len(reg), [x[1] for x in reg][:5]))
    changed = sorted((n, x[0], x[2], x[3]) for n, e in res.items() for x in e["changed"])
    check(not changed, "no row of cases/ or blind_v15..v20 (%d rows) changes verdict v20 -> v21 (%s)" % (
        sum(e["rows"] for e in res.values()), changed[:6] or "none"))
    shapes = sorted((n, x) for n, e in res.items() for x in e["shapes"])
    check(not shapes, "no redirect shape changes on rows both deny (%s)" % (shapes[:4] or "none"))
    nraw, moved = raw_sweep(g20, g21)
    check(not moved, "every row of every .jsonl under cases/ and the six blind sets (%d rows, %d files) keeps its verdict "
                     "and origin v20 -> v21 (%s)" % (nraw, len(every_file()), moved[:6] or "none"))

    # 4. timing: bench.py's pathological inputs and version 16's; every set row; the superlinear walk named, not hidden
    w16, head, n16 = V16.pathological_timing(g21)
    wb, hb = bench.pathological_timing(g21)
    check(w16 < SLOW_S and wb < SLOW_S, "no pathological input takes %.1f s (bench.py %.4f s; with version 16's seeds "
                                        "%.4f s over %d inputs: %r)" % (SLOW_S, wb, w16, n16, head[:30]))
    slow_row, nrows = (0.0, ""), 0
    for name, rel in all_sets():
        for r in rows_of(name, rel):
            t = time.perf_counter()
            g21.decide(r["command"])
            dt = time.perf_counter() - t
            nrows += 1
            if dt > slow_row[0]:
                slow_row = (dt, r["id"])
    check(slow_row[0] < 0.1, "no decision takes 0.1 s on the %d rows of every set (slowest %.4f s: %s)" % (
        nrows, slow_row[0], slow_row[1]))
    wall = []
    for size in (4000, 8000):
        written, top = _wall_of(size)
        t = time.perf_counter()
        g21.decide(written)
        a = time.perf_counter() - t
        t = time.perf_counter()
        g20.decide(top)
        b = time.perf_counter() - t
        wall.append((size, a, b))
    check(all(a < 3 * b + 0.05 for _, a, b in wall), "a pathological written script costs v21 what the same bytes as a "
          "top-level command cost v20 (%s)" % ", ".join("%d B: v21 %.2f s, v20 %.2f s" % x for x in wall))

    n_ok = sum(1 for ok, _ in results if ok)
    n_bad = len(results) - n_ok
    print("guard under test: %s" % gpath)
    print("slowest planted row %.4f s (%s); slowest pathological input %.4f s (bench.py %.4f s); slowest set row %.4f s "
          "(%d rows)" % (slow[0], slow[1], w16, wb, slow_row[0], nrows))
    print("superlinear shell walk, named: %s" % ", ".join("%d B of '(' lines: v21 written script %.2f s, v20 top-level "
                                                         "%.2f s" % x for x in wall))
    print("Blind to: %s" % " ".join(__doc__.split("Blind to:")[1].split()))
    print("SELF-TEST: %d passed, %d failed" % (n_ok, n_bad))
    return 1 if n_bad else 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    g20 = load_module("g20", os.path.join(HERE, "variants", "guard_v20.py"))
    g21 = load_module("g21", guard_path())
    if "--diff" in argv:
        V16.print_diff(compare_all(g20, g21, all_sets()), "v20", "v21")
        n, moved = raw_sweep(g20, g21)
        print("EVERY FILE (%d .jsonl files, %d rows): verdict or origin changed v20 -> v21: %d" % (
            len(every_file()), n, len(moved)))
        for x in moved:
            print("     ", x)
        return 0
    if "--tables" in argv:
        tables(compare_all(g20, g21, all_sets()))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
