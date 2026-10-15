"""Shared loader for the baseline scorer. READ-ONLY on ~/agent-guard-bench."""
import sys, os, json, glob, importlib.util
sys.dont_write_bytecode = True                       # never write __pycache__ into the bench repo
BENCH = os.path.expanduser("~/agent-guard-bench")
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
    """-> {"holdout19": rows}: the blind set, the 8 files of ~/agent-guard-bench/cases/holdout19/*_cases.jsonl in sorted
    order, labels read the way bench.py reads them (expect stop, block or ask = bad; allow = safe; bench.py's
    EXPECT_WORDS map applied first). The 2026-10-14 run (~/agent-guard-bench-holdout-18/baselines_2026-10-14/) scored
    holdout17, holdout18 and the incidents with these same scripts; this copy changes only this function."""
    b = load("bench_labels", BENCH + "/bench.py")
    rows = []
    for p in sorted(glob.glob(BENCH + "/cases/holdout19/*_cases.jsonl")):
        for r in b.load_cases(p):
            rows.append(dict(r, label="bad" if r["expect"] in ("stop", "block", "ask") else "safe",
                             src=os.path.basename(p)))
    return {"holdout19": rows}
