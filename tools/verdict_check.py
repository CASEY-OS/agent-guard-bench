#!/usr/bin/env python3
"""verdict_check.py: the README's table of the three kinds of verdict, and the split in docs/PROFILE_DESIGN.md, read
back from the guard itself.

    python3 tools/verdict_check.py --self-test     the proofs, then SELF-TEST: N passed, N failed
    python3 tools/verdict_check.py                 the split only, printed

Two things are checked against `guard.decide_full`, the code that decides:
  1. each example command in the README's "Three kinds of verdict" table has the `origin` the table gives it;
  2. the table in docs/PROFILE_DESIGN.md (how many dangerous and safe commands of blind_v20 land in each kind) equals the
     count this run makes over docs/evidence/blind_v20/blind_v20_set.jsonl, and its deny rows add up to the figures in
     results/NUMBERS.json (versions.current.denied, safe_denied, missed: the numbers of guard.py).
The guard runs with the undo layer off, the judge unset and the root pinned to /work/repo (asserted below), as
tools/v15_check.py and tools/v22_check.py run it, so nothing depends on the machine.

Every planted violation is built at run time in memory: a wrong example in a copy of the README table, a wrong count in a
copy of the design table. Each has a matched clean control (the real text).

Blind to: any command the table does not name as an example; whether the words in the table's "What the guard does"
column describe the origin well (only the origin value and the example are checked); the counts on any set other than
blind_v20; and the guard on a machine other than this one (Python 3.14 on macOS proven here).
"""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
os.environ["AGENT_GUARD_UNDO"] = "0"
os.environ["AGENT_GUARD_ROOT"] = "/work/repo"
os.environ.pop("AGENT_GUARD_JUDGE", None)
sys.path.insert(0, REPO)
import guard  # noqa: E402

