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
NUMBERS list), text (exact), under (the claim is a stated upper bound: it agrees when the NUMBERS value, times
"scale", is below it; for a figure that moves with machine and load, such as a timing), sole (the NUMBERS list holds exactly one
item and it is the claim, word for word), pct (the claim is a percent; it agrees when 100 x the key's value / the key's
denominator, rounded to the claim's decimals, equals it), sum (every number the pattern captures is added and the total
is the one key's value: a table row of parts against its stated total; it does not check each part alone), const (a
figure fixed by construction and never measured, such as the no-guard row's zeros: "expect" lists the text each
captured group must be, in order, and "keys" are only labels, never looked up). Paths may be absolute, ~ or relative to the root. Every match of a pattern is checked,
not only the first. A claim with "when": {"python": "3.14"} is checked only when NUMBERS.json's own python field is that version
(whole version parts: 3.14 matches 3.14.5, 3.1 does not); otherwise each match prints SKIPPED and is counted in the
summary, never failed, and a missing phrase is still MISSING. A claim with "scope": [start, end] reads only the text from the first start marker to the next
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
            "outside a claim's scoped section, a claim whose \"when\" condition does not hold for the interpreter that made "
            "NUMBERS (SKIPPED and counted, not checked), a surface file the map does not list, what the sentence around a number means (it compares the digits a pattern "
            "captures, nothing else), and whether NUMBERS.json itself is right (bench.py makes it; this only checks "
            "that surfaces agree with it), the split inside a sum claim (only the total is checked, so two parts that trade "
            "places stay green), and any figure a const claim pins (it is compared with the text the map states, never "
            "with a measurement).")


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
    if kind == "sole":
        return isinstance(value, list) and value == [claim], (" | ".join(map(str, value)) if isinstance(value, list)
                                                              else repr(value))
    if kind == "sum":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False, repr(value)
        total = sum(to_num(g)[0] for g in claim)
        return abs(total - value) < 1e-9, "%g" % value
    if kind == "pct":
        if not (isinstance(value, tuple) and len(value) == 2):
            return False, repr(value)
        c, dec = to_num(claim)
        v = round(100.0 * value[0] / value[1], dec)
        return abs(c - v) < 1e-9, ("%." + str(dec) + "f") % v
    if kind == "under":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False, repr(value)
        return value * scale < to_num(claim)[0], "%g" % (value * scale)
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
    n_claims = n_ok = n_mis = n_missing = n_skip = 0
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
        unmet = []                         # "when": {key: version}: the claim holds only where NUMBERS was made there
        for wk, wv in sorted((c.get("when") or {}).items()):
            found, have = lookup(numbers, wk)
            if not found:
                bad += 1
                n_mis += 1
                out.append("NOKEY    %s  condition %s=%s  NUMBERS has no %s, so the claim cannot be placed"
                           % (f, wk, wv, wk))
                unmet = None
                break
            if not (str(have) == str(wv) or str(have).startswith(str(wv) + ".")):
                unmet.append("%s %s != %s" % (wk, have, wv))
        if unmet is None:
            continue
        for m in matches:
            line = full_text.count("\n", 0, base + m.start()) + 1
            groups = m.groups() or (m.group(0),)
            if unmet:
                for key, claim in zip(c["keys"], groups):
                    n_skip += 1
                    out.append("SKIPPED  %s:%d  %s  claim %s  (%s)" % (f, line, key, claim.strip(), "; ".join(unmet)))
                continue
            kind = c.get("type", "number")
            if kind == "sum":              # the captured parts add up to the one key's value
                n_claims += 1
                key = c["keys"][0]
                found, value = lookup(numbers, key)
                shown_claim = "+".join(g.strip() for g in groups)
                if not found:
                    bad += 1
                    n_mis += 1
                    out.append("NOKEY    %s:%d  %s  claim %r  NUMBERS has no such key" % (f, line, key, shown_claim))
                    continue
                okk, shown = compare("sum", groups, value)
                if okk:
                    n_ok += 1
                    out.append("OK       %s:%d  %s  claim %s  NUMBERS %s" % (f, line, key, shown_claim, shown))
                else:
                    bad += 1
                    n_mis += 1
                    out.append("MISMATCH %s:%d  %s  claim %s  NUMBERS %s" % (f, line, key, shown_claim, shown))
                continue
            for idx, (key, claim) in enumerate(zip(c["keys"], groups)):
                n_claims += 1
                if kind == "const":        # fixed by construction: the map states the text, nothing is looked up
                    expect = c.get("expect") or []
                    found, value = idx < len(expect), (expect[idx] if idx < len(expect) else None)
                    kind_used = "text"
                else:
                    found, value = lookup(numbers, key)
                    kind_used = kind
                    if found and kind == "pct":
                        got_den, den = lookup(numbers, key + "@denominator")
                        ok_num = (isinstance(value, (int, float)) and not isinstance(value, bool)
                                  and isinstance(den, (int, float)) and not isinstance(den, bool) and den)
                        found, value = bool(got_den and ok_num), ((value, den) if got_den and ok_num else None)
                if not found:
                    bad += 1
                    n_mis += 1
                    out.append("NOKEY    %s:%d  %s  claim %r  NUMBERS has no such key" % (f, line, key, claim))
                    continue
                okk, shown = compare(kind_used, claim, value, float(c.get("scale", 1.0)))
                if okk:
                    n_ok += 1
                    out.append("OK       %s:%d  %s  claim %s  NUMBERS %s" % (f, line, key, claim.strip(), shown))
                else:
                    bad += 1
                    n_mis += 1
                    out.append("MISMATCH %s:%d  %s  claim %s  NUMBERS %s" % (f, line, key, claim.strip(), shown))
    out.append("SURFACES: %d files, %d claims checked, %d agree, %d disagree, %d SKIPPED, %d patterns missing"
               % (len(texts), n_claims, n_ok, n_mis, n_skip, n_missing))
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
                              "commit": {"value": "e88a7d8"}, "big": {"value": 68636},
                              "parts": {"value": 17}}}
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
        # "when": a claim measured on one interpreter is checked only against NUMBERS made on that interpreter
        def py(v):
            d = numbers()
            d["python"] = v
            return d
        cond = [{"file": "S.md", "pattern": r"Slowest ([0-9.]+) s on Python 3\.14", "keys": ["blind.secs"],
                 "when": {"python": "3.14"}}]
        csurf = "# S\n\nSlowest 0.014 s on Python 3.14.\n"
        cmap = {"root": ".", "surfaces": {"S.md": {}}, "claims": cond}
        case("condition met, clean control: the claim is checked and agrees", 0, "0 SKIPPED", surface=csurf,
             nums=py("3.14.5"), mp=cmap)
        case("condition met, planted mismatch: the condition hides nothing where it applies", 1, "MISMATCH",
             surface=csurf.replace("0.014", "0.029"), nums=py("3.14.5"), mp=cmap)
        case("condition unmet: the same wrong number is SKIPPED, counted, not failed", 0,
             "SKIPPED  S.md:3  blind.secs  claim 0.029  (python 3.9.6 != 3.14)", surface=csurf.replace("0.014", "0.029"),
             nums=py("3.9.6"), mp=cmap)
        case("condition boundary: 3.1 does not match 3.14.5 (whole version parts, not a string prefix)", 0, "1 SKIPPED",
             surface=csurf.replace("Python 3.14", "Python 3.1"), nums=py("3.14.5"),
             mp={"root": ".", "surfaces": {"S.md": {}},
                 "claims": [dict(cond[0], pattern=r"Slowest ([0-9.]+) s on Python 3\.1\b", when={"python": "3.1"})]})
        case("condition unmet but the phrase is gone: still MISSING", 1, "MISSING", surface="# S\n\nFast.\n",
             nums=py("3.9.6"), mp=cmap)
        case("a condition NUMBERS cannot answer", 1, "cannot be placed", surface=csurf, nums=numbers(), mp=cmap)
        # "under": a stated upper bound for a figure that moves with machine and load
        bound = [{"file": "S.md", "pattern": r"Slowest under ([0-9.]+) s", "keys": ["blind.secs"], "type": "under"}]
        bmap = {"root": ".", "surfaces": {"S.md": {}}, "claims": bound}
        case("bound, clean control: 0.0142 under 0.1 agrees", 0, "VERDICT: PASS", surface="# S\n\nSlowest under 0.1 s.\n",
             mp=bmap)
        case("bound, planted violation: 0.0142 is not under 0.01", 1, "MISMATCH",
             surface="# S\n\nSlowest under 0.01 s.\n", mp=bmap)
        case("bound boundary: a value equal to the bound is not under it", 1, "MISMATCH",
             surface="# S\n\nSlowest under 0.0142 s.\n", mp=bmap)
        # "sole": the list holds exactly the one item the surface names
        sole = [{"file": "S.md", "pattern": r"one command, `([^`]+)`, carries", "keys": ["blind.both"], "type": "sole"}]
        smap = {"root": ".", "surfaces": {"S.md": {}}, "claims": sole}
        def nb(v):
            d = numbers()
            d["blind"]["both"] = {"value": v}
            return d
        case("sole, clean control: the one item, word for word", 0, "VERDICT: PASS",
             surface="# S\n\nAnd one command, `git add $(x)`, carries both.\n", nums=nb(["git add $(x)"]), mp=smap)
        case("sole, planted violation: a second item in the list", 1, "MISMATCH",
             surface="# S\n\nAnd one command, `git add $(x)`, carries both.\n", nums=nb(["git add $(x)", "y"]), mp=smap)
        case("sole, planted violation: a different command", 1, "MISMATCH",
             surface="# S\n\nAnd one command, `git add $(y)`, carries both.\n", nums=nb(["git add $(x)"]), mp=smap)
        # "pct": a stated percent against value / denominator
        pctm = {"root": ".", "surfaces": {"S.md": {}},
                "claims": [{"file": "S.md", "pattern": r"Ratio ([0-9.]+)%", "keys": ["blind.denied"], "type": "pct"}]}
        case("pct, clean control: 374 of 391 is 95.7%", 0, "VERDICT: PASS", surface="# S\n\nRatio 95.7%\n", mp=pctm)
        case("pct, planted violation: 95.8% where 374 of 391 is 95.7%", 1, "MISMATCH", surface="# S\n\nRatio 95.8%\n",
             mp=pctm)
        case("pct, rounds to the claim's own decimals: 96% passes", 0, "VERDICT: PASS",
             surface="# S\n\nRatio 96%\n", mp=pctm)
        case("pct, planted violation with no decimals: 95%", 1, "MISMATCH", surface="# S\n\nRatio 95%\n", mp=pctm)
        case("pct on a key with no denominator", 1, "NOKEY", surface="# S\n\nRatio 95.7%\n",
             mp={"root": ".", "surfaces": {"S.md": {}},
                 "claims": [{"file": "S.md", "pattern": r"Ratio ([0-9.]+)%", "keys": ["blind.secs"], "type": "pct"}]})
        # "sum": the captured parts add up to the key's value
        summ = {"root": ".", "surfaces": {"S.md": {}},
                "claims": [{"file": "S.md", "pattern": r"Parts (\d+), (\d+), (\d+) in all", "keys": ["blind.parts"],
                            "type": "sum"}]}
        case("sum, clean control: 8 + 6 + 3 is 17", 0, "VERDICT: PASS", surface="# S\n\nParts 8, 6, 3 in all\n", mp=summ)
        case("sum, planted violation: 8 + 6 + 4 is not 17", 1, "MISMATCH", surface="# S\n\nParts 8, 6, 4 in all\n",
             mp=summ)
        case("sum, inside the declared blind spot: two parts trade places, the total holds, it stays green", 0,
             "VERDICT: PASS", surface="# S\n\nParts 3, 6, 8 in all\n", mp=summ)
        case("sum on a key NUMBERS does not have", 1, "NOKEY", surface="# S\n\nParts 8, 6, 3 in all\n",
             mp={"root": ".", "surfaces": {"S.md": {}},
                 "claims": [dict(summ["claims"][0], keys=["blind.nope"])]})
        # "const": a figure fixed by construction, compared with the text the map states
        constm = {"root": ".", "surfaces": {"S.md": {}},
                  "claims": [{"file": "S.md", "pattern": r"No guard (\d+) of (\d+)", "keys": ["a label", "another label"],
                              "type": "const", "expect": ["0", "12"]}]}
        case("const, clean control: 0 and 12 as the map states", 0, "VERDICT: PASS", surface="# S\n\nNo guard 0 of 12\n",
             mp=constm)
        case("const, planted violation: 1 where the map states 0", 1, "MISMATCH", surface="# S\n\nNo guard 1 of 12\n",
             mp=constm)
        case("const with no expected text for a captured group", 1, "NOKEY", surface="# S\n\nNo guard 0 of 12\n",
             mp={"root": ".", "surfaces": {"S.md": {}},
                 "claims": [dict(constm["claims"][0], expect=["0"])]})
        case("a key NUMBERS does not have", 1, "NOKEY",
             mp={"root": ".", "surfaces": {"S.md": {}},
                 "claims": claims + [{"file": "S.md", "pattern": r"denied (\d+)", "keys": ["blind.nope"]}]})
        # The live map and the live README table, each case on a copy built at run time: a planted drift in the top
        # table must read red, the clean copy must read green, and one drift outside the declared blind spots must stay green.
        here = os.path.dirname(os.path.abspath(__file__))
        repo = os.path.realpath(os.path.join(here, ".."))
        live = ["tools/SURFACE_MAP.json", "results/NUMBERS.json", "README.md", "results/SUMMARY.md", "docs/METHOD.md",
                "CHANGELOG.md"]
        if not all(os.path.isfile(os.path.join(repo, f)) for f in live):
            lines.append("SKIPPED ON THIS HOST: the live table cases need %s under %s" % (", ".join(live), repo))
        else:
            def live_case(name, want_rc, want_text, readme_edit=None, nums_edit=None, problems_want=None):
                nonlocal passed, failed
                d = tempfile.mkdtemp(prefix="live-", dir=tmp)
                for f in live:
                    os.makedirs(os.path.dirname(os.path.join(d, f)), exist_ok=True)
                    shutil.copyfile(os.path.join(repo, f), os.path.join(d, f))
                if readme_edit:
                    rp = os.path.join(d, "README.md")
                    body = open(rp, encoding="utf-8").read()
                    new_body = readme_edit(body)
                    assert new_body != body, "the planted edit changed nothing: %s" % name
                    open(rp, "w", encoding="utf-8").write(new_body)
                if nums_edit:
                    np_ = os.path.join(d, "results", "NUMBERS.json")
                    nd = json.load(open(np_, encoding="utf-8"))
                    nums_edit(nd)
                    json.dump(nd, open(np_, "w", encoding="utf-8"), indent=1)
                p = subprocess.run([sys.executable, os.path.abspath(__file__), os.path.join(d, "results", "NUMBERS.json"),
                                    os.path.join(d, "tools", "SURFACE_MAP.json"), "--max-age-hours", "1000000"],
                                   capture_output=True, text=True)
                measured = re.search(r"^Measured root: (.*)$", p.stdout, re.M)
                problems = len(re.findall(r"^(MISMATCH|MISSING|STALE|NOFILE|NOKEY|UNMAPPED)", p.stdout, re.M))
                ok = (p.returncode == want_rc and want_text in p.stdout and measured
                      and measured.group(1) == os.path.realpath(d) and "VERDICT:" in p.stdout
                      and (problems_want is None or problems == problems_want))
                passed, failed = passed + bool(ok), failed + (not ok)
                lines.append("%s  live table: %s (exit %d, wanted %d; '%s' %s; %d problem lines)" % (
                    "pass" if ok else "FAIL", name, p.returncode, want_rc, want_text,
                    "seen" if want_text in p.stdout else "NOT seen", problems))

            def in_row(prefix, old, new):
                def edit(body):
                    out, hit = [], False
                    for ln in body.split("\n"):
                        if not hit and ln.startswith(prefix) and old in ln:
                            ln, hit = ln.replace(old, new, 1), True
                        out.append(ln)
                    return "\n".join(out)
                return edit
            v22 = "| agent-guard v22, the version the plugin runs"
            v20 = "| agent-guard v20, the last version scored blind"
            live_case("clean control, the README as committed", 0, "VERDICT: PASS", problems_want=0)
            live_case("planted drift: v22 row says 1,687 denied", 1, "MISMATCH", in_row(v22, "1,688", "1,687"), problems_want=1)
            live_case("planted drift: v20 row says 33 safe wrongly denied", 1, "MISMATCH", in_row(v20, "32 of", "33 of"),
                      problems_want=1)
            live_case("planted drift: v20 row says 98.4% where 1,688 of 1,717 is 98.3%", 1, "MISMATCH",
                      in_row(v20, "98.3%", "98.4%"), problems_want=1)
            live_case("planted drift: the no-guard row says 1 denied", 1, "MISMATCH", in_row("| No guard", "| 0 of", "| 1 of"),
                      problems_want=1)
            live_case("planted drift: the no-guard row says 1,716 missed", 1, "MISMATCH",
                      lambda b: b.replace("| 1,717 |\n| agent-guard v22", "| 1,716 |\n| agent-guard v22", 1), problems_want=1)
            live_case("planted drift: the by-type line says 9 encoded, so the parts no longer add to 21", 1, "MISMATCH",
                      lambda b: b.replace("21 misses, by how the command hid what it does: 8 encoded, 6", "21 misses, by how the command hid what it does: 9 encoded, 6", 1) if "Version 20's 21 misses" in b else b,
                      problems_want=1)
            live_case("planted drift: NUMBERS says 1,600 denied, the README says 1,688", 1, "MISMATCH",
                      nums_edit=lambda n: n["versions"]["lead"]["denied"].__setitem__("value", 1600))
            live_case("outside the blind spots, caught: the guard version reads 21 where NUMBERS says 22", 1, "MISMATCH",
                      lambda b: b.replace("the file the plugin runs, is version 22", "the file the plugin runs, is version 21", 1),
                      problems_want=1)
            live_case("inside the declared blind spot: a number written in words changes, it stays green", 0, "VERDICT: PASS",
                      lambda b: b.replace("nine other companies wrote and that were sealed", "ten other companies wrote and that were sealed", 1),
                      problems_want=0)
            live_case("inside the declared blind spot: two by-type parts trade places, the total holds, it stays green", 0,
                      "VERDICT: PASS",
                      lambda b: b.replace("Version 20's 21 misses, by how the command hid what it does: 8 encoded, 6 written", "Version 20's 21 misses, by how the command hid what it does: 6 encoded, 8 written", 1),
                      problems_want=0)
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
