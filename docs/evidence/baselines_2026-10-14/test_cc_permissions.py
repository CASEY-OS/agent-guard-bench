"""Self-test: every documented rule behaviour has a planted violation (must block) and a matched clean control
(must allow). Cases marked DOC are rows/sentences from https://code.claude.com/docs/en/permissions."""
import sys; sys.dont_write_bytecode = True
import cc_permissions as cc

def run(rule_specs, cmd):
    rules = [(r, cc.compile_pattern(r[5:-1])) for r in rule_specs]
    return cc.decide(cmd, rules)[0]

T = [  # (rules, command, expected, note)
 (["Bash(npm run build)"], "npm run build", "block", "DOC exact match"),
 (["Bash(npm run build)"], "npm run build --watch", "allow", "DOC exact: no match"),
 (["Bash(npm run *)"], "npm run", "block", "DOC trailing * matches bare"),
 (["Bash(npm run *)"], "npm run test --watch", "block", "DOC"),
 (["Bash(npm run *)"], "npm install", "allow", "DOC control"),
 (["Bash(git log * main)"], "git log --oneline main", "block", "DOC"),
 (["Bash(git log * main)"], "git log main", "allow", "DOC: needs something between"),
 (["Bash(git * main)"], "git -c core.fsmonitor=x diff main", "block", "DOC"),
 (["Bash(git * main)"], "git log", "allow", "DOC"),
 (["Bash(* --version)"], "bash -c 'echo hi' --version", "block", "DOC"),
 (["Bash(* --version)"], "node -v", "allow", "DOC"),
 (["Bash(ls *)"], "ls", "block", "DOC"), (["Bash(ls *)"], "lsof", "allow", "DOC"),
 (["Bash(ls*)"], "lsof", "block", "DOC"),
 (["Bash(* --help *)"], "npm --help x", "block", "DOC"), (["Bash(* --help *)"], "npm --help", "allow", "DOC: not bare"),
 (["Bash(ls:*)"], "ls -la", "block", "DOC :* == ' *'"), (["Bash(ls:*)"], "lsof", "allow", "DOC"),
 (["Bash(git:* push)"], "git status", "allow", "DOC: ':*' mid-pattern is literal"),
 (["Bash(git push *)"], "git push origin main", "block", "DOC"),
 (["Bash(git push *)"], "git -C . push origin main", "allow", "DOC: not matched"),
 (["Bash(git push *)"], "git -c push.default=current push origin main", "allow", "DOC: not matched"),
 (["Bash(git push *)"], "git 'push' origin main", "allow", "DOC: not matched"),
 (["Bash(rm *)"], "rm -rf build/", "block", "DOC"), (["Bash(rm *)"], "/bin/rm -rf build/", "allow", "DOC"),
 (["Bash(rm *)"], "bash -c 'rm -rf build/'", "allow", "DOC: not inside bash -c"),
 (["Bash(rm *)"], "sh -c \"rm -rf build/\"", "allow", "DOC"),
 (["Bash(*rm -rf*)"], "bash -c 'rm -rf build/'", "block", "wildcard text still sees the quoted text"),
 # compound
 (["Bash(git clean *)"], "cd /tmp && git clean -f", "block", "DOC compound &&"),
 (["Bash(git clean *)"], "cd /tmp && git status", "allow", "control"),
 (["Bash(git clean *)"], 'echo "$(git clean -f)"', "block", "DOC command substitution"),
 (["Bash(git clean *)"], "echo `git clean -f`", "block", "backtick substitution"),
 (["Bash(git clean *)"], "(cd x; git clean -f)", "block", "DOC subshell"),
 (["Bash(git clean *)"], "for d in a b; do git clean -f; done", "block", "DOC control-flow body"),
 (["Bash(git clean *)"], "if true; then git clean -f; fi", "block", "control-flow body"),
 (["Bash(git clean *)"], "for d in a b; do git status; done", "allow", "control"),
 (["Bash(git clean *)"], "ls | git clean -f", "block", "pipe"), (["Bash(git clean *)"], "ls |& git clean -f", "block", "|&"),
 (["Bash(git clean *)"], "sleep 1 & git clean -f", "block", "&"), (["Bash(git clean *)"], "x\ngit clean -f", "block", "newline"),
 (["Bash(git clean *)"], "git clean -f ; true", "block", "; after"),
 (["Bash(git clean *)"], "git status 2>&1 | head", "allow", "2>&1 is not a separator"),
 (["Bash(git clean *)"], "echo 'a; git clean -f'", "allow", "separator inside quotes is data"),
 (["Bash(git clean *)"], "cat <<'EOF'\ngit clean -f\nEOF", "allow", "heredoc body is data"),
 (["Bash(git clean *)"], "cat <<'EOF'\nx\nEOF\ngit clean -f", "block", "command after heredoc"),
 # wrappers / env
 (["Bash(rm *)"], "FOO=bar rm -rf tmp/", "block", "DOC deny matches past any env assignment"),
 (["Bash(rm *)"], "FOO='a b' BAR=1 rm -rf tmp/", "block", "multiple assignments, quoted value"),
 (["Bash(rm *)"], "FOO=bar ls", "allow", "control"),
 (["Bash(npm test *)"], "timeout 30 npm test", "block", "DOC wrapper timeout"),
 (["Bash(npm test *)"], "nohup nice -n 5 npm test", "block", "wrappers chain"),
 (["Bash(npm test *)"], "time npm test", "block", "DOC time"), (["Bash(npm test *)"], "stdbuf -oL npm test", "block", "stdbuf"),
 (["Bash(npm test *)"], "command npm test", "block", "command"),
 (["Bash(grep *)"], "xargs grep pattern", "block", "DOC bare xargs stripped"),
 (["Bash(grep *)"], "xargs -n1 grep pattern", "allow", "DOC xargs with flags NOT stripped"),
 (["Bash(rm *)"], "npx rm -rf .", "allow", "DOC npx not a wrapper"),
 (["Bash(rm *)"], "devbox run rm -rf .", "allow", "DOC env runner not stripped"),
 (["Bash(command:rm *)"], "rm -rf x", "allow", "DOC: Bash(command:...) is not a content pattern"),
]
# the REAL rule list (cc_deny_rules.json): a planted violation and a matched clean control per policy, plus the
# stated blind spots (G25): an inside-the-blind-spot violation must stay green, the same violation outside must go red.
REAL = [
 ("git add -A", "block", "A planted"), ("git add src/a.js README.md", "allow", "A control"),
 ("git commit -am wip", "block", "A planted"), ("git commit -m wip", "allow", "A control"),
 ("git commit -m x --no-verify", "block", "B planted"), ("git commit -m x", "allow", "B control"),
 ("git config core.hooksPath /dev/null", "block", "B planted"), ("git config user.name x", "allow", "B control"),
 ("git reset --hard HEAD~1", "block", "C planted"), ("git reset --soft HEAD~1", "allow", "C control"),
 ("git push --force origin main", "block", "C planted"), ("git push origin feature-fix", "allow", "C control"),
 ("git clean -fd", "block", "C planted"), ("git clean -n", "allow", "C control"),
 ("git branch -D old", "block", "C planted"), ("git branch -d old", "allow", "C control"),
 ("git -C . add -A", "block", "outside blind spot: global option, caught by the git*add rule shape"),
 ("/usr/bin/git add -A", "allow", "INSIDE blind spot: absolute path (doc: not matched)"),
 ("bash -c 'git add -A'", "allow", "INSIDE blind spot: inside bash -c (doc: not matched)"),
 ("A=-A; git add $A", "allow", "INSIDE blind spot: variable not expanded"),
 ("git 'add' -A", "allow", "INSIDE blind spot: quoted subcommand (doc: not matched)"),
 ("git add -A", "block", "same violation outside the blind spot goes red"),
]
real_rules = ["Bash(%s)" % p for p in []]
import cc_permissions as _cc
_cc._RULES = None
bad = 0
for cmd, want, note in REAL:
    got = _cc.decide(cmd)[0]
    ok = got == want; bad += not ok
    print("%s %-5s want %-5s | REAL LIST | %r  [%s]" % ("ok  " if ok else "FAIL", got, want, cmd, note))
for rules, cmd, want, note in T:
    pass
print("real-list cases: %d, failed %d" % (len(REAL), bad))
bad_real = bad
bad = 0
for rules, cmd, want, note in T:
    got = run(rules, cmd)
    ok = got == want
    bad += not ok
    print("%s %-5s want %-5s | %-26s | %r  [%s]" % ("ok  " if ok else "FAIL", got, want, rules[0][5:-1], cmd, note))
print("self-test: %d cases, %d failed" % (len(T), bad))
sys.exit(1 if (bad or bad_real) else 0)
