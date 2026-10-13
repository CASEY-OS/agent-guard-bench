#!/usr/bin/env python3
"""real_traffic.py: how often v7, v8 and v9 (variants/) and v10 (guard.py) stop real agent Bash calls.

    python3 real_traffic.py COMMANDS.json [ROOT]

COMMANDS.json is a list of {"command": "..."} objects (one per real call, repeats kept), ROOT the repo root the
guard compares paths to (default: the current directory). Nothing is run: each command is only judged.
Writes results/real_traffic.json with AGGREGATE numbers only. No command text, path or reason detail is
written, because real commands are private; shape ids and reason categories are generic. bench.py prints the
stored file; it cannot recompute it without the commands.
"""
import collections
import importlib.util
import json
import multiprocessing as mp
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_MODS = {}


def _load(name, path):
    if name not in _MODS:
        spec = importlib.util.spec_from_file_location("rt_" + name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MODS[name] = mod
    return _MODS[name]


def _category(reason):
    """A generic category: the reason up to its first parenthesis or colon detail, no paths or values."""
    r = re.sub(r"\s*\(.*", "", reason or "")
    r = re.sub(r"(?<![\w.])/\S*|~\S*", "<path>", r)
    return r[:100]


VERSIONS = (("v7", os.path.join(HERE, "variants", "guard_v7.py")), ("v8", os.path.join(HERE, "variants", "guard_v8.py")),
            ("v9", os.path.join(HERE, "variants", "guard_v9.py")), ("v10", os.path.join(HERE, "guard.py")))
CURRENT = VERSIONS[-1][0]


def work(cmd):
    out = {}
    for name, path in VERSIONS:
        g = _load(name, path)
        t = time.perf_counter()
        d = g.decide_full(cmd)
        out["t_" + name] = time.perf_counter() - t
        out[name] = d["verdict"]
        out[name + "_origin"] = d["origin"]
        out[name + "_shape"] = d["shape"]
        out[name + "_why"] = _category(d.get("irreversible") or "") if d["origin"] == "irreversible" else ""
    return cmd, out


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    os.environ["AGENT_GUARD_ROOT"] = os.path.abspath(argv[1] if len(argv) > 1 else os.getcwd())
    os.environ.pop("AGENT_GUARD_JUDGE", None)          # the optional model judge is never used here
    cmds = [c["command"] for c in json.load(open(argv[0], encoding="utf-8"))]
    uniq = sorted(set(cmds))
    with mp.Pool(min(8, os.cpu_count() or 1)) as p:
        res = dict(p.map(work, uniq, chunksize=200))
    calls = [res[c] for c in cmds]
    n = len(calls)

    def pct(k):
        return round(100.0 * k / n, 2) if n else None
    out = {"calls": n, "unique_commands": len(uniq), "root": "<the repo root given>"}
    for name, _ in VERSIONS:
        d = sum(1 for r in calls if r[name] == "deny")
        rec = sum(1 for r in calls if r[name + "_origin"] == "recoverable")
        secs = sorted(r["t_" + name] for r in res.values())
        v = {"denied": d, "denied_pct": pct(d),
             "denied_by_origin": dict(collections.Counter(r[name + "_origin"] for r in calls if r[name] == "deny")),
             "denied_by_shape": dict(collections.Counter(r[name + "_shape"] for r in calls if r[name] == "deny").most_common())}
        if name != "v7":
            v.update({"recoverable_allowed": rec, "recoverable_pct": pct(rec),
                      "recoverable_by_v7_shape": dict(collections.Counter(r["v7_shape"] for r in calls
                                                                          if r[name + "_origin"] == "recoverable").most_common()),
                      "irreversible_by_category": dict(collections.Counter(r[name + "_why"] for r in calls
                                                                           if r[name + "_origin"] == "irreversible").most_common())})
        if name == CURRENT:
            v.update({"median_ms": round(1000 * secs[len(secs) // 2], 3) if secs else None,
                      "p99_ms": round(1000 * secs[int(len(secs) * .99)], 2) if secs else None})
        out[name] = v
    for a, b in zip(VERSIONS, VERSIONS[1:]):
        out["transitions_%s_to_%s" % (a[0], b[0])] = dict(collections.Counter(
            "%s -> %s" % (r[a[0] + "_origin"] or "allow", r[b[0] + "_origin"] or "allow") for r in calls).most_common())
    # how many calls changed verdict from the previous version to this one, by direction (counts only)
    prev = VERSIONS[-2][0]
    out["changed_%s_to_%s" % (prev, CURRENT)] = {
        "newly_denied": sum(1 for r in calls if r[prev] != "deny" and r[CURRENT] == "deny"),
        "newly_allowed": sum(1 for r in calls if r[prev] == "deny" and r[CURRENT] != "deny"),
        "newly_denied_by_shape": dict(collections.Counter(r[CURRENT + "_shape"] for r in calls
                                                          if r[prev] != "deny" and r[CURRENT] == "deny").most_common())}
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "real_traffic.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("calls %d: " % n + "; ".join(
        "%s denied %d (%.2f%%)%s" % (name, out[name]["denied"], out[name]["denied_pct"],
                                     ", allowed on an undo point %d (%.2f%%)" % (out[name]["recoverable_allowed"],
                                                                                out[name]["recoverable_pct"])
                                     if "recoverable_allowed" in out[name] else "")
        for name, _ in VERSIONS))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
