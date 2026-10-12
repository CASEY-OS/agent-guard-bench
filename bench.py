#!/usr/bin/env python3
"""bench.py: run every variant against every case set. One command: python3 bench.py

Variants: no_guard (baseline), naive_regex, guard (the real one), broken_guard (negative control).
Sets: known_bad, known_good, residual, and the two blind holdouts when their files exist
(cases/holdout/holdout.jsonl and cases/holdout2/holdout2.jsonl).
Reports: per set, per policy (A, B, C, none) inside known cases and each holdout, and per class
inside holdout2 (issue-97881, each guardfall-* class, safe), so a reader sees which classes the
guard stops and which it does not.

Scoring. "Positive" means "this command should be blocked".
  known_bad / known_good / holdout / holdout2: positive = expect is "block".
  residual: every case is a policy violation the guard knowingly does not catch. Positive = True.
            A residual the guard allows is a miss (FN). It is reported as a miss, not hidden.
Exit 0 only if all of these hold:
  1. guard.py has zero wrong answers on known_good and known_bad.
  2. broken_guard.py has at least one wrong answer there (the negative control can fail).
  3. guard.py run as a hook (stdin JSON, stdout) agrees with guard.decide() on every case.
  4. broken_guard.py differs from guard.py by exactly one line.
Holdout results (both) never change the exit code. They are reported as they are.

Surface: command strings only. Nothing is ever executed. Blind to: shell state (variables,
aliases, globs), wrappers (bash -c, eval, xargs), scripts, other tools, and anything outside the
Bash command text. See cases/residual.jsonl.
"""
import difflib
import importlib.util
import json
import os
import platform
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PINNED_ROOT = "/work/repo"
os.environ["AGENT_GUARD_ROOT"] = PINNED_ROOT   # the repo root a bare `git add <root>` is compared to

VARIANTS = [
    ("no_guard", os.path.join(HERE, "variants", "no_guard.py")),
    ("naive_regex", os.path.join(HERE, "variants", "naive_regex.py")),
    ("guard", os.path.join(HERE, "guard.py")),
    ("broken_guard", os.path.join(HERE, "variants", "broken_guard.py")),
]
CASE_FILES = [
    ("known_bad", os.path.join(HERE, "cases", "known_bad.jsonl")),
    ("known_good", os.path.join(HERE, "cases", "known_good.jsonl")),
    ("residual", os.path.join(HERE, "cases", "residual.jsonl")),
    ("holdout", os.path.join(HERE, "cases", "holdout", "holdout.jsonl")),
    ("holdout2", os.path.join(HERE, "cases", "holdout2", "holdout2.jsonl")),
]
GUARD_BY_POLICY = {"A": "blanket_stage_guard", "B": "hook_bypass_guard", "C": "data_loss_guard"}
HOLDOUTS = ("holdout", "holdout2")
EXPECT_WORDS = {"block": "block", "deny": "block", "blocked": "block", "denied": "block",
                "allow": "allow", "allowed": "allow", "pass": "allow"}
