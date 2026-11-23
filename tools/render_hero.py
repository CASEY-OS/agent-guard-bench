#!/usr/bin/env python3
"""render_hero.py: makes docs/hero.svg from a real run of the guard, and proves the committed picture is that run.

    python3 tools/render_hero.py              run the guard for real and write docs/hero.svg
    python3 tools/render_hero.py --check      run it again and fail unless docs/hero.svg is byte for byte what it renders
    python3 tools/render_hero.py --self-test  the proofs, then SELF-TEST: N passed, N failed

WHAT IT RUNS. A throwaway git repo is built under a temp folder (deleted at the end): one committed file, one edit not
committed, one file git has never seen. Then the plugin's exact hook command, `python3 guard.py`, is run once per
command with the PreToolUse JSON on its stdin, the way Claude Code runs it: git reset --hard, git add -A,
git commit --no-verify, and then one clean control, git status. NONE OF THOSE COMMANDS IS RUN; the guard only reads them.
`git status --short` is run for real before the first and after the last, so the picture shows the work still there.

WHAT IS IN THE PICTURE. Every character of a command, of a decision and of a reason is the guard's own output, decoded
from its JSON. Fixed chrome (the window bar, the words "agent runs", "guard says", the colours) is the only text not
from the run. The one liberty is layout: a reason is broken into lines at spaces, and a line break is put before
"DO THIS INSTEAD:". Joined back with single spaces, the lines of a reason are the reason (asserted in --self-test).
Nothing in it depends on the machine: no path, no timestamp, no version.

Blind to: how the picture looks in a viewer whose monospace font is wider than 0.6 em (a line could run past the right
edge; the canvas has margin for Menlo, Consolas, DejaVu Sans Mono and Courier); a guard answer this machine does not
give (the proof is Python 3.14 on macOS; --check is the check on any other); the other commands the guard denies (it
shows three and a control, not the headline rate); and whether the picture reads well, which only a person looking at it can say.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
GUARD = os.path.join(REPO, "guard.py")
OUT = os.path.join(REPO, "docs", "hero.svg")

COMMANDS = ["git reset --hard", "git add -A", "git commit --no-verify -m x"]
CONTROL = "git status"
MARK = "DO THIS INSTEAD:"
COLS = 96
FS = 13
LH = 19
CW = 0.62 * FS                    # the widest monospace advance the canvas allows for
PAD = 26
BAR = 38


def run_hook(guard, command, repo, env):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": repo})
    p = subprocess.run([sys.executable, guard], input=payload, capture_output=True, text=True, env=env, cwd=repo,
                       timeout=120)
    return p.returncode, p.stdout


def capture(guard=GUARD):
    """-> dict: status_before, status_after, runs: [(command, exit, decision, reason)], control: (command, exit, stdout)."""
    work = tempfile.mkdtemp(prefix="hero_")
    try:
        repo = os.path.join(work, "repo")
        os.mkdir(repo)
        env = dict(os.environ)
        for k in [k for k in env if k.startswith("AGENT_GUARD_")] + ["CLAUDE_PROJECT_DIR"]:
            env.pop(k, None)
        env["AGENT_GUARD_STORE"] = os.path.join(work, "store")
        env["AGENT_GUARD_ROOT"] = repo
        git = ["git", "-c", "user.email=demo@example.com", "-c", "user.name=demo", "-C", repo]
        subprocess.run(git + ["init", "-q"], check=True, env=env, capture_output=True)
        with open(os.path.join(repo, "app.py"), "w") as fh:
            fh.write("print('hello')\n")
        subprocess.run(git + ["add", "app.py"], check=True, env=env, capture_output=True)
        subprocess.run(git + ["commit", "-q", "-m", "first"], check=True, env=env, capture_output=True)
        with open(os.path.join(repo, "app.py"), "a") as fh:
            fh.write("print('unsaved work')\n")
        with open(os.path.join(repo, "notes.txt"), "w") as fh:
            fh.write("a file git has never seen\n")

        def status():
            return subprocess.run(git + ["status", "--short"], check=True, env=env, capture_output=True,
                                  text=True).stdout.rstrip("\n").split("\n")

        out = {"status_before": status(), "runs": []}
        for c in COMMANDS:
            code, stdout = run_hook(guard, c, repo, env)
            try:
                hook = json.loads(stdout)["hookSpecificOutput"]
                decision, reason = hook["permissionDecision"], hook["permissionDecisionReason"]
            except Exception:
                decision, reason = "NOT A DECISION", stdout.strip()
            out["runs"].append((c, code, decision, reason))
        code, stdout = run_hook(guard, CONTROL, repo, env)
        out["control"] = (CONTROL, code, stdout)
        out["status_after"] = status()
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def layout(cap):
    """-> a list of lines; a line is a list of (text, style). Styles: dim, text, cmd, deny, key, ok."""
    lines = []

    def add(*segs):
        lines.append(list(segs))

    add(("a throwaway repo with work that is not committed:", "dim"))
    for s in cap["status_before"]:
        add(("  " + s, "text"))
    for c, code, decision, reason in cap["runs"]:
        lines.append([])
        add(("agent runs  ", "dim"), ("$ " + c, "cmd"))
        add(("guard says  ", "dim"), ("permissionDecision: " + decision, "deny" if decision == "deny" else "key"))
        head, mark, tail = reason.partition(MARK)
        for w in textwrap.wrap(head.strip(), COLS, break_long_words=False, break_on_hyphens=False):
            add(("  " + w, "text"))
        if mark:
            wrapped = textwrap.wrap(MARK + " " + tail.strip(), COLS - 2, break_long_words=False,
                                    break_on_hyphens=False)
            first = True
            for w in wrapped:
                if first:
                    add(("  ", "text"), (MARK, "key"), (w[len(MARK):], "text"))
                    first = False
                else:
                    add(("  " + w, "text"))
    lines.append([])
    c, code, stdout = cap["control"]
    add(("agent runs  ", "dim"), ("$ " + c, "cmd"))
    if code == 0 and stdout == "":
        add(("guard says  ", "dim"), ("(nothing printed, exit 0: the command runs)", "ok"))
    else:
        add(("guard says  ", "dim"), ("exit %d, printed %s" % (code, json.dumps(stdout)), "deny"))
    lines.append([])
    add(("after all of that, the same work is still there:", "dim"))
    for s in cap["status_after"]:
        add(("  " + s, "text"))
    return lines


STYLE = {"dim": "#8b949e", "text": "#c9d1d9", "cmd": "#ffffff", "deny": "#ff7b72", "key": "#7ee787", "ok": "#7ee787"}


def render(cap):
    lines = layout(cap)
    widest = max(sum(len(t) for t, _ in ln) for ln in lines if ln)
    width = int(PAD * 2 + widest * CW) + 8
    height = BAR + PAD + len(lines) * LH + PAD
    o = []
    o.append('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" '
             'aria-labelledby="t d">' % (width, height, width, height))
    o.append('<title id="t">agent-guard denying git reset --hard, git add -A and git commit --no-verify</title>')
    o.append('<desc id="d">A terminal. Over a repo with uncommitted work, the guard denies three commands, each with a '
             'DO THIS INSTEAD, allows git status, and the uncommitted work is still there.</desc>')
    o.append('<rect width="%d" height="%d" rx="10" fill="#0d1117"/>' % (width, height))
    o.append('<rect width="%d" height="%d" rx="10" fill="#161b22"/>' % (width, BAR))
    o.append('<rect y="%d" width="%d" height="%d" fill="#161b22"/>' % (BAR - 10, width, 10))
    for i, col in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        o.append('<circle cx="%d" cy="%d" r="6" fill="%s"/>' % (22 + i * 20, BAR // 2, col))
    o.append('<text x="%d" y="%d" fill="#8b949e" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, '
             '\'DejaVu Sans Mono\', \'Liberation Mono\', monospace" font-size="12" text-anchor="middle">'
             'agent-guard</text>' % (width // 2, BAR // 2 + 4))
    o.append('<g font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, \'DejaVu Sans Mono\', '
             '\'Liberation Mono\', monospace" font-size="%d">' % FS)
    y = BAR + PAD
    for ln in lines:
        if ln:
            spans = "".join('<tspan fill="%s"%s>%s</tspan>' % (STYLE[s], ' font-weight="bold"' if s in ("key", "cmd")
                                                                else "", escape(t)) for t, s in ln)
            o.append('<text x="%d" y="%d" xml:space="preserve" style="white-space:pre">%s</text>' % (PAD, y, spans))
        y += LH
    o.append("</g>")
    o.append("</svg>")
    return "\n".join(o) + "\n"


def texts(svg):
    """The text lines of a rendered picture, XML-unescaped, for the --self-test."""
    import re
    import html
    return [html.unescape(re.sub(r"<[^>]+>", "", m)) for m in re.findall(r"<text x=\"\d+\" y=\"\d+\" [^>]*>(.*?)</text>", svg)]


def self_test():
    results = []

    def case(label, ok, detail=""):
        results.append(ok)
        print("%s  %s%s" % ("pass" if ok else "FAIL", label, (": " + detail) if detail else ""))

    cap = capture()
    svg = render(cap)
    case("the three planted commands are denied and carry DO THIS INSTEAD",
         [r[2] for r in cap["runs"]] == ["deny"] * 3 and all(MARK in r[3] for r in cap["runs"]),
         "decisions %r" % [r[2] for r in cap["runs"]])
    case("the clean control prints nothing and exits 0", cap["control"][1] == 0 and cap["control"][2] == "",
         "exit %d, %d bytes" % (cap["control"][1], len(cap["control"][2])))
    case("the uncommitted work is on screen before and after, unchanged",
         cap["status_before"] == cap["status_after"] == [" M app.py", "?? notes.txt"], repr(cap["status_after"]))
    ts = texts(svg)
    # every reason, rebuilt from the picture's own lines, is the guard's reason
    blob = "\n".join(ts)
    ok = True
    for c, code, decision, reason in cap["runs"]:
        flat = " ".join(reason.split())
        picture = " ".join(blob.split())
        ok = ok and flat in picture and ("$ " + c) in blob
    case("every command and every reason is in the picture, character for character (whitespace joined)", ok)
    case("the picture states nothing of this machine (no temp path, no home path, no repo path)",
         tempfile.gettempdir() not in svg and os.path.expanduser("~") not in svg and REPO not in svg)
    case("rendering twice gives the same bytes (nothing in it moves from run to run)", render(capture()) == svg)
    width = int(svg.split('width="', 1)[1].split('"', 1)[0])
    longest = max(len(t) for t in ts)
    case("the longest line fits the canvas at a 0.62 em advance", longest * CW + PAD * 2 <= width,
         "%d columns, canvas %d px" % (longest, width))
    # red: a guard that allows everything makes the capture's own assertions fail
    work = tempfile.mkdtemp(prefix="hero_check_")
    try:
        allow_all = os.path.join(work, "allow_all.py")
        with open(allow_all, "w") as fh:
            fh.write("import sys\nsys.stdin.read()\n")
        bad = capture(allow_all)
        case("planted: a guard that allows everything reads red (no deny, no DO THIS INSTEAD)",
             [r[2] for r in bad["runs"]] != ["deny"] * 3 and not any(MARK in r[3] for r in bad["runs"]),
             "decisions %r" % [r[2] for r in bad["runs"]])
        # red: a reworded redirect makes --check fail
        reworded = os.path.join(work, "reworded.py")
        with open(GUARD, encoding="utf-8") as src:
            body = src.read()
        marker = "Keep the work. Set it aside"
        assert marker in body, "the redirect this proof rewords is gone from guard.py: update the proof"
        with open(reworded, "w", encoding="utf-8") as fh:
            fh.write(body.replace(marker, "Keep your work. Set it aside", 1))
        case("planted: a guard with one reworded redirect renders a different picture (--check would read red)",
             render(capture(reworded)) != svg)
        # control for that: the real guard copied elsewhere renders the same picture
        copydir = os.path.join(work, "copy")
        os.mkdir(copydir)
        for name in ("guard.py", "undo.py"):          # guard.py imports undo.py from its own folder
            shutil.copy(os.path.join(REPO, name), copydir)
        case("control: a byte-for-byte copy of guard.py (with undo.py beside it) renders the same picture",
             render(capture(os.path.join(copydir, "guard.py"))) == svg)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    committed = os.path.exists(OUT) and open(OUT, encoding="utf-8").read() == svg
    case("docs/hero.svg is the picture this run renders, byte for byte", committed,
         "docs/hero.svg %s" % ("matches" if committed else "is missing or differs: run python3 tools/render_hero.py"))
    print("SELF-TEST: %d passed, %d failed" % (results.count(True), results.count(False)))
    return 0 if all(results) else 1


def main(argv):
    if "--self-test" in argv:
        return self_test()
    svg = render(capture())
    if "--check" in argv:
        have = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else None
        print("docs/hero.svg %s what the guard prints now" % ("is" if have == svg else "is NOT"))
        return 0 if have == svg else 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print("wrote %s (%d bytes)" % (os.path.relpath(OUT, REPO), len(svg.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
