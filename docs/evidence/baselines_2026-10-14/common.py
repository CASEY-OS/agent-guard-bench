"""Shared loader for the baseline scorer. READ-ONLY on ~/agent-guard-bench and ~/agent-guard-bench-holdout-18."""
import sys, os, json, glob, importlib.util
sys.dont_write_bytecode = True                       # never write __pycache__ into the bench repo
BENCH = os.path.expanduser("~/agent-guard-bench")
H18 = os.path.expanduser("~/agent-guard-bench-holdout-18")
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["AGENT_GUARD_ROOT"] = "/work/repo"
os.environ["AGENT_GUARD_UNDO"] = "0"
os.environ.pop("AGENT_GUARD_JUDGE", None)

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def read_jsonl(p):
    with open(p) as f:
        return [json.loads(l) for l in f if l.strip()]

def sets():
    """-> ordered dict set_name -> list of rows with id, command, label ('bad'|'safe')."""
    out = {}
    rows = read_jsonl(BENCH + "/cases/holdout17/sonnet_cases.jsonl")
    out["holdout17"] = [dict(r, label="bad" if r["expect"] in ("stop", "block", "ask") else "safe") for r in rows]
    rows = []
    for p in sorted(glob.glob(H18 + "/*_cases.jsonl")) + sorted(glob.glob(H18 + "/round2/*_cases.jsonl")):
        src = os.path.relpath(p, H18)
        for r in read_jsonl(p):
            rows.append(dict(r, label="bad" if r["expect"] in ("stop", "block", "ask") else "safe", src=src))
    out["holdout18"] = rows
    inc = []
    for r in read_jsonl(H18 + "/incidents_2026-10-14/incidents.jsonl"):
        c = r.get("class")
        if c in ("A", "B", "C") and not r.get("unverified"):
            inc.append(dict(r, label="bad"))
        elif c == "SAFE":
            inc.append(dict(r, label="safe"))
    out["incidents"] = inc
    return out
