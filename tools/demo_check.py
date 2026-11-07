#!/usr/bin/env python3
"""demo_check.py: proves demo.py prints exactly tools/demo_expected.txt, that docs/install.md and llms.txt show the hook
the plugin really carries, and that each check can go red.

    python3 tools/demo_check.py --self-test     the proofs below, then SELF-TEST: N passed, N failed
    python3 tools/demo_check.py                 only the first proof: demo.py's real output against the expected file

tools/demo_expected.txt was written BEFORE demo.py existed, from the guard's own output on the six commands. The demo
must print it byte for byte and exit 0.

Every planted violation is built at run time in a temp folder and deleted; nothing is stored at rest. The roots this
check measures are pinned: the demo is run with the repo's own demo.py and guard.py (asserted by path) from a different
working directory, with HOME pointed at an empty temp folder.

Blind to: any command the six in the demo do not name (the demo never asks the guard about a seventh); a guard that
answers the six correctly and gets everything else wrong; the guard's behaviour on a machine other than the one this
ran on (only Python 3.14 on macOS proven here, the CI matrix runs 3.9 and 3.12); and Windows. It pins the guard's
wording of each reason and redirect: a reworded redirect in guard.py reads red here until the expected file is updated
on purpose. For the install page it compares the hook JSON and the command strings only; it cannot show that those
commands work against the GitHub marketplace (they were run here only against a local-folder marketplace, in a throwaway
config folder) or that a new session refuses a planted command.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DEMO = os.path.join(REPO, "demo.py")
EXPECTED = os.path.join(HERE, "demo_expected.txt")
GUARD = os.path.join(REPO, "guard.py")
NO_GUARD = os.path.join(REPO, "variants", "no_guard.py")
README = os.path.join(REPO, "README.md")
HOOKS = os.path.join(REPO, "hooks", "hooks.json")
INSTALL = os.path.join(REPO, "docs", "install.md")
LLMS = os.path.join(REPO, "llms.txt")
MARKET = os.path.join(REPO, ".claude-plugin", "marketplace.json")
PLUGIN = os.path.join(REPO, ".claude-plugin", "plugin.json")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def run_demo(args=(), env_extra=None, home=None, cwd=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    if home:
        env["HOME"] = home
    p = subprocess.run([sys.executable, DEMO] + list(args), capture_output=True, text=True, env=env,
                       cwd=cwd or tempfile.gettempdir(), timeout=300)
    return p.returncode, p.stdout, p.stderr


def main(argv):
    self_test = "--self-test" in argv
    results = []

    def case(label, ok, detail=""):
        results.append(ok)
        print("%s  %s%s" % ("pass" if ok else "FAIL", label, (": " + detail) if detail else ""))

    tmp = tempfile.mkdtemp(prefix="demo_check_")
    try:
        want = read(EXPECTED)
        home = os.path.join(tmp, "home")
        os.mkdir(home)
        elsewhere = os.path.join(tmp, "elsewhere")
        os.mkdir(elsewhere)
        assert os.path.dirname(DEMO) == REPO and os.path.exists(GUARD), "measuring the wrong tree"

        code, out, err = run_demo(home=home, cwd=elsewhere)
        case("the real demo prints the expected file byte for byte and exits 0",
             code == 0 and out == want, "exit %d, %d bytes of %d wanted" % (code, len(out), len(want)))
        if not self_test:
            print("SELF-TEST: %d passed, %d failed" % (results.count(True), results.count(False)))
            return 0 if all(results) else 1

        def tree_of(root):
            return sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs + [""])

        # the interpreter itself may write under HOME (Apple's python3 makes ~/Library/Caches): measure that first, and
        # blame the demo only for what it adds beyond it
        base_home = os.path.join(tmp, "base_home")
        os.mkdir(base_home)
        env0 = dict(os.environ, HOME=base_home)
        subprocess.run([sys.executable, "-c", "pass"], env=env0, cwd=elsewhere, timeout=60)
        # a second HOME for a run with the interpreter's bytecode cache off: Apple's python3 3.9 writes .pyc files for every
        # module it imports under ~/Library/Caches, which is the interpreter and not the demo
        nobyte_home = os.path.join(tmp, "nobyte_home")
        os.mkdir(nobyte_home)
        code0, out0, _ = run_demo(env_extra={"PYTHONDONTWRITEBYTECODE": "1"}, home=nobyte_home, cwd=elsewhere)
        added = sorted(set(tree_of(nobyte_home)) - set(tree_of(base_home)))
        case("it writes nothing under HOME beyond what a bare python3 does (the undo store is pinned to a temp folder)",
             code0 == 0 and out0 == want and added == [], "the demo added %r" % added)
        # the matched violation: a demo-like run that does write the undo store under HOME must read red
        os.makedirs(os.path.join(nobyte_home, ".local", "state", "agent-guard"))
        added2 = sorted(set(tree_of(nobyte_home)) - set(tree_of(base_home)))
        case("planted: a file under HOME/.local/state/agent-guard reads as written by the demo", added2 != [],
             "%r" % added2)
        shutil.rmtree(os.path.join(nobyte_home, ".local"))

        code, out2, _ = run_demo(env_extra={"AGENT_GUARD_JUDGE": "haiku", "CLAUDE_PROJECT_DIR": "/nonexistent",
                                            "AGENT_GUARD_ROOT": "/nonexistent", "AGENT_GUARD_UNDO": "0"},
                                 home=home, cwd=elsewhere)
        case("same output with a judge, a project dir, a guard root and the undo switch set in the caller's environment",
             code == 0 and out2 == want)

        # red: the guard that allows everything. The five planted commands must read as a failure.
        code, out3, _ = run_demo(["--guard", NO_GUARD], home=home, cwd=elsewhere)
        case("planted: a guard that allows everything makes the demo FAIL (exit 1, all five reported)",
             code == 1 and "DEMO FAILED" in out3 and out3.count("ALLOWED  ") == 6,
             "exit %d, DEMO FAILED %s, %d ALLOWED lines" % (code, "DEMO FAILED" in out3, out3.count("ALLOWED  ")))

        # red: the guard that blocks everything. The clean control must read as a failure.
        deny_all = os.path.join(tmp, "deny_all.py")
        with open(deny_all, "w") as fh:
            fh.write("import json,sys\n"
                     "json.load(sys.stdin)\n"
                     "print(json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny',"
                     "'permissionDecisionReason':'deny_all: no. DO THIS INSTEAD: nothing.'}}))\n")
        code, out4, _ = run_demo(["--guard", deny_all], home=home, cwd=elsewhere)
        case("planted: a guard that blocks everything makes the demo FAIL on the clean control",
             code == 1 and "DEMO FAILED" in out4 and "BLOCKED  git status" in out4,
             "exit %d" % code)

        # red: a guard that is silent and then crashes
        crash = os.path.join(tmp, "crash.py")
        with open(crash, "w") as fh:
            fh.write("import sys\nsys.exit(3)\n")
        code, out5, _ = run_demo(["--guard", crash], home=home, cwd=elsewhere)
        case("planted: a guard that crashes makes the demo FAIL, never print ALLOWED as if it had looked",
             code == 1 and "DEMO FAILED" in out5, "exit %d" % code)

        # red: the expected file with one character changed
        bad_expected = os.path.join(tmp, "expected.txt")
        with open(bad_expected, "w", encoding="utf-8") as fh:
            fh.write(want.replace("BLOCKED  git reset --hard", "BLOCKED  git reset --soft", 1))
        code, out6, _ = run_demo(["--expected", bad_expected], home=home, cwd=elsewhere)
        case("planted: an expected file with one command changed makes the demo FAIL",
             code == 1 and "DEMO FAILED" in out6 and "differs from the expected output" in out6, "exit %d" % code)
        # the matched clean control for that: the real expected file through the same flag
        code, out7, _ = run_demo(["--expected", EXPECTED], home=home, cwd=elsewhere)
        case("control: the real expected file through the same flag passes", code == 0 and out7 == want)

        # the demo runs nothing: the uncommitted work it prints about is read back by the demo from disk
        case("the output says the work is still on disk, and says nothing of a path on this machine",
             "The uncommitted work is still on disk." in out and tempfile.gettempdir() not in out and REPO not in out)

        # the README's sentence and the demo's sentence are the same numbers
        m = re.search(r"^(\d+) of (\d+) planted commands BLOCKED\. (\d+) of (\d+) clean command ALLOWED\.$", out, re.M)
        readme = read(README)
        r = re.search(r"(\d+) of (\d+) planted commands BLOCKED and (\d+) of (\d+) clean command ALLOWED", readme)
        case("README quotes the demo's tally (%s)" % (m.group(0) if m else "demo tally not found"),
             bool(m) and bool(r) and m.groups() == r.groups(),
             "README %s" % (str(r.groups()) if r else "line not found"))
        case("README names the demo command and the try-without-installing line",
             "python3 demo.py" in readme and "Try it without installing" in readme)

        # the install page and llms.txt: the hook they show is the hook the plugin carries
        hooks = json.loads(read(HOOKS))
        page = read(INSTALL)
        blocks = re.findall(r"```json\n(.*?)\n```", page, re.S)
        shown = json.loads(blocks[0]) if blocks else None
        case("docs/install.md shows hooks/hooks.json word for word (parsed JSON equal)", shown == hooks)
        planted = page.replace('"timeout": 30', '"timeout": 3', 1)
        pb = re.findall(r"```json\n(.*?)\n```", planted, re.S)
        case("planted: an install page whose timeout differs from hooks.json reads red",
             planted != page and json.loads(pb[0]) != hooks)
        case("the install page and llms.txt carry the step that shows the user the hook before any setting changes",
             "before anything is installed" in page and "word for word" in page
             and "Do not edit any setting before they say yes" in read(LLMS))
        cmds = ("claude plugin marketplace add CASEY-OS/agent-guard-bench",
                "claude plugin install agent-guard@agent-guard-bench",
                "claude plugin uninstall agent-guard@agent-guard-bench",
                "claude plugin marketplace remove agent-guard-bench")
        readme = read(README)
        case("the install, uninstall and marketplace commands are the same in README, llms.txt and install.md",
             all(c in page and c in read(LLMS) for c in cmds) and all(c in readme for c in cmds[:2]))
        market = json.loads(read(MARKET))
        plugin = json.loads(read(PLUGIN))
        ident = "%s@%s" % (market["plugins"][0]["name"], market["name"])
        case("the plugin id in those commands is the one the manifests declare (%s)" % ident,
             ident == "agent-guard@agent-guard-bench" and plugin["name"] == "agent-guard")

        # the SURFACE_MAP claims for the numbers this page set added: each goes red when its surface drifts
        tree = os.path.join(tmp, "tree")
        for rel in ("tools/check_surfaces.py", "tools/SURFACE_MAP.json", "results/NUMBERS.json", "README.md", "llms.txt",
                    "docs/install.md", "results/SUMMARY.md", "docs/METHOD.md", "CHANGELOG.md"):
            os.makedirs(os.path.dirname(os.path.join(tree, rel)), exist_ok=True)
            shutil.copy(os.path.join(REPO, rel), os.path.join(tree, rel))

        def surfaces():
            p = subprocess.run([sys.executable, os.path.join(tree, "tools", "check_surfaces.py"),
                                os.path.join(tree, "results", "NUMBERS.json"),
                                os.path.join(tree, "tools", "SURFACE_MAP.json"), "--max-age-hours", "1000000"],
                               capture_output=True, text=True, cwd=tmp, timeout=300)
            return p.returncode, p.stdout

        code, text = surfaces()
        root_line = [l for l in text.splitlines() if l.startswith("Measured root:")]
        case("control: the copied tree reads PASS, and the root measured is the temp copy, not the live repo",
             code == 0 and "VERDICT: PASS" in text and root_line and os.path.realpath(tree) in root_line[0]
             and REPO not in root_line[0], root_line[0] if root_line else "no root line")
        for rel, old, new, label in (
                ("README.md", "agent-guard blocks 98.3% of", "agent-guard blocks 99.3% of", "the pain line's percent"),
                ("README.md", "5 of 5 planted commands BLOCKED and", "4 of 5 planted commands BLOCKED and",
                 "the demo tally in the README"),
                ("llms.txt", "dangerous commands (98.3%)", "dangerous commands (97.3%)", "llms.txt's percent"),
                ("llms.txt", "denied 1,688 of 1,717", "denied 1,689 of 1,717", "llms.txt's count"),
                ("docs/install.md", "wrongly denied 2.0% of 1,583", "wrongly denied 2.1% of 1,583",
                 "install.md's false-block percent")):
            path = os.path.join(tree, rel)
            before = read(path)
            assert old in before, "the phrase this proof drifts is gone from %s: %s" % (rel, old)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(before.replace(old, new, 1))
            code, text = surfaces()
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(before)
            case("planted: %s drifts, check_surfaces reads FAIL" % label,
                 code == 1 and "VERDICT: FAIL" in text and "MISMATCH %s" % rel in text, "exit %d" % code)
        code, text = surfaces()
        case("control: every surface restored reads PASS again", code == 0 and "VERDICT: PASS" in text)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("SELF-TEST: %d passed, %d failed" % (results.count(True), results.count(False)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