assert guard._root() == "/work/repo", "the guard root is not pinned"
SET = os.path.join(REPO, "docs", "evidence", "blind_v20", "blind_v20_set.jsonl")
README = os.path.join(REPO, "README.md")
DESIGN = os.path.join(REPO, "docs", "PROFILE_DESIGN.md")
NUMBERS = os.path.join(REPO, "results", "NUMBERS.json")
KINDS = (("Floor", "deny", "block"), ("Reflex", "deny", "irreversible"), ("Finish", "allow", "recoverable"),
         ("Plain allow", "allow", None))


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def split():
    """-> {(verdict, origin): [dangerous, safe]} over blind_v20."""
    out = collections.defaultdict(lambda: [0, 0])
    with open(SET, encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            d = guard.decide_full(row["command"])
            out[(d["verdict"], d["origin"])][0 if row["expect"] == "stop" else 1] += 1
    return out


def readme_examples(text):
    """-> [(kind name, origin, example command)] from the README's table."""
    rows = re.findall(r"^\| (Floor|Reflex|Finish) \| `(\w+)` \|.*\| `([^`]+)` \|$", text, re.M)
    return rows


def design_counts(text):
    """-> {kind name: (dangerous, safe)} from the design page's table."""
    got = {}
    for name, a, b in re.findall(r"^\| ((?:Floor|Reflex|Finish)[^|]*|Plain allow) \| ([0-9,]+) \| ([0-9,]+) \|$", text, re.M):
        got[name.split(":")[0]] = (int(a.replace(",", "")), int(b.replace(",", "")))
    return got


def examples_ok(text):
    bad = []
    rows = readme_examples(text)
    if [r[0] for r in rows] != ["Floor", "Reflex", "Finish"]:
        return ["README table rows not found: got %r" % [r[0] for r in rows]]
    for name, origin, cmd in rows:
        got = guard.decide_full(cmd)["origin"]
        if got != origin:
            bad.append("%s: `%s` has origin %r, the table says %r" % (name, cmd, got, origin))
    return bad


def counts_ok(text, sp, numbers):
    bad = []
    want = design_counts(text)
    have = {"Floor": tuple(sp[("deny", "block")]), "Reflex": tuple(sp[("deny", "irreversible")]),
            "Finish": tuple(sp[("allow", "recoverable")]), "Plain allow": tuple(sp[("allow", None)])}
    if set(want) != set(have):
        return ["design table rows not found: got %r" % sorted(want)]
    for k in have:
        if want[k] != have[k]:
            bad.append("%s: the page says %r, the guard gives %r" % (k, want[k], have[k]))
    lead = numbers["versions"]["current"]   # guard.py: the table above is its split (it was "lead", v20, while guard.py equalled v20 on this set)

    def val(key):
        v = lead[key]
        return v["value"] if isinstance(v, dict) else v
    if have["Floor"][0] + have["Reflex"][0] != val("denied"):
        bad.append("deny rows (dangerous) %d != NUMBERS denied %s" % (have["Floor"][0] + have["Reflex"][0], val("denied")))
    if have["Floor"][1] + have["Reflex"][1] != val("safe_denied"):
        bad.append("deny rows (safe) %d != NUMBERS safe_denied %s" % (have["Floor"][1] + have["Reflex"][1], val("safe_denied")))
    if have["Plain allow"][0] != val("missed"):
        bad.append("plain allows (dangerous) %d != NUMBERS missed %s" % (have["Plain allow"][0], val("missed")))
    return bad


def main(argv):
    sp = split()
    print("blind_v20 through guard.py (undo off, judge unset, root /work/repo): dangerous / safe")
    for name, verdict, origin in KINDS:
        d, s = sp[(verdict, origin)]
        print("  %-12s %-6s %-13s %5d / %5d" % (name, verdict, origin, d, s))
    if "--self-test" not in argv:
        return 0
    results = []

    def case(label, ok, detail=""):
        results.append(bool(ok))
        print("%s  %s%s" % ("pass" if ok else "FAIL", label, (": " + detail) if detail else ""))

    readme = read(README)
    design = read(DESIGN)
    numbers = json.load(open(NUMBERS, encoding="utf-8"))
    problems = examples_ok(readme)
    case("README table: Floor, Reflex and Finish each have the origin the table names", not problems, "; ".join(problems))
    wrong = readme.replace("| `irreversible` |", "| `block` |", 1)
    case("planted: a table that gives the Reflex row the origin `block` reads red",
         bool(examples_ok(wrong)) and wrong != readme, "; ".join(examples_ok(wrong))[:120])
    swapped = readme.replace("| `rm -rf .` |", "| `git status` |", 1)
    case("planted: an example that is a plain allow in the Reflex row reads red", bool(examples_ok(swapped)) and swapped != readme)
    problems = counts_ok(design, sp, numbers)
    case("design page: the table equals this run's split and its deny rows equal NUMBERS.json", not problems,
         "; ".join(problems))
    off = design.replace("| 1,667 | 18 |", "| 1,668 | 18 |", 1)
    case("planted: one count changed on the design page reads red", bool(counts_ok(off, sp, numbers)) and off != design)
    # the sums against NUMBERS must stand on their own: a split that does not add up must read red even if the page matches
    broken = {k: list(v) for k, v in sp.items()}
    broken[("deny", "block")][0] += 1
    off2 = design.replace("| 1,667 | 18 |", "| 1,668 | 18 |", 1)
    case("planted: a split that no longer adds up to NUMBERS reads red though the page agrees with it",
         any("NUMBERS" in b for b in counts_ok(off2, broken, numbers)))
    case("the blind_v20 set read is the whole set (3,300 rows)", sum(sum(v) for v in sp.values()) == 3300,
         "%d rows" % sum(sum(v) for v in sp.values()))
    print("Blind to: any example not in the table; the words of the table's middle column; sets other than blind_v20.")
    print("SELF-TEST: %d passed, %d failed" % (results.count(True), results.count(False)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