CLASS_FIELDS = ("class", "category", "bypass_class", "group", "klass", "type", "tag")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location("variant_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_cases(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            for k in ("id", "command", "expect"):
                if k not in row:
                    raise SystemExit("%s line %d: missing %r" % (path, n, k))
            row["expect"] = EXPECT_WORDS.get(str(row["expect"]).strip().lower(), row["expect"])
            if row["expect"] not in ("block", "allow"):
                raise SystemExit("%s line %d: expect must be block or allow, got %r"
                                 % (path, n, row["expect"]))
            rows.append(row)
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise SystemExit("%s: duplicate ids" % path)
    return rows


def truth_positive(set_name, row):
    """Should this command be blocked, by policy?"""
    if set_name == "residual":
        return True
    return row["expect"] == "block"


def policy_of(row):
    return str(row.get("policy", "none")).strip() or "none"


def class_of(row):
    """The class a holdout2 case belongs to: the first class-like field, else the id prefix."""
    for k in CLASS_FIELDS:
        if row.get(k):
            return str(row[k]).strip()
    return "unclassified"


def score(decide, set_name, rows):
    tp = fp = tn = fn = 0
    wrong = []
    for row in rows:
        verdict = decide(row["command"])[0]
        pos, said = truth_positive(set_name, row), verdict == "block"
        if pos and said:
            tp += 1
        elif pos and not said:
            fn += 1
            wrong.append(row["id"])
        elif not pos and said:
            fp += 1
            wrong.append(row["id"])
        else:
            tn += 1
    return {"TP": tp, "FP": fp, "TN": tn, "FN": fn, "wrong": wrong,
            "precision": (tp / float(tp + fp)) if (tp + fp) else None,
            "recall": (tp / float(tp + fn)) if (tp + fn) else None}


def fmt(x):
    return "n/a" if x is None else "%.3f" % x


def median_us(decide, commands, runs=5):
    per_run = []
    for _ in range(runs):
        t0 = time.perf_counter()
        for c in commands:
            decide(c)
        per_run.append((time.perf_counter() - t0) / len(commands) * 1e6)
    return statistics.median(per_run)


def cli_verdict(guard_path, command):
    """Run guard.py as the hook runs it. Returns (verdict, rc)."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    p = subprocess.run([sys.executable, guard_path], input=payload, capture_output=True,
                       text=True, env=dict(os.environ))
    out = p.stdout.strip()
    if not out:
        return "allow", p.returncode
    try:
        d = json.loads(out)
        deny = d.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
        return ("block" if deny else "allow"), p.returncode
    except ValueError:
        return "error", p.returncode


def main():
    mods = {name: load_module(name, path) for name, path in VARIANTS}
    for name in ("guard", "broken_guard"):
        assert mods[name]._root() == PINNED_ROOT, "root pin failed for " + name
    print("Python %s on %s. Root pinned: %s (measured, not the live cwd %s)"
          % (platform.python_version(), platform.system(), PINNED_ROOT, os.getcwd()))

    sets = {}
    for name, path in CASE_FILES:
        if os.path.exists(path):
            sets[name] = load_cases(path)
    holdout_present = "holdout" in sets
    holdout2_present = "holdout2" in sets
    sets_known = sets["known_bad"] + sets["known_good"]
    order = ["known_bad", "known_good", "known_all", "residual"] + (["holdout"] if holdout_present else []) \
        + (["holdout2"] if holdout2_present else [])
    sets["known_all"] = sets_known

    results = {}
    for vname, _ in VARIANTS:
        decide = mods[vname].decide
        results[vname] = {s: score(decide, s, sets[s]) for s in order}

    # per policy inside known cases and each holdout; per class inside holdout2
    by_policy = {}
    for s in ("known_all",) + tuple(h for h in HOLDOUTS if h in sets):
        pols = sorted({policy_of(r) for r in sets[s]})
        by_policy[s] = {p: {v: score(mods[v].decide, s, [r for r in sets[s] if policy_of(r) == p])
                            for v, _ in VARIANTS} for p in pols}
    by_class = {}
    if holdout2_present:
        for c in sorted({class_of(r) for r in sets["holdout2"]}):
            crows = [r for r in sets["holdout2"] if class_of(r) == c]
            by_class[c] = {"n": len(crows),
                           "expect": "/".join(sorted({r["expect"] for r in crows})),
                           "per_variant": {v: score(mods[v].decide, "holdout2", crows)
                                           for v, _ in VARIANTS}}

    timing_cmds = [r["command"] for s in ("known_bad", "known_good", "residual") for r in sets[s]]
    for h in HOLDOUTS:
        if h in sets:
            timing_cmds += [r["command"] for r in sets[h]]
    timing = {v: median_us(mods[v].decide, timing_cmds) for v, _ in VARIANTS}

    # guard.py's reason names the guard the case's policy points at
    named_ok = named_total = 0
    named_bad = []
    for s in ("known_bad",) + HOLDOUTS:
        for row in sets.get(s, []):
            if row["expect"] == "block" and row.get("policy") in GUARD_BY_POLICY:
                verdict, reason = mods["guard"].decide(row["command"])
                if verdict == "block":
                    named_total += 1
                    if reason.startswith(GUARD_BY_POLICY[row["policy"]]):
                        named_ok += 1
                    else:
                        named_bad.append(row["id"])

    # the hook form, run for real, must agree with the library form on every case
    cli_diffs = []
    cli_total = 0
    seen = set()
    for s in ("known_bad", "known_good", "residual") + tuple(h for h in HOLDOUTS if h in sets):
        for row in sets[s]:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            cli_total += 1
            lib = mods["guard"].decide(row["command"])[0]
            cli, rc = cli_verdict(VARIANTS[2][1], row["command"])
            if cli != lib or rc != 0:
                cli_diffs.append(row["id"])

    # residual flips: the guard must still allow what it is documented to allow
    flips = [r["id"] for r in sets["residual"] if mods["guard"].decide(r["command"])[0] != r["expect"]]

    # the negative control differs from guard.py by exactly one line
    a = open(VARIANTS[2][1], encoding="utf-8").read().splitlines()
    b = open(VARIANTS[3][1], encoding="utf-8").read().splitlines()
    changed = [l for l in difflib.unified_diff(a, b, lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]
    one_line = len(changed) == 2

    # ---- conditions ----
    g_err = results["guard"]["known_all"]["FP"] + results["guard"]["known_all"]["FN"]
    b_err = results["broken_guard"]["known_all"]["FP"] + results["broken_guard"]["known_all"]["FN"]
    conds = [
        ("guard.py has zero errors on known_good and known_bad", g_err == 0, "%d errors" % g_err),
        ("broken_guard.py has at least one error (negative control)", b_err >= 1, "%d errors" % b_err),
        ("guard.py hook form agrees with decide() on every case", not cli_diffs,
         "%d of %d differ%s" % (len(cli_diffs), cli_total, (": " + ", ".join(cli_diffs)) if cli_diffs else "")),
        ("broken_guard.py differs from guard.py by exactly one line", one_line, "%d changed lines" % (len(changed) // 2)),
    ]
    ok = all(c[1] for c in conds)

    # ---- output ----
    lines = []
    lines.append("# Results")
    lines.append("")
    lines.append("Python %s on %s. Root pinned to `%s`." % (platform.python_version(), platform.system(), PINNED_ROOT))
    lines.append("Timing: %d decisions per run, median of 5 runs, in-process (no interpreter start-up)."
                 % len(timing_cmds))
    lines.append("Positive means the command should be blocked. In `residual` every case is a policy "
                 "violation the guard knowingly allows, so each one counts as a miss (FN).")
    for h, present in (("holdout", holdout_present), ("holdout2", holdout2_present)):
        if not present:
            lines.append("")
            lines.append("**The blind %s set was not present for this run.**" % h)
    labels = {"known_bad": "known_bad (%d)", "known_good": "known_good (%d)",
              "known_all": "known_bad + known_good (%d)", "residual": "residual (%d)",
              "holdout": "holdout, blind (%d)", "holdout2": "holdout2, blind (%d)"}
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| set | variant | TP | FP | TN | FN | precision | recall |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for s in order:
        if s == "known_all":
            continue
        for vname, _ in VARIANTS:
            r = results[vname][s]
            lines.append("| %s | %s | %d | %d | %d | %d | %s | %s |" % (
                s, vname, r["TP"], r["FP"], r["TN"], r["FN"], fmt(r["precision"]), fmt(r["recall"])))
    for s in order:
        lines.append("")
        lines.append("## " + labels[s] % len(sets[s]))
        lines.append("")
        lines.append("| variant | TP | FP | TN | FN | precision | recall |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for vname, _ in VARIANTS:
            r = results[vname][s]
            lines.append("| %s | %d | %d | %d | %d | %s | %s |" % (
                vname, r["TP"], r["FP"], r["TN"], r["FN"], fmt(r["precision"]), fmt(r["recall"])))
    lines.append("")
    lines.append("## By policy")
    lines.append("")
    lines.append("Cases are grouped by their `policy` field. `none` is a case written to stay clean "
                 "under every policy.")
    lines.append("")
    lines.append("| set | policy | variant | n | TP | FP | TN | FN | precision | recall |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for s, pols in by_policy.items():
        for p, per_v in pols.items():
            for vname, _ in VARIANTS:
                r = per_v[vname]
                lines.append("| %s | %s | %s | %d | %d | %d | %d | %d | %s | %s |" % (
                    s, p, vname, r["TP"] + r["FP"] + r["TN"] + r["FN"], r["TP"], r["FP"], r["TN"],
                    r["FN"], fmt(r["precision"]), fmt(r["recall"])))
    if holdout2_present:
        lines.append("")
        lines.append("## holdout2 by class")
        lines.append("")
        lines.append("Each cell is correct verdicts over cases in the class. For a class whose cases "
                     "expect block, that is the share the variant stops. For the safe class it is the "
                     "share correctly allowed.")
        lines.append("")
        lines.append("| class | expect | n | " + " | ".join(v for v, _ in VARIANTS) + " |")
        lines.append("|---|---|---:|" + "---:|" * len(VARIANTS))
        for c, info in by_class.items():
            cells = ["%d/%d" % (info["per_variant"][v]["TP"] + info["per_variant"][v]["TN"], info["n"])
                     for v, _ in VARIANTS]
            lines.append("| %s | %s | %d | %s |" % (c, info["expect"], info["n"], " | ".join(cells)))
        lines.append("")
        lines.append("Wrong guard.py verdicts by class:")
        lines.append("")
        for c, info in by_class.items():
            w = info["per_variant"]["guard"]["wrong"]
            lines.append("- %s (%d): %s" % (c, len(w), ", ".join(w) if w else "none"))
    lines.append("")
    lines.append("## Timing")
    lines.append("")
    lines.append("| variant | median us/decision |")
    lines.append("|---|---:|")
    for vname, _ in VARIANTS:
        lines.append("| %s | %.1f |" % (vname, timing[vname]))
    lines.append("")
    lines.append("## Wrong cases by id")
    for s in order:
        if s == "known_all":
            continue
        lines.append("")
        lines.append("### " + s)
        for vname, _ in VARIANTS:
            w = results[vname][s]["wrong"]
            lines.append("- %s (%d): %s" % (vname, len(w), ", ".join(w) if w else "none"))
    lines.append("")
    lines.append("## Commands behind guard.py's wrong cases")
    any_wrong = False
    for s in order:
        if s == "known_all":
            continue
        byid = {r["id"]: r for r in sets[s]}
        for cid in results["guard"][s]["wrong"]:
            any_wrong = True
            r = byid[cid]
            lines.append("- `%s` (%s, policy %s): `%s`" % (cid, s, r.get("policy", "?"), json.dumps(r["command"])))
    if not any_wrong:
        lines.append("- none")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    lines.append("- guard.py reason names the policy's guard on %d of %d blocked violations%s."
                 % (named_ok, named_total, (" (off: " + ", ".join(named_bad) + ")") if named_bad else ""))
    lines.append("- Residual cases guard.py still allows as documented: %d of %d%s."
                 % (len(sets["residual"]) - len(flips), len(sets["residual"]),
                    (" (flipped to block: " + ", ".join(flips) + ")") if flips else ""))
    lines.append("- Negative control, the one changed line:")
    lines.append("  - guard.py: `%s`" % next((l[1:].strip() for l in changed if l[0] == "-"), "?"))
    lines.append("  - broken_guard.py: `%s`" % next((l[1:].strip() for l in changed if l[0] == "+"), "?"))
    lines.append("")
    lines.append("Blind to: shell state (variables, aliases, globs), wrappers (`bash -c`, `eval`, `xargs`), "
                 "scripts and interpreters that call git, git config that changes a command's meaning "
                 "(aliases, clean.requireForce), tools other than Bash, and everything outside "
                 "the command text. Nothing is executed. The residual set lists shapes in each class.")
    lines.append("")
    lines.append("## Exit conditions")
    lines.append("")
    for text, passed, detail in conds:
        lines.append("- %s: %s (%s)" % ("PASS" if passed else "FAIL", text, detail))
    lines.append("")
    lines.append("OVERALL: %s" % ("PASS" if ok else "FAIL"))
    md = "\n".join(lines) + "\n"

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "RESULTS.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    out = {"python": platform.python_version(), "root_pinned": PINNED_ROOT,
           "holdout_present": holdout_present, "holdout2_present": holdout2_present,
           "by_policy": by_policy, "by_class": by_class, "timing_us_median": timing,
           "case_counts": {s: len(sets[s]) for s in order},
           "results": results, "checks": {
               "reason_names_guard": {"ok": named_ok, "total": named_total, "off": named_bad},
               "cli_parity_diffs": cli_diffs, "residual_flips": flips, "one_line_diff": one_line},
           "conditions": [{"name": c[0], "pass": c[1], "detail": c[2]} for c in conds],
           "overall": "PASS" if ok else "FAIL"}
    with open(os.path.join(HERE, "results", "results.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
        fh.write("\n")
    sys.stdout.write(md)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
