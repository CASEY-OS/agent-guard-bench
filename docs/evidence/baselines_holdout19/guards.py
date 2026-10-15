from common import *
_g = None; _n = None
def guard_py(command):
    global _g
    if _g is None: _g = load("guard_v14", BENCH + "/guard.py")
    d = _g.decide_full(command)            # no cwd: holdout cases carry no files, as in bench.py
    if d["verdict"] == "deny": return "stopped", d["origin"]
    if d["origin"] == "recoverable": return "undo", "recoverable"
    return "missed", str(d["origin"])
def naive(command):
    global _n
    if _n is None: _n = load("naive_regex", BENCH + "/variants/naive_regex.py")
    v, why = _n.decide(command)
    return ("stopped" if v in ("block", "deny") else "missed"), why
