import sys, os, importlib.util, shutil
sys.dont_write_bytecode = True
REPO = sys.argv[1]; sys.argv = [sys.argv[0], REPO, "x"]
spec = importlib.util.spec_from_file_location("jl", os.path.expanduser("~/agent-guard-bench-holdout-18/jail_labels.py"))
jl = importlib.util.module_from_spec(spec); spec.loader.exec_module(jl); ub = jl.ub
try:
    ub.JAIL[:] = ub.jail()
    for name, cmd, on in (("ctl-on", "git add -A", True), ("ctl-off-RED", "git add -A", False)):
        p = ub.play(name, cmd, None, undo_on=on)
        print(name, "undo_on=%s" % on, "snapshots", p["snapshots_taken"], "damage", p["damage"], "restore_rc", p["restore_rc"], "left", len(p["left"]), p["left"][:2])
finally:
    shutil.rmtree(ub.ROOT, ignore_errors=True)
