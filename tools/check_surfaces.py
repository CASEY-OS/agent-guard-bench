#!/usr/bin/env python3
"""check_surfaces.py: every number a surface states, checked against NUMBERS.json.

    python3 tools/check_surfaces.py results/NUMBERS.json tools/SURFACE_MAP.json [--max-age-hours 24]
    python3 tools/check_surfaces.py --self-test

SURFACE_MAP.json:
    {"root": "..",                     surface paths resolve against this, relative to the map file's own directory
     "surfaces": {"README.md": {}, "x.md": {"optional": true}},
     "claims": [{"file": "README.md", "pattern": "dangerous commands denied \\| (\\d+) of (\\d+)",
                 "keys": ["blind.guards.v14.denied", "blind.guards.v14.denied@denominator"],
                 "type": "number"}]}
A key is a dotted path into NUMBERS.json; a node that carries "value" gives its value, and "@denominator" gives its
denominator. Types: number (commas and a trailing % are dropped; a claim with k decimals is compared with the NUMBERS
value rounded to k decimals; "scale" multiplies the NUMBERS value first), ids (the claim's ids as a set against the
NUMBERS list), text (exact). Paths may be absolute, ~ or relative to the root. Every match of a pattern is checked,
not only the first. A claim with "scope": [start, end] reads only the text from the first start marker to the next
end marker (a changelog's newest section, say); a number outside that section is not checked, by design.

Exit 1 on any mismatch, on a mapped pattern with no match, on a key NUMBERS does not have, on a surface file that is
missing (unless the map marks it optional) and on a NUMBERS.json older than --max-age-hours (default 24) by its own
generated_at. Exit 0 only when every claim agrees. It prints every claim beside the NUMBERS value.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

BLIND_TO = ("Blind to: a number on a surface that no pattern in the map names, a number written in words, a number "
            "outside a claim's scoped section, a surface file the map does not list, what the sentence around a number means (it compares the digits a pattern "
            "captures, nothing else), and whether NUMBERS.json itself is right (bench.py makes it; this only checks "
            "that surfaces agree with it).")


def lookup(numbers, key):
    """-> (found, value)."""
    want_den = key.endswith("@denominator")
    path = key[:-len("@denominator")] if want_den else key
    node = numbers
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return False, None
    if isinstance(node, dict):
        if want_den:
            return ("denominator" in node), node.get("denominator")
        if "value" in node:
            return True, node["value"]
        return False, None
    if want_den:
        return False, None
    return True, node


def to_num(text):
    t = text.strip().replace(",", "").rstrip("%").strip()
    return float(t), (len(t.split(".")[1]) if "." in t else 0)


def compare(kind, claim, value, scale=1.0):
    """-> (agrees, shown NUMBERS value)."""
    if kind == "ids":
        got = set(re.findall(r"[A-Za-z0-9][A-Za-z0-9:_-]*", claim)) - {"and", "none"}
        want = set(value or [])
        return got == want, ", ".join(sorted(want)) or "none"
    if kind == "text":
        return claim.strip() == str(value), str(value)
    if isinstance(value, bool) or value is None or not isinstance(value, (int, float)):
        return False, repr(value)
    c, dec = to_num(claim)
    v = round(value * scale, dec)
    return abs(c - v) < 1e-9, ("%." + str(dec) + "f") % v


def run(numbers_path, map_path, max_age_hours, now=None):
    out, bad = [], 0
    numbers = json.load(open(numbers_path, encoding="utf-8"))
    smap = json.load(open(map_path, encoding="utf-8"))
    root = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(map_path)),
                                         os.path.expanduser(smap.get("root", "."))))
    out.append("Measured root: %s" % root)
    out.append("NUMBERS: %s" % os.path.realpath(numbers_path))
    gen = numbers.get("generated_at")
    now = now or datetime.datetime.now().astimezone()
    try:
        g = datetime.datetime.fromisoformat(gen)
        if g.tzinfo is None:
            g = g.astimezone()
        age = (now - g).total_seconds() / 3600.0
        if age > max_age_hours:
            bad += 1
            out.append("STALE    NUMBERS generated_at %s is %.1f h old, over the %.1f h bound" % (gen, age, max_age_hours))
        else:
            out.append("FRESH    NUMBERS generated_at %s, %.1f h old, bound %.1f h" % (gen, age, max_age_hours))
    except (TypeError, ValueError):
        bad += 1
        out.append("STALE    NUMBERS has no readable generated_at (%r)" % (gen,))
    surfaces = smap.get("surfaces", {})
    texts = {}
    for f, meta in sorted(surfaces.items()):
        p = os.path.expanduser(f)
        p = p if os.path.isabs(p) else os.path.join(root, p)
        if os.path.isfile(p):
            texts[f] = open(p, encoding="utf-8").read()
        elif (meta or {}).get("optional"):
            out.append("OPTIONAL-ABSENT %s (%s)" % (f, p))
        else:
            bad += 1
            out.append("NOFILE   %s (%s)" % (f, p))
    n_claims = n_ok = n_mis = n_missing = 0
    for c in smap.get("claims", []):
        f = c["file"]
        if f not in surfaces:
            bad += 1
            out.append("UNMAPPED claim names %s, which is not in surfaces" % f)
            continue
        if f not in texts:
            continue
        text, base = texts[f], 0
        if c.get("scope"):                 # [start marker, end marker]: only that section of the file is read
            a = text.find(c["scope"][0])
            b = text.find(c["scope"][1], a + 1) if a >= 0 and len(c["scope"]) > 1 else len(text)
            if a < 0 or b < 0:
                bad += 1
                n_missing += 1
                out.append("MISSING  %s: scope marker not found (%r)" % (f, c["scope"]))
                continue
            text, base = text[a:b], a
        full_text = texts[f]
        matches = list(re.finditer(c["pattern"], text))
        if not matches:
            bad += 1
            n_missing += 1
            out.append("MISSING  %s: no match for /%s/ (keys %s)" % (f, c["pattern"], ", ".join(c["keys"])))
            continue
        for m in matches:
            line = full_text.count("\n", 0, base + m.start()) + 1
            groups = m.groups() or (m.group(0),)
            for key, claim in zip(c["keys"], groups):
                n_claims += 1
                found, value = lookup(numbers, key)
                if not found:
                    bad += 1
                    n_mis += 1
                    out.append("NOKEY    %s:%d  %s  claim %r  NUMBERS has no such key" % (f, line, key, claim))
                    continue
                okk, shown = compare(c.get("type", "number"), claim, value, float(c.get("scale", 1.0)))
                if okk:
                    n_ok += 1
                    out.append("OK       %s:%d  %s  claim %s  NUMBERS %s" % (f, line, key, claim.strip(), shown))
                else:
                    bad += 1
                    n_mis += 1
                    out.append("MISMATCH %s:%d  %s  claim %s  NUMBERS %s" % (f, line, key, claim.strip(), shown))
    out.append("SURFACES: %d files, %d claims checked, %d agree, %d disagree, %d patterns missing"
               % (len(texts), n_claims, n_ok, n_mis, n_missing))
    out.append("VERDICT: %s" % ("PASS" if bad == 0 else "FAIL (%d problems)" % bad))
    out.append(BLIND_TO)
    return (0 if bad == 0 else 1), out


def self_test():
    """Fixtures built at runtime in a temp dir, each run through this script as a separate process (the real route),
    and the measured root asserted to be the temp dir, never the live tree."""
    import shutil
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="check-surfaces-"))
    passed, failed, lines = 0, 0, []
    try:
        now = datetime.datetime.now().astimezone()

        def numbers(age_h=0.0):
            return {"generated_at": (now - datetime.timedelta(hours=age_h)).isoformat(timespec="seconds"),
                    "blind": {"denied": {"value": 374, "denominator": 391},
                              "missed_ids": {"value": ["H19A", "H19B"]},
                              "secs": {"value": 0.0142}, "share": {"value": 0.6583},
                              "commit": {"value": "e88a7d8"}, "big": {"value": 68636}}}
        clean = ("# S\n\nThe guard denied 374 of 391.\nMissed: H19A and H19B.\nSlowest 0.014 s. Share 65.8%.\n"
                 "Frozen at e88a7d8. Calls 68,636.\n")
        claims = [{"file": "S.md", "pattern": r"denied (\d+) of (\d+)", "keys": ["blind.denied", "blind.denied@denominator"]},
                  {"file": "S.md", "pattern": r"Missed: ([^.]+)\.", "keys": ["blind.missed_ids"], "type": "ids"},
                  {"file": "S.md", "pattern": r"Slowest ([0-9.]+) s", "keys": ["blind.secs"]},
                  {"file": "S.md", "pattern": r"Share ([0-9.]+%)", "keys": ["blind.share"], "scale": 100},
                  {"file": "S.md", "pattern": r"Frozen at ([0-9a-f]{7})", "keys": ["blind.commit"], "type": "text"},
                  {"file": "S.md", "pattern": r"Calls ([0-9,]+)", "keys": ["blind.big"]}]

        def case(name, want_rc, want_text, surface=clean, nums=None, mp=None, extra=(), files=None):
            nonlocal passed, failed
            d = tempfile.mkdtemp(prefix="case-", dir=tmp)
            for fn, body in (files if files is not None else {"S.md": surface}).items():
                with open(os.path.join(d, fn), "w", encoding="utf-8") as fh:
                    fh.write(body)
            with open(os.path.join(d, "N.json"), "w") as fh:
                json.dump(nums if nums is not None else numbers(), fh)
            with open(os.path.join(d, "M.json"), "w") as fh:
                json.dump(mp if mp is not None else {"root": ".", "surfaces": {"S.md": {}}, "claims": claims}, fh)
            p = subprocess.run([sys.executable, os.path.abspath(__file__), os.path.join(d, "N.json"),
                                os.path.join(d, "M.json")] + list(extra), capture_output=True, text=True)
            measured = re.search(r"^Measured root: (.*)$", p.stdout, re.M)
            problems = len(re.findall(r"^(MISMATCH|MISSING|STALE|NOFILE|NOKEY|UNMAPPED)", p.stdout, re.M))
            ok = (p.returncode == want_rc and want_text in p.stdout and measured
                  and measured.group(1) == os.path.realpath(d) and "VERDICT:" in p.stdout
                  and problems == (0 if want_rc == 0 else 1))    # one planted defect, one red line; the rest stays green
            passed, failed = passed + bool(ok), failed + (not ok)
            lines.append("%s  %s (exit %d, wanted %d; '%s' %s; %d problem lines)" % (
                "pass" if ok else "FAIL", name, p.returncode, want_rc, want_text,
                "seen" if want_text in p.stdout else "NOT seen", problems))
        case("clean control: every claim agrees", 0, "VERDICT: PASS")
        case("planted mismatch: 375 where NUMBERS says 374", 1, "MISMATCH", surface=clean.replace("374", "375"))
        case("planted mismatch in the denominator", 1, "MISMATCH", surface=clean.replace("of 391", "of 390"))
        case("planted mismatch in ids", 1, "MISMATCH", surface=clean.replace("H19B", "H19C"))
        case("planted mismatch in a rounded decimal", 1, "MISMATCH", surface=clean.replace("0.014", "0.015"))
        case("planted mismatch in text", 1, "MISMATCH", surface=clean.replace("e88a7d8", "e88a7d9"))
        case("a second, wrong occurrence of a claim", 1, "MISMATCH", surface=clean + "Again denied 370 of 391.\n")
        case("missing phrase", 1, "MISSING", surface=clean.replace("Slowest 0.014 s.", "Fast."))
        case("stale date: NUMBERS 30 h old, bound 24 h", 1, "STALE", nums=numbers(30.0))
        case("fresh control: NUMBERS 30 h old, bound 48 h", 0, "VERDICT: PASS", nums=numbers(30.0),
             extra=["--max-age-hours", "48"])
        case("missing surface file", 1, "NOFILE", files={})
        case("optional surface file absent is reported, not failed", 0, "OPTIONAL-ABSENT",
             mp={"root": ".", "surfaces": {"S.md": {}, "Gone.md": {"optional": True}}, "claims": claims})
        scoped = [{"file": "S.md", "pattern": r"denied (\d+) of (\d+)", "keys": ["blind.denied", "blind.denied@denominator"],
                   "scope": ["## New", "## Old"]}]
        sec = "# S\n\n## New\n\nThe guard denied 374 of 391.\n\n## Old\n\nThen it denied 200 of 300.\n"
        case("scope boundary, outside: a wrong number in an older section is not read", 0, "VERDICT: PASS",
             surface=sec, mp={"root": ".", "surfaces": {"S.md": {}}, "claims": scoped})
        case("scope boundary, inside: the same wrong number in the scoped section is red", 1, "MISMATCH",
             surface=sec.replace("374 of 391", "200 of 391"), mp={"root": ".", "surfaces": {"S.md": {}}, "claims": scoped})
        case("scope marker missing", 1, "scope marker not found", surface=sec.replace("## New", "## Fresh"),
             mp={"root": ".", "surfaces": {"S.md": {}}, "claims": scoped})
        case("a key NUMBERS does not have", 1, "NOKEY",
             mp={"root": ".", "surfaces": {"S.md": {}},
                 "claims": claims + [{"file": "S.md", "pattern": r"denied (\d+)", "keys": ["blind.nope"]}]})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    gone = not os.path.exists(tmp)
    if not gone:
        failed += 1
        lines.append("FAIL  temp dir not deleted: %s" % tmp)
    print("\n".join(lines))
    print(BLIND_TO)
    print("SELF-TEST: %d passed, %d failed" % (passed, failed))
    return 0 if failed == 0 else 1


def main(argv):
    if argv[1:2] == ["--self-test"]:
        return self_test()
    args = [a for a in argv[1:] if not a.startswith("--")]
    max_age = 24.0
    if "--max-age-hours" in argv:
        max_age = float(argv[argv.index("--max-age-hours") + 1])
        args = [a for a in args if a != argv[argv.index("--max-age-hours") + 1]]
    if len(args) != 2:
        print(__doc__)
        return 2
    rc, out = run(args[0], args[1], max_age)
    print("\n".join(out))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
