#!/usr/bin/env python3
"""real_traffic.py: how often v7 (variants/guard_v7.py) and v8 (guard.py) stop real agent Bash calls.

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


def work(cmd):
    g7 = _load("v7", os.path.join(HERE, "variants", "guard_v7.py"))
    g8 = _load("v8", os.path.join(HERE, "guard.py"))
    t = time.perf_counter()
    d7 = g7.decide_full(cmd)
    t7 = time.perf_counter() - t
    t = time.perf_counter()
    d8 = g8.decide_full(cmd)
    t8 = time.perf_counter() - t
    return cmd, {"v7": d7["verdict"], "v7_origin": d7["origin"], "v7_shape": d7["shape"],
                 "v8": d8["verdict"], "v8_origin": d8["origin"], "v8_shape": d8["shape"],
                 "v8_why": _category(d8.get("irreversible") or "") if d8["origin"] == "irreversible" else "",
                 "t7": t7, "t8": t8}


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
    d7 = sum(1 for r in calls if r["v7"] == "deny")
    d8 = sum(1 for r in calls if r["v8"] == "deny")
    rec = sum(1 for r in calls if r["v8_origin"] == "recoverable")
    trans = collections.Counter("%s -> %s" % (r["v7_origin"] or "allow", r["v8_origin"] or "allow") for r in calls)
    secs8 = sorted(r["t8"] for r in res.values())
    out = {
        "calls": n, "unique_commands": len(uniq), "root": "<the repo root given>",
        "v7": {"denied": d7, "denied_pct": pct(d7),
               "denied_by_origin": dict(collections.Counter(r["v7_origin"] for r in calls if r["v7"] == "deny")),
               "denied_by_shape": dict(collections.Counter(r["v7_shape"] for r in calls if r["v7"] == "deny").most_common())},
        "v8": {"denied": d8, "denied_pct": pct(d8), "recoverable_allowed": rec, "recoverable_pct": pct(rec),
               "denied_by_origin": dict(collections.Counter(r["v8_origin"] for r in calls if r["v8"] == "deny")),
               "denied_by_shape": dict(collections.Counter(r["v8_shape"] for r in calls if r["v8"] == "deny").most_common()),
               "recoverable_by_v7_shape": dict(collections.Counter(r["v7_shape"] for r in calls
                                                                   if r["v8_origin"] == "recoverable").most_common()),
               "irreversible_by_category": dict(collections.Counter(r["v8_why"] for r in calls
                                                                    if r["v8_origin"] == "irreversible").most_common()),
               "median_ms": round(1000 * secs8[len(secs8) // 2], 3) if secs8 else None,
               "p99_ms": round(1000 * secs8[int(len(secs8) * .99)], 2) if secs8 else None},
        "transitions_v7_to_v8": dict(trans.most_common()),
    }
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "real_traffic.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("calls %d: v7 denied %d (%.2f%%); v8 denied %d (%.2f%%), allowed on an undo point %d (%.2f%%)"
          % (n, d7, pct(d7), d8, pct(d8), rec, pct(rec)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
