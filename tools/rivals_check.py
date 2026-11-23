#!/usr/bin/env python3
"""rivals_check.py: every rival number in the README's rival section, checked against the scorer's own output.

    python3 tools/rivals_check.py [--root REPO]
    python3 tools/rivals_check.py --self-test

Reads the section of README.md from the heading "### Against two free rivals, same blind set" to the end of its
"To re-run:" paragraph, and checks it against docs/evidence/blind_v31/rivals/ (the JSON and the Markdown table that
score_rivals_v31.py wrote) and docs/evidence/blind_v31/LOCK.txt.

What it checks, by two routes:
  1. Each of the six table rows (a guard, or one convention of ours) against the JSON's counts: dangerous stopped of 1,124,
     the Wilson 95% interval it recomputes itself, the four per-policy counts, and safe wrongly stopped of 1,305.
  2. The same row's cell text against the matching row of RESULTS_v31.md, which the scorer printed. The two routes share
     no code with each other.
  Also: the figures in the prose (234 of 236, 228 of 236, 36 and 96 false stops, 50 commands, 2,429 commands) against the
  JSON; that cc-safety-net paranoid is ahead of this guard on policy D, because the section says so; that the JSON's set
  sha256 is the one in LOCK.txt; and that the section does not use a claim the guard has not earned ("best", "#1",
  "most-starred", "beats everyone", "beats every").
Exit 1 on any mismatch, on a missing row, a missing section or a missing file. Exit 0 only when every check agrees.
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

HEAD = "### Against two free rivals, same blind set"
TAIL = "To re-run:"
RIV = os.path.join("docs", "evidence", "blind_v31", "rivals")
LOCK = os.path.join("docs", "evidence", "blind_v31", "LOCK.txt")
# README row label (start of the first cell) -> key in the JSON's "tables"
ROWS = [
    ("agent-guard v30 (counted as the table above counts it)", "ours v30, README convention (undo fallback counted allowed)"),
    ("agent-guard v30 (the hook as run outside a git repo)", "ours v30, hook as run, undo off (fallback deny counted stopped)"),
    ("dcg v0.17.1, default settings", "dcg v0.17.1 (default packs)"),
    ("cc-safety-net 2.8.3, standard level", "cc-safety-net 2.8.3 standard"),
    ("cc-safety-net 2.8.3, strict level", "cc-safety-net 2.8.3 strict"),
    ("cc-safety-net 2.8.3, paranoid level", "cc-safety-net 2.8.3 paranoid"),
]
FORBIDDEN = [r"\bbest\b", r"#1", r"most-starred", r"beats everyone", r"beats every\b"]
BLIND_TO = ("Blind to: any number outside the rival section of the README (the blind_v31 and blind_v20 tables are "
            "check_surfaces.py's), a number written in words, whether the scorer's output is itself right (it compares the "
            "README with the scorer's JSON and Markdown, not with a new run of the rivals), whether the labels are right, "
            "and any claim in the section that is not one of the numbers or forbidden words listed above.")


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return 100 * (c - h) / d, 100 * (c + h) / d


def num(s):
    return int(s.replace(",", ""))


def section(readme):
    i = readme.find(HEAD)
    if i < 0:
        return None
    j = readme.find(TAIL, i)
    if j < 0:
        return None
    k = readme.find("\n\n", j)
    return readme[i:(k if k > 0 else len(readme))]


def check(root):
    """-> (problems list, notes list)."""
    bad, notes = [], []
    rp = os.path.join(root, "README.md")
    jp = os.path.join(root, RIV, "rival_scores_v31.json")
    mp = os.path.join(root, RIV, "RESULTS_v31.md")
    lp = os.path.join(root, LOCK)
    for p in (rp, jp, mp, lp):
        if not os.path.isfile(p):
            return ["MISSING FILE: %s" % p], notes
    sec = section(open(rp, encoding="utf-8").read())
    if sec is None:
        return ["MISSING: README has no section %r ending in a %r paragraph" % (HEAD, TAIL)], notes
    js = json.load(open(jp, encoding="utf-8"))
    tb = js["tables"]
    md = open(mp, encoding="utf-8").read()
    # the set the scorer measured is the locked one
    lock = open(lp, encoding="utf-8").read().split()
    if len(lock) < 3 or lock[2] != js["meta"]["set_sha256"]:
        bad.append("set sha256 in the JSON (%s) is not the one in LOCK.txt (%s)" % (js["meta"]["set_sha256"], lock[2:3]))
    # table rows
    rows = {}
    for line in sec.splitlines():
        if line.startswith("| ") and not line.startswith("| guard") and not line.startswith("|---"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows.setdefault(cells[0], []).append(cells)
    for label, key in ROWS:
        got = rows.get(label, [])
        if len(got) != 1:
            bad.append("row %r appears %d times in the README table (want 1)" % (label, len(got)))
            continue
        cells = got[0]
        t = tb[key]
        if len(cells) != 7:
            bad.append("row %r has %d cells (want 7)" % (label, len(cells)))
            continue
        m = re.fullmatch(r"([\d,]+) of ([\d,]+) \(([\d.]+)%, ([\d.]+) to ([\d.]+)\)", cells[1])
        s = re.fullmatch(r"([\d,]+) of ([\d,]+) \(([\d.]+)%, ([\d.]+) to ([\d.]+)\)", cells[6])
        for part, mm, k_, n_ in (("dangerous", m, t["tp"], t["bad"]), ("safe wrongly stopped", s, t["fp"], t["safe"])):
            if not mm:
                bad.append("%s: %s cell is not in the shape 'k of n (p%%, lo to hi)'" % (label, part))
                continue
            k, n, pct, lo, hi = num(mm.group(1)), num(mm.group(2)), mm.group(3), mm.group(4), mm.group(5)
            wl, wh = wilson(k_, n_)
            want = (k_, n_, "%.1f" % (100 * k_ / n_), "%.1f" % wl, "%.1f" % wh)
            if (k, n, pct, lo, hi) != want:
                bad.append("%s: %s reads %s, the scorer's JSON gives %s" % (label, part, (k, n, pct, lo, hi), want))
        for p, cell in zip("ABCD", cells[2:6]):
            if cell != "%d/%d" % (t["tp_" + p], t["bad_" + p]):
                bad.append("%s: policy %s reads %s, the JSON gives %d/%d" % (label, p, cell, t["tp_" + p], t["bad_" + p]))
        # route 2: the scorer's own Markdown row
        mrow = [l for l in md.splitlines() if l.startswith("| " + key + " |") and l.count("|") == 8]   # the main table (7 cells), not the 3-cell sensitivity table
        if len(mrow) != 1:
            bad.append("%s: RESULTS_v31.md has %d rows for %r (want 1)" % (label, len(mrow), key))
        else:
            mc = [c.strip() for c in mrow[0].strip().strip("|").split("|")]
            if mc[1] != cells[1] or mc[6] != cells[6] or mc[2:6] != cells[2:6]:
                bad.append("%s: README cells differ from the scorer's own RESULTS_v31.md row: %s vs %s" % (label, cells[1:], mc[1:]))
    # the prose figures
    ours, par = tb[ROWS[0][1]], tb[ROWS[5][1]]
    for text, want in (("%d of %d" % (par["tp_D"], par["bad_D"]), "cc-safety-net paranoid on D"),
                       ("%d of %d" % (ours["tp_D"], ours["bad_D"]), "ours on D"),
                       ("(%d false stops)" % ours["fp"], "ours, first convention"),
                       ("(%d false stops)" % tb[ROWS[1][1]]["fp"], "ours, hook as run"),
                       ("%d commands in the set name the path" % len(js["sensitivity_ids"]), "the /work/repo rows"),
                       ("The same %s commands" % format(len(js["ids"]), ","), "the set size")):
        if text not in sec:
            bad.append("prose figure %r (%s) is not in the section as the JSON gives it" % (text, want))
    if not par["tp_D"] > ours["tp_D"]:
        bad.append("the section says cc-safety-net paranoid is ahead on policy D, but the JSON has %d vs %d" % (par["tp_D"], ours["tp_D"]))
    for pat in FORBIDDEN:
        if re.search(pat, sec, re.I):
            bad.append("the section uses a claim it has not earned: %s" % pat)
    notes.append("rows checked: %d; prose figures: 6" % len(ROWS))
    return bad, notes


def main(argv):
    if "--self-test" in argv:
        return self_test()
    root = os.path.realpath(argv[argv.index("--root") + 1]) if "--root" in argv else os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    print("Measured root: %s" % root)
    bad, notes = check(root)
    for n in notes:
        print("  " + n)
    for b in bad:
        print("  FAIL: " + b)
    print(BLIND_TO)
    print("RIVALS CHECK: %s" % ("PASS" if not bad else "FAIL (%d problem%s)" % (len(bad), "" if len(bad) == 1 else "s")))
    return 0 if not bad else 1


# ------------------------------------------------------------------ self-test
def self_test():
    here = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="rivals-selftest-"))
    results = []

    def case(name, ok):
        results.append(ok)
        print("%s  %s" % ("pass" if ok else "FAIL", name))

    def fresh(tag):
        r = os.path.join(tmp, tag)
        os.makedirs(os.path.join(r, RIV))
        os.makedirs(os.path.dirname(os.path.join(r, LOCK)), exist_ok=True)
        shutil.copy(os.path.join(here, "README.md"), r)
        for f in os.listdir(os.path.join(here, RIV)):
            if f.endswith((".json", ".md")):
                shutil.copy(os.path.join(here, RIV, f), os.path.join(r, RIV))
        shutil.copy(os.path.join(here, LOCK), os.path.join(r, LOCK))
        return r

    def edit(r, rel, fn):
        p = os.path.join(r, rel)
        s = open(p, encoding="utf-8").read()
        t = fn(s)
        assert t != s, "the planted edit changed nothing in " + rel
        open(p, "w", encoding="utf-8").write(t)

    def run(r):
        p = subprocess.run([sys.executable, "-I", os.path.join(here, "tools", "rivals_check.py"), "--root", r], capture_output=True, text=True)
        return p.returncode, p.stdout

    try:
        # clean control: the real files, copied
        r = fresh("clean")
        rc, out = run(r)
        case("clean control: the copied README and rival files pass", rc == 0 and "RIVALS CHECK: PASS" in out)
        case("the run measured the fixture root, not the live tree (%s)" % r, ("Measured root: %s" % r) in out and here not in out.split("Blind to")[0])
        case("a Blind to line is printed", "Blind to:" in out)
        planted = [
            ("planted: a dangerous-stopped count changed in a rival row", "README.md", lambda s: s.replace("| 417 of 1,124 (37.1%", "| 418 of 1,124 (37.1%", 1), "dcg v0.17.1, default settings: dangerous"),
            ("planted: a Wilson bound changed", "README.md", lambda s: s.replace("(41.3%, 38.4 to 44.2)", "(41.3%, 38.4 to 44.3)", 1), "paranoid level: dangerous"),
            ("planted: a policy cell changed", "README.md", lambda s: s.replace("| 17/349 | 36/318 |", "| 17/349 | 37/318 |", 1), "policy B"),
            ("planted: a safe-wrongly-stopped count changed", "README.md", lambda s: s.replace("| 293 of 1,305 (22.5%", "| 292 of 1,305 (22.5%", 1), "safe wrongly stopped"),
            ("planted: the prose says 233 of 236 for the rival", "README.md", lambda s: s.replace("stopped 234 of 236", "stopped 233 of 236", 1), "prose figure"),
            ("planted: the 96 false stops figure changed", "README.md", lambda s: s.replace("(96 false stops)", "(95 false stops)", 1), "prose figure"),
            ("planted: a table row is deleted", "README.md", lambda s: s.replace("| cc-safety-net 2.8.3, strict level |", "| (row removed) |", 1), "appears 0 times"),
            ("planted: a claim the guard has not earned, 'the best'", "README.md", lambda s: s.replace("The limits, in plain sentences:", "This is the best guard. The limits, in plain sentences:", 1), "has not earned"),
            ("planted: the JSON no longer agrees with the README", RIV + "/rival_scores_v31.json", lambda s: s.replace('"tp": 417,', '"tp": 416,', 1), "dcg v0.17.1, default settings: dangerous"),
            ("planted: the JSON names a different set than LOCK.txt", RIV + "/rival_scores_v31.json", lambda s: s.replace("dbac99f8", "dbac99f9", 1), "LOCK.txt"),
            ("planted: the section is gone", "README.md", lambda s: s.replace(HEAD, "### Something else", 1), "MISSING"),
        ]
        for name, rel, fn, want in planted:
            r = fresh("p%d" % len(results))
            edit(r, rel, fn)
            rc, out = run(r)
            case(name, rc == 1 and "RIVALS CHECK: FAIL" in out and want in out)
        # the paranoid-leads-on-D sentence cannot stay true if the data flips
        r = fresh("flip")
        edit(r, RIV + "/rival_scores_v31.json", lambda s: s.replace('"tp_D": 234', '"tp_D": 200', 1))
        rc, out = run(r)
        case("planted: the JSON says the rival is no longer ahead on D, the sentence still says so", rc == 1 and "ahead on policy D" in out)
        # boundary: outside the blind spot stays caught, inside it stays green and says so
        r = fresh("outside")
        edit(r, "README.md", lambda s: s.replace("| agent-guard v30, the version the plugin runs (blind) | 1,107 of 1,124 (98.5%)", "| agent-guard v30, the version the plugin runs (blind) | 1,106 of 1,124 (98.5%)", 1))
        rc, out = run(r)
        case("blind spot: a wrong number in the blind_v31 table (outside this section) stays green here; check_surfaces.py owns it", rc == 0 and "Blind to:" in out and "any number outside the rival section" in out)
        r = fresh("inside")
        edit(r, "README.md", lambda s: s.replace("A newer release may differ.", "A newer release may differ, and it may be better.", 1))
        rc, out = run(r)
        case("blind spot: a changed sentence that is neither a number nor a forbidden word stays green", rc == 0)
        r = fresh("nofile")
        os.remove(os.path.join(r, RIV, "RESULTS_v31.md"))
        rc, out = run(r)
        case("planted: the scorer's Markdown is missing", rc == 1 and "MISSING FILE" in out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("room deleted: %s" % (not os.path.exists(tmp)))
    print(BLIND_TO)
    print("SELF-TEST: %d passed, %d failed" % (sum(results), len(results) - sum(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    sys.exit(main(sys.argv[1:]))
