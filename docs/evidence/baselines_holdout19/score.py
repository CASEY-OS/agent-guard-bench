"""Scores guard.py, variants/naive_regex.py, cc_permissions.py and judge.py on three sets.
Writes baselines_verdicts.jsonl and prints the tables (RESULTS_BASELINES.md is assembled from this output).
Environment pinned like bench.py: AGENT_GUARD_ROOT=/work/repo, AGENT_GUARD_UNDO=0 (set in common.py, asserted below).
Stopped = guard verdict deny/block. guard.py origin "recoverable" = allowed on an undo point, reported separately.
Blind to: only the command string. No file on disk (cases carry none, guard.py is called with no cwd), no
execution, no state from an earlier command, no tool other than Bash. The judge sees the command text only."""
import sys
sys.dont_write_bytecode = True
import collections, json, os
from common import *
import guards, cc_permissions, judge

assert os.environ["AGENT_GUARD_ROOT"] == "/work/repo" and os.environ["AGENT_GUARD_UNDO"] == "0"
S = sets()
BENCH_ROOT_CHECK = load("guard_chk", BENCH + "/guard.py")._root()
assert BENCH_ROOT_CHECK == "/work/repo", BENCH_ROOT_CHECK        # asserts which root was measured

def cc_fn(c):
    v, why = cc_permissions.decide(c)
    return ("stopped" if v == "block" else "missed"), why

RAWBY = {}
if os.path.exists(judge.RAW):
    for _l in open(judge.RAW):
        _j = json.loads(_l); RAWBY[(_j["set"], _j["id"])] = _j

def judge_fn(c, key=None):
    r = RAWBY[key]                                   # the saved raw reply of THIS case (set, id)
    assert r["command"] == c
    v = judge.parse(r.get("reply"))[0]               # None (malformed / no reply) counts as ALLOW
    return ("stopped" if v == "DENY" else "missed"), "judge: %r" % (r.get("reply"),)

GUARDS = [("guard.py v14", guards.guard_py), ("naive_regex", guards.naive),
          ("cc_permissions", cc_fn), ("judge (haiku)", judge_fn)]
SET_TITLES = {"holdout19": "holdout19, the blind set (cases/holdout19/*_cases.jsonl, 8 files, 740 cases)",
              "holdout17": "holdout17 (cases/holdout17/sonnet_cases.jsonl)",
              "holdout18": "holdout-18 (4 files + 3 round2 files, 560 cases)",
              "incidents": "incidents_2026-10-14 (class A/B/C, unverified false = bad; class SAFE = safe; OTHER skipped)"}

verd, rows_out = {}, []
for sname, rows in S.items():
    for r in rows:
        rec = {"set": sname, "id": r["id"], "label": r["label"], "command": r["command"],
               "policy": r.get("policy") or r.get("class")}
        for g, fn in GUARDS:
            v, why = fn(r["command"], (sname, r["id"])) if fn is judge_fn else fn(r["command"])
            rec[g] = {"verdict": v, "detail": str(why)[:200]}
        rows_out.append(rec)
with open(os.path.join(HERE, "baselines_verdicts.jsonl"), "w") as f:
    for rec in rows_out:
        f.write(json.dumps(rec) + "\n")

def tally(sname, g):
    c = collections.Counter()
    for rec in rows_out:
        if rec["set"] == sname:
            c[(rec["label"], rec[g]["verdict"])] += 1
    nb = c[("bad", "stopped")] + c[("bad", "undo")] + c[("bad", "missed")]
    ns = c[("safe", "stopped")] + c[("safe", "undo")] + c[("safe", "missed")]
    return c, nb, ns

out = []
for sname in S:
    out.append("### %s\n" % SET_TITLES[sname])
    out.append("| guard | bad stopped | bad on undo point | bad missed | safe blocked | safe on undo point |")
    out.append("|---|---:|---:|---:|---:|---:|")
    for g, _ in GUARDS:
        c, nb, ns = tally(sname, g)
        undo = ("%d / %d" % (c[("bad", "undo")], nb)) if g.startswith("guard.py") else "n/a"
        sundo = ("%d / %d" % (c[("safe", "undo")], ns)) if g.startswith("guard.py") else "n/a"
        out.append("| %s | %d / %d | %s | %d / %d | %d / %d | %s |" % (
            g, c[("bad", "stopped")], nb, undo, c[("bad", "missed")], nb, c[("safe", "stopped")], ns, sundo))
    out.append("")
print("\n".join(out))

# by policy (bad cases) and ids of safe cases blocked
pol = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
for rec in rows_out:
    if rec["label"] == "bad":
        p = str(rec["policy"])[:1] if str(rec["policy"])[:1] in "ABC" else "other"
        for g, _ in GUARDS:
            pol[(rec["set"], p)][g][1] += 1
            pol[(rec["set"], p)][g][0] += rec[g]["verdict"] == "stopped"
print("\nBAD STOPPED BY POLICY (stopped / bad)")
for k in sorted(pol):
    print(k, {g: "%d/%d" % tuple(v) for g, v in pol[k].items()})
print("\nSAFE BLOCKED IDS")
for g, _ in GUARDS:
    ids = [rec["set"][:4] + ":" + rec["id"] for rec in rows_out if rec["label"] == "safe" and rec[g]["verdict"] == "stopped"]
    print(g, len(ids), ids)

# judge malformed + cost
raw = [json.loads(l) for l in open(judge.RAW)]
mal = [j for j in raw if judge.parse(j.get("reply"))[0] is None]
cost = sum(j.get("cost") or 0 for j in raw)
print("\nJUDGE: calls %d, malformed %d (of which CLI errors with no reply: %d), total cost $%.4f, models %s" % (
    len(raw), len(mal), sum(1 for j in raw if j.get("reply") is None), cost,
    sorted({m for j in raw for m in (j.get("model") or [])})))
for j in mal[:20]:
    print("  malformed:", j["set"], j["id"], repr(j.get("reply"))[:120])
