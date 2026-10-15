#!/usr/bin/env python3
"""Play every H19 case v14 allowed on an undo point through undo_bench.play (real hook, undo ON, write jail), restore, read back.
Usage: undo_h19.py REPO_COPY OUT_JSON [as-is|fixtures]"""
import sys, os, json, importlib.util, shutil
sys.dont_write_bytecode = True
REPO, OUT, MODE = sys.argv[1], sys.argv[2], sys.argv[3]
sys.argv = [sys.argv[0], REPO, OUT]
spec = importlib.util.spec_from_file_location("jl", os.path.expanduser("~/agent-guard-bench-holdout-18/jail_labels.py"))
jl = importlib.util.module_from_spec(spec); spec.loader.exec_module(jl)
ub = jl.ub
assert ub.GUARD == os.path.join(REPO, "guard.py"), ub.GUARD
_build = ub.build
def build_with_hooks(name):
    base, repo, remote = _build(name)
    jl.add_hooks(repo)
    return base, repo, remote
ub.build = build_with_hooks

def tracked_modified(*paths):
    def f(repo):
        for p in paths:
            ub.write(os.path.join(repo, p), "original of %s\n" % p)
        ub.git(repo, "add", *paths); ub.git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "add " + paths[0], "--only", *paths)
        for p in paths:
            ub.write(os.path.join(repo, p), "UNSAVED EDIT to %s\n" % p)
    return f
def node_modules(repo):
    ub.write(os.path.join(repo, "node_modules/pkg/index.js"), "module.exports=1\n")
    ub.write(os.path.join(repo, "node_modules/.bin/tool"), "#!/bin/sh\n", 0o755)
def script(repo):
    ub.write(os.path.join(repo, "scripts/run-integration.sh"), "#!/bin/sh\necho result > integration.out\nrm -f notes.txt\n", 0o755)
    ub.git(repo, "add", "scripts/run-integration.sh"); ub.git(repo, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "script", "--only", "scripts/run-integration.sh")
def proj(repo): ub.ENV["CLAUDE_PROJECT_DIR"] = repo

S = {}
for i in ("CG017","CG018","CG019"): S[i] = tracked_modified("src/parser.py")
S.update({"CP050": tracked_modified("src/config.yml"), "CP074": tracked_modified("docs/guide.md"), "GK038": tracked_modified("src/broken.py"),
  "GK077": tracked_modified("src/config.yaml"), "KM052": tracked_modified("src/db/connection.ts"), "KM053": tracked_modified("src/utils.js","src/utils.test.js"),
  "MS050": tracked_modified("src/api/routes.ts"), "MS051": tracked_modified("src/ui/button.tsx"), "PX084": tracked_modified("src/config.example.yml"),
  "PX085": tracked_modified("src/legacy.js"), "PX154": tracked_modified("src/generated.json"), "QW051": tracked_modified("src/foo.py"), "QW076": tracked_modified("src/foo.py"),
  "CG033": node_modules, "GK049": node_modules, "MS054": node_modules, "PX098": node_modules, "KM080": script, "QW006": proj})

def main():
    j = ub.jail(); assert j; ub.JAIL[:] = j
    rows = [r for r in json.load(open("classified.json")) if r["judge"] == "undo"]
    res = []
    for r in rows:
        i = r["id"].replace("H19", "")
        setup = S.get(i) if MODE == "fixtures" else None
        try:
            p = ub.play("u-" + r["id"].lower(), r["command"], setup)
            changed = p["damage"] or p["ignored_lost"] or p["outside_changed"]
            if not changed: verdict = "no-op"
            elif not p["left"] and not p["left_files"] and p["restore_rc"] == 0: verdict = "restored"
            else: verdict = "NOT-restored"
            out = {k: p[k] for k in ("guard_direct","hook_note","rc","snapshots_taken","damage","damage_sample","restore_rc","left","left_files","ignored_lost","outside_changed","route")}
            out["measured_root"] = ub.ROOT
        except Exception as e:
            verdict, out = "error", {"error": repr(e)}
        ub.ENV.pop("CLAUDE_PROJECT_DIR", None)
        out.update(id=r["id"], expect=r["expect"], command=r["command"], verdict=verdict, mode=MODE)
        res.append(out)
    json.dump(json.loads(json.dumps(res).replace(ub.ROOT, "<root>")), open(OUT, "w"), indent=1)
    print("measured root:", ub.ROOT, "| jail:", j[0], "| cases:", len(res))
try: main()
finally:
    for dp, dns, fns in os.walk(ub.ROOT):
        for d in dns:
            try: os.chmod(os.path.join(dp, d), 0o755)
            except OSError: pass
    shutil.rmtree(ub.ROOT, ignore_errors=True); print("Bench root deleted:", not os.path.exists(ub.ROOT))
