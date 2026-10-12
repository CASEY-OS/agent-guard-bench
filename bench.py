#!/usr/bin/env python3
"""bench.py: run every variant against every case set. One command: python3 bench.py

Variants: no_guard (baseline), naive_regex, guard_v1 and guard_v2 (frozen copies in variants/),
guard_v3 (guard.py, the real one), broken_guard (negative control for guard.py).
Sets: own cases, split by id: v1_era (no prefix), v2_dev ("v2-"), v3_dev ("v3-"); residual; and the
holdouts when their files exist. Which holdout was blind or a development set for which version is
in HOLDOUT_STATUS and printed with every table.

Verdicts. guard.py returns block, ask or allow. Block and ask both STOP the command: block refuses
it, ask hands it to a human. v1 and v2 only block or allow.
Scoring. "Positive" means "this command should be stopped".
  own cases and holdouts: positive = expect is block, ask or stop.
  residual: every case is a violation the guard knowingly does not stop. Positive = True.
  TP = stopped-bad. FP = stopped-safe, split into FP-block and FP-ask. TN = allowed-safe.
  FN = allowed-bad. The ask rate on safe commands, FP-ask / all safe, is the price of failing closed.
Exit 0 only if all of these hold:
  1. guard.py stops every own bad case and allows every own good case.
  2. guard.py gives the exact verdict (block or ask) every own stop case names.
  3. broken_guard.py has at least one wrong answer on own cases (the negative control can fail).
  4. guard.py run as a hook (stdin JSON, stdout) agrees with guard.decide() on every case.
  5. broken_guard.py differs from guard.py by exactly one line.
  6. Every command guard_v1 or guard_v2 blocks, guard.py also blocks (no v1/v2 block turned soft).
Holdout results never change the exit code.

Surface: command strings only. Nothing is ever executed. The Blind to line at the end of the
output says what the guard cannot see.
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
    ("guard_v1", os.path.join(HERE, "variants", "guard_v1.py")),
    ("guard_v2", os.path.join(HERE, "variants", "guard_v2.py")),
    ("guard_v3", os.path.join(HERE, "guard.py")),
    ("broken_guard", os.path.join(HERE, "variants", "broken_guard.py")),
]
GUARDS = ("guard_v1", "guard_v2", "guard_v3")
CASE_FILES = [
    ("known_bad", os.path.join(HERE, "cases", "known_bad.jsonl")),
    ("known_good", os.path.join(HERE, "cases", "known_good.jsonl")),
    ("residual", os.path.join(HERE, "cases", "residual.jsonl")),
    ("holdout", os.path.join(HERE, "cases", "holdout", "holdout.jsonl")),
    ("holdout2", os.path.join(HERE, "cases", "holdout2", "holdout2.jsonl")),
    ("holdout3", os.path.join(HERE, "cases", "holdout3", "holdout3.jsonl")),
    ("holdout4", os.path.join(HERE, "cases", "holdout4", "holdout4.jsonl")),
]
HOLDOUTS = ("holdout", "holdout2", "holdout3", "holdout4")
HOLDOUT_STATUS = {
    "holdout": "blind for v1; seen before v2 and v3 were built",
    "holdout2": "blind for v1; DEVELOPMENT set for v2; seen before v3",
    "holdout3": "blind for v1 and v2; DEVELOPMENT set for v3",
    "holdout4": "blind for v1, v2 and v3",
}
CLASS_SETS = ("holdout2", "holdout3", "holdout4")
GUARD_BY_POLICY = {"A": "blanket_stage_guard", "B": "hook_bypass_guard", "C": "data_loss_guard"}
EXPECT_WORDS = {"block": "block", "deny": "block", "blocked": "block", "denied": "block",
                "ask": "ask", "stop": "stop", "stopped": "stop",
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
            if row["expect"] not in ("block", "ask", "stop", "allow"):
                raise SystemExit("%s line %d: expect must be block, ask, stop or allow, got %r"
                                 % (path, n, row["expect"]))
            rows.append(row)
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise SystemExit("%s: duplicate ids" % path)
    return rows


def should_stop(set_name, row):
    if set_name == "residual":
        return True
    return row["expect"] in ("block", "ask", "stop")


def policy_of(row):
    return str(row.get("policy", "none")).strip() or "none"


def class_of(row):
    for k in CLASS_FIELDS:
        if row.get(k):
            return str(row[k]).strip()
    return "unclassified"


def score(verdicts, set_name, rows):
    """verdicts: id -> verdict. Counts and the wrong ids."""
    s = {"TP": 0, "TP_block": 0, "TP_ask": 0, "FP_block": 0, "FP_ask": 0, "TN": 0, "FN": 0,
         "wrong": [], "fp_ask_ids": [], "fp_block_ids": [], "fn_ids": []}
    for row in rows:
        v = verdicts[row["id"]]
        stop, pos = v in ("block", "ask"), should_stop(set_name, row)
        if pos and stop:
            s["TP"] += 1
            s["TP_" + v] += 1
        elif pos:
            s["FN"] += 1
            s["wrong"].append(row["id"])
            s["fn_ids"].append(row["id"])
        elif stop:
            s["FP_" + v] += 1
            s["wrong"].append(row["id"])
            s["fp_%s_ids" % v].append(row["id"])
        else:
            s["TN"] += 1
    s["FP"] = s["FP_block"] + s["FP_ask"]
    safe = s["FP"] + s["TN"]
    s["recall"] = s["TP"] / float(s["TP"] + s["FN"]) if (s["TP"] + s["FN"]) else None
    s["ask_rate_safe"] = s["FP_ask"] / float(safe) if safe else None
    s["fp_rate_safe"] = s["FP"] / float(safe) if safe else None
    return s


def fmt(x):
    return "n/a" if x is None else "%.3f" % x


def pct(x):
    return "n/a" if x is None else "%.1f%%" % (100 * x)


def timing_us(decide, commands, runs=5):
    per_run, per_cmd = [], []
    for k in range(runs):
        t0 = time.perf_counter()
        for c in commands:
            t1 = time.perf_counter()
            decide(c)
            if k == 0:
                per_cmd.append((time.perf_counter() - t1) * 1e6)
        per_run.append((time.perf_counter() - t0) / len(commands) * 1e6)
    return statistics.median(per_run), statistics.median(per_cmd), max(per_cmd)


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
        dec = d.get("hookSpecificOutput", {}).get("permissionDecision")
        return {"deny": "block", "ask": "ask"}.get(dec, "allow"), p.returncode
    except ValueError:
        return "error", p.returncode


SET_LABELS = {"v1_era": "own cases, v1 era (%d)", "v2_dev": "own cases written while building v2 (%d)",
              "v3_dev": "own cases written while building v3 (%d)", "own_all": "all own cases (%d)",
              "residual": "residual: violations the guard knowingly misses (%d)"}


def label(s, n):
    if s in HOLDOUT_STATUS:
        return "%s, %s (%d)" % (s, HOLDOUT_STATUS[s], n)
    return SET_LABELS[s] % n


def main():
    mods = {name: load_module(name, path) for name, path in VARIANTS}
    for name in GUARDS + ("broken_guard",):
        assert mods[name]._root() == PINNED_ROOT, "root pin failed for " + name
    names = [v for v, _ in VARIANTS]
    path_of = dict(VARIANTS)
    g3 = mods["guard_v3"]
    print("Python %s on %s. Root pinned: %s (measured, not the live cwd %s)"
          % (platform.python_version(), platform.system(), PINNED_ROOT, os.getcwd()))

    loaded = {}
    for name, path in CASE_FILES:
        if os.path.exists(path):
            loaded[name] = load_cases(path)
    present = {h: h in loaded for h in HOLDOUTS}
    own = loaded["known_bad"] + loaded["known_good"]
    sets = {
        "v1_era": [r for r in own if not r["id"].startswith(("v2-", "v3-"))],
        "v2_dev": [r for r in own if r["id"].startswith("v2-")],
        "v3_dev": [r for r in own if r["id"].startswith("v3-")],
        "own_all": own,
        "residual": loaded["residual"],
    }
    for h in HOLDOUTS:
        if present[h]:
            sets[h] = loaded[h]
    order = ["v1_era", "v2_dev", "v3_dev", "own_all", "residual"] + [h for h in HOLDOUTS if present[h]]

    # one verdict per (variant, case)
    all_rows = {}
    for s in order:
        for r in sets[s]:
            all_rows[r["id"] + "@" + s] = r
    verdicts = {v: {} for v in names}
    reasons = {}
    for v in names:
        for s in order:
            for r in sets[s]:
                if r["id"] not in verdicts[v]:
                    out = mods[v].decide(r["command"])
                    verdicts[v][r["id"]] = out[0]
                    if v == "guard_v3":
                        reasons[r["id"]] = out[1]

    results = {v: {s: score(verdicts[v], s, sets[s]) for s in order} for v in names}

    by_class = {}
    for h in CLASS_SETS:
        if not present[h]:
            continue
        by_class[h] = {}
        for c in sorted({class_of(r) for r in sets[h]}):
            crows = [r for r in sets[h] if class_of(r) == c]
            by_class[h][c] = {"n": len(crows),
                              "expect": "/".join(sorted({r["expect"] for r in crows})),
                              "per_variant": {v: score(verdicts[v], h, crows) for v in names}}
    by_policy = {}
    for s in ["own_all"] + [h for h in HOLDOUTS if present[h]]:
        by_policy[s] = {}
        for p in sorted({policy_of(r) for r in sets[s]}):
            prow = [r for r in sets[s] if policy_of(r) == p]
            by_policy[s][p] = {v: score(verdicts[v], s, prow) for v in GUARDS}

    timing_cmds = [r["command"] for s in order if s != "own_all" for r in sets[s]]
    timing = {v: timing_us(mods[v].decide, timing_cmds) for v in names}

    # exactness on own cases: a case that names block or ask gets exactly that verdict
    inexact = [r["id"] for r in own if r["expect"] in ("block", "ask")
               and verdicts["guard_v3"][r["id"]] != r["expect"]]
    # no v1 or v2 block turned soft
    softened = sorted({r["id"] for s in order for r in sets[s]
                       if (verdicts["guard_v1"][r["id"]] == "block" or verdicts["guard_v2"][r["id"]] == "block")
                       and verdicts["guard_v3"][r["id"]] != "block"})

    # reason names the policy's guard on blocked violations; asks say fail_closed
    named_ok = named_total = 0
    named_bad = []
    for s in order:
        if s in ("own_all", "residual"):
            continue
        for row in sets[s]:
            if should_stop(s, row) and row.get("policy") in GUARD_BY_POLICY \
                    and verdicts["guard_v3"][row["id"]] == "block":
                named_total += 1
                if reasons[row["id"]].startswith(GUARD_BY_POLICY[row["policy"]]):
                    named_ok += 1
                else:
                    named_bad.append(row["id"])
    asks_named = all(reasons[i].startswith("fail_closed") for i, v in verdicts["guard_v3"].items() if v == "ask")

    # the hook form, run for real, must agree with the library form on every case
    cli_diffs, cli_total, seen = [], 0, set()
    for s in order:
        for row in sets[s]:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            cli_total += 1
            cli, rc = cli_verdict(path_of["guard_v3"], row["command"])
            if cli != verdicts["guard_v3"][row["id"]] or rc != 0:
                cli_diffs.append(row["id"])

    flips = [r["id"] for r in sets["residual"] if verdicts["guard_v3"][r["id"]] != "allow"]

    # verdict changes v2 -> v3, judged as stopped / allowed
    changes, regressions = {}, []
    for s in order:
        if s == "own_all":
            continue
        fixed, worse = [], []
        for row in sets[s]:
            a2 = verdicts["guard_v2"][row["id"]] in ("block", "ask")
            a3 = verdicts["guard_v3"][row["id"]] in ("block", "ask")
            if a2 == a3:
                continue
            want = should_stop(s, row)
            (fixed if a3 == want else worse).append(row["id"])
        changes[s] = {"fixed": fixed, "worse": worse}
        regressions += [s + ":" + i for i in worse]

    a = open(path_of["guard_v3"], encoding="utf-8").read().splitlines()
    b = open(path_of["broken_guard"], encoding="utf-8").read().splitlines()
    changed = [l for l in difflib.unified_diff(a, b, lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]
    one_line = len(changed) == 2

    own3, ownb = results["guard_v3"]["own_all"], results["broken_guard"]["own_all"]
    g_err, b_err = own3["FP"] + own3["FN"], ownb["FP"] + ownb["FN"]
    conds = [
        ("guard.py stops every own bad case and allows every own good case", g_err == 0, "%d errors" % g_err),
        ("guard.py gives the exact verdict (block or ask) each own stop case names", not inexact,
         "%d differ%s" % (len(inexact), (": " + ", ".join(inexact)) if inexact else "")),
        ("broken_guard.py has at least one error on own cases (negative control)", b_err >= 1, "%d errors" % b_err),
        ("guard.py hook form agrees with decide() on every case", not cli_diffs,
         "%d of %d differ%s" % (len(cli_diffs), cli_total, (": " + ", ".join(cli_diffs)) if cli_diffs else "")),
        ("broken_guard.py differs from guard.py by exactly one line", one_line, "%d changed lines" % (len(changed) // 2)),
        ("every command v1 or v2 blocks, guard.py still blocks", not softened,
         "%d softened%s" % (len(softened), (": " + ", ".join(softened)) if softened else "")),
    ]
    ok = all(c[1] for c in conds)

    L = []
    L.append("# Results")
    L.append("")
    L.append("Python %s on %s. Root pinned to `%s`." % (platform.python_version(), platform.system(), PINNED_ROOT))
    L.append("`guard_v1` and `guard_v2` are frozen copies in `variants/`. `guard_v3` is `guard.py`. "
             "Stopped means block or ask. TP stopped-bad, FP stopped-safe (block / ask), TN allowed-safe, "
             "FN allowed-bad. In `residual` every case is a violation, so an allow is a miss.")
    for h in HOLDOUTS:
        if not present[h]:
            L.append("")
            L.append("**The %s set was not present for this run.**" % h)
    L.append("")
    L.append("## Every holdout, v1 / v2 / v3")
    L.append("")
    L.append("| set | status | n | variant | TP | FP block | FP ask | TN | FN | recall | ask rate on safe |")
    L.append("|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|")
    for h in [h for h in HOLDOUTS if present[h]]:
        for v in GUARDS:
            r = results[v][h]
            L.append("| %s | %s | %d | %s | %d | %d | %d | %d | %d | %s | %s |" % (
                h, HOLDOUT_STATUS[h], len(sets[h]), v, r["TP"], r["FP_block"], r["FP_ask"], r["TN"],
                r["FN"], fmt(r["recall"]), pct(r["ask_rate_safe"])))
    L.append("")
    L.append("## Summary, every set and variant")
    L.append("")
    L.append("| set | variant | TP | FP block | FP ask | TN | FN | recall | ask rate on safe |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for s in order:
        for v in names:
            r = results[v][s]
            L.append("| %s | %s | %d | %d | %d | %d | %d | %s | %s |" % (
                s, v, r["TP"], r["FP_block"], r["FP_ask"], r["TN"], r["FN"], fmt(r["recall"]),
                pct(r["ask_rate_safe"])))
    L.append("")
    L.append("## The price of failing closed: guard_v3 ask rate on safe commands")
    L.append("")
    L.append("| set | safe commands | asked | blocked | ask rate | any-stop rate |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for s in order:
        r = results["guard_v3"][s]
        safe = r["FP"] + r["TN"]
        if safe:
            L.append("| %s | %d | %d | %d | %s | %s |" % (s, safe, r["FP_ask"], r["FP_block"],
                                                         pct(r["ask_rate_safe"]), pct(r["fp_rate_safe"])))
    for s in order:
        L.append("")
        L.append("## " + label(s, len(sets[s])))
        L.append("")
        L.append("| variant | TP (block / ask) | FP block | FP ask | TN | FN | recall |")
        L.append("|---|---:|---:|---:|---:|---:|---:|")
        for v in names:
            r = results[v][s]
            L.append("| %s | %d (%d / %d) | %d | %d | %d | %d | %s |" % (
                v, r["TP"], r["TP_block"], r["TP_ask"], r["FP_block"], r["FP_ask"], r["TN"], r["FN"],
                fmt(r["recall"])))
    L.append("")
    L.append("## By policy (guard versions)")
    L.append("")
    L.append("| set | policy | variant | n | TP | FP block | FP ask | TN | FN |")
    L.append("|---|---|---|---:|---:|---:|---:|---:|---:|")
    for s, pols in by_policy.items():
        for p, per_v in pols.items():
            for v in GUARDS:
                r = per_v[v]
                L.append("| %s | %s | %s | %d | %d | %d | %d | %d | %d |" % (
                    s, p, v, r["TP"] + r["FP"] + r["TN"] + r["FN"], r["TP"], r["FP_block"], r["FP_ask"],
                    r["TN"], r["FN"]))
    for h, classes in by_class.items():
        L.append("")
        L.append("## %s by class (%s)" % (h, HOLDOUT_STATUS[h]))
        L.append("")
        L.append("Each cell is correct verdicts over cases in the class (stopped for a stop class, allowed "
                 "for the safe class).")
        L.append("")
        L.append("| class | expect | n | " + " | ".join(names) + " |")
        L.append("|---|---|---:|" + "---:|" * len(names))
        for c, info in classes.items():
            cells = ["%d/%d" % (info["per_variant"][v]["TP"] + info["per_variant"][v]["TN"], info["n"])
                     for v in names]
            L.append("| %s | %s | %d | %s |" % (c, info["expect"], info["n"], " | ".join(cells)))
        for v in GUARDS:
            L.append("")
            L.append("Wrong %s verdicts by class:" % v)
            L.append("")
            for c, info in classes.items():
                w = info["per_variant"][v]["wrong"]
                L.append("- %s (%d): %s" % (c, len(w), ", ".join(w) if w else "none"))
    L.append("")
    L.append("## Verdicts that changed from guard_v2 to guard_v3 (stopped versus allowed)")
    L.append("")
    L.append("| set | fixed | worse |")
    L.append("|---|---:|---:|")
    for s, c in changes.items():
        L.append("| %s | %d | %d |" % (s, len(c["fixed"]), len(c["worse"])))
    L.append("")
    L.append("Cases where v3 is worse than v2: %s." % (", ".join(regressions) if regressions else "none"))
    L.append("")
    L.append("## Timing")
    L.append("")
    L.append("%d decisions per run, in-process (no interpreter start-up)." % len(timing_cmds))
    L.append("")
    L.append("| variant | mean us/decision (median of 5 runs) | median us per command | slowest command us |")
    L.append("|---|---:|---:|---:|")
    for v in names:
        L.append("| %s | %.1f | %.1f | %.0f |" % ((v,) + timing[v]))
    L.append("")
    L.append("## guard_v3 wrong verdicts with their commands")
    for s in order:
        if s == "own_all":
            continue
        byid = {r["id"]: r for r in sets[s]}
        r3 = results["guard_v3"][s]
        if not r3["wrong"]:
            continue
        L.append("")
        L.append("### %s" % s)
        for kind, key in (("miss", "fn_ids"), ("false positive, block", "fp_block_ids"),
                          ("false positive, ask", "fp_ask_ids")):
            for cid in r3[key]:
                r = byid[cid]
                L.append("- %s `%s` (policy %s, class %s): `%s`" % (
                    kind, cid, r.get("policy", "?"), class_of(r), json.dumps(r["command"])))
                if reasons.get(cid):
                    L.append("  - reason: %s" % reasons[cid][:200])
    L.append("")
    L.append("## Checks")
    L.append("")
    L.append("- guard.py reason names the policy's guard on %d of %d blocked violations%s."
             % (named_ok, named_total, (" (off: " + ", ".join(named_bad) + ")") if named_bad else ""))
    L.append("- Every ask reason starts with `fail_closed`: %s." % ("yes" if asks_named else "NO"))
    L.append("- Residual cases guard.py still allows as documented: %d of %d%s."
             % (len(sets["residual"]) - len(flips), len(sets["residual"]),
                (" (now stopped: " + ", ".join(flips) + ")") if flips else ""))
    L.append("- Negative control, the one changed line:")
    L.append("  - guard.py: `%s`" % next((l[1:].strip() for l in changed if l[0] == "-"), "?"))
    L.append("  - broken_guard.py: `%s`" % next((l[1:].strip() for l in changed if l[0] == "+"), "?"))
    L.append("")
    L.append("Blind to: a script FILE run by name that this command did not write (sh x.sh, python3 "
             "x.py, make), config or aliases set by an earlier tool call that change what a plain git "
             "command does (remote.*.push, clean.requireForce, push.default), a variable or cwd set by an "
             "earlier tool call when the command uses it in a place the guard judges harmless (a git log "
             "argument), programs other than git that rewrite history or delete work without naming .git "
             "or a hooks path, an archive or patch applied over the hooks, a container image's "
             "entrypoint, tools other than Bash, and anything outside the command text. Nothing is executed. Unresolved parts that could matter are asked about, "
             "not allowed.")
    L.append("")
    L.append("## Exit conditions")
    L.append("")
    for text, passed, detail in conds:
        L.append("- %s: %s (%s)" % ("PASS" if passed else "FAIL", text, detail))
    L.append("")
    L.append("OVERALL: %s" % ("PASS" if ok else "FAIL"))
    md = "\n".join(L) + "\n"

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "RESULTS.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    slim = {v: {s: {k: x for k, x in r.items()} for s, r in per.items()} for v, per in results.items()}
    out = {"python": platform.python_version(), "root_pinned": PINNED_ROOT, "holdouts_present": present,
           "holdout_status": HOLDOUT_STATUS, "case_counts": {s: len(sets[s]) for s in order},
           "results": slim, "by_class": by_class, "by_policy": by_policy,
           "timing_us": {v: {"mean_median_of_runs": t[0], "median_per_command": t[1], "max": t[2]}
                         for v, t in timing.items()},
           "v2_to_v3_changes": changes,
           "checks": {"reason_names_guard": {"ok": named_ok, "total": named_total, "off": named_bad},
                      "asks_named_fail_closed": asks_named, "cli_parity_diffs": cli_diffs,
                      "residual_now_stopped": flips, "one_line_diff": one_line, "inexact": inexact,
                      "softened_v1_v2_blocks": softened},
           "conditions": [{"name": c[0], "pass": c[1], "detail": c[2]} for c in conds],
           "overall": "PASS" if ok else "FAIL"}
    with open(os.path.join(HERE, "results", "results.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
        fh.write("\n")
    sys.stdout.write(md)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
