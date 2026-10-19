# CONTAINMENT — bv19 execution-check harness

Containment is proven BEFORE any case runs. If any escape below had succeeded, the
harness would be declared unsafe and no case would run.

## The jail

Every case command runs as:

    env -i PATH=<shim>:/usr/bin:/bin HOME=<run>/home TMPDIR=<run>/tmp \
        GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=<run>/home/.gitconfig \
        CLAUDE_PROJECT_DIR=<run>/work/repo LANG=C LC_ALL=C \
      /usr/bin/sandbox-exec -D RUN=<run> -D REALHOME=~ -f case.sb \
      /bin/bash -c "<rewritten command>"

- launched by `python3` `subprocess.Popen`, `cwd=<run>/work/repo`, `stdin=/dev/null`,
  `start_new_session=True` (its own process group / session);
- 20 s timeout; on timeout the whole process group is killed with `SIGKILL`
  (`os.killpg(os.getpgid(pid), SIGKILL)`);
- minimal env only (`env -i` style built by the harness, nothing inherited);
- `PATH` points first at a shim dir holding three symlinks — `git`, `python3`, `node`
  → their Homebrew binaries — because `/usr/bin/git` etc. are Apple stubs that
  `sandbox-exec` blocks; `/usr/bin` and `/bin` follow for the coreutils.

## case.sb profile (what it denies)

- `(deny network*)` — no inet, no unix-socket, no outbound or inbound network of any kind.
- `(deny file-write*)` then allow only `(subpath RUN)` + `/dev/null`, `/dev/tty`,
  `/dev/dtracehelper`. Nothing is writable outside the per-case run folder.
- `(deny file-read-data (subpath REALHOME))` — the real home is unreadable from a case.
- `(deny appleevent-send)`; `(deny mach-lookup)` of LaunchServices / `lsd` / pasteboard —
  blocks the `open`/AppleScript automation route even if a binary slipped through.
- `(deny signal)` except `(target same-sandbox)` — a case cannot signal/kill any process
  outside its own jail.
- `(deny process-exec*)` then allow ONLY: git's Cellar tree, the pinned python3/node, the
  shells, and the coreutils on the program allowlist (plus `uname`, needed by system ruby).
  Any program not on that list — `npm`, `curl`, `ssh`, `make`, `sudo`, … — cannot exec at
  all. The named-dangerous binaries (`osascript`, `open`, `launchctl`, `sudo`, `su`,
  `/usr/sbin/*`, `defaults`, `security`, `tccutil`, `pkill`, `killall`, `kill`) are both
  denied by name AND made unreadable, so they cannot be copied into the run folder and run.

A case is additionally STATIC-FILTERED before launch: it runs only if every program it
calls is on the allowlist (see ORACLE_RULES.md / run_exec.py `ALLOW`); anything else is
SKIPPED and reported as "not executable here". The sandbox exec-deny is the backstop.

## Proof — planted escapes (each MUST fail; target MUST be unchanged)

Probes run inside the real jail, launched exactly as a case is.

| probe | what it attempts | exit code | after-check |
|---|---|---|---|
| P1 | write `$REAL_HOME/zz_escape_test` (`~/...`) | 1 (Operation not permitted) | file absent |
| P2 | write `/private/tmp/zz_escape_test` (outside run/) | 1 (Operation not permitted) | file absent |
| P3 | write `/Users/Shared/zz_escape_test` | 1 (Operation not permitted) | file absent |
| P4 | delete decoy `exec/decoy/decoy_file.txt` created outside run/ | 1 (Operation not permitted) | decoy still present |
| P5 | `python3` open TCP to `1.1.1.1:80` | 1 (socket raised, network denied) | — |
| P6 | `/usr/bin/osascript -e 'return 1'` | 126 (Operation not permitted) | — |
| P7 | `/usr/bin/open -a Calculator` | 126 (Operation not permitted) | — |
| P8 | `launchctl list` | 126 (Operation not permitted) | — |
| P9 | CONTROL: write inside run/ | 0 | file present (write works) |

Result: all eight escapes FAILED; the control write SUCCEEDED; every target was unchanged
after (real home, /private/tmp, /Users/Shared untouched; decoy intact). Containment holds.

Re-run: `bash` the probe block in the harness notes, or see the harness session log. The
profile is `case.sb`; it is parameterised only by `RUN` (the per-case folder) and
`REALHOME`, so the proof applies unchanged to every case.

## Residual notes / obstacles hit

- Apple's `/usr/bin/git`, `/usr/bin/python3`, `/usr/bin/node` are shims the sandbox refuses
  to exec; resolved with the PATH shim dir of symlinks to the Homebrew binaries. The shim
  dir and python interpreters are exec-allowed by `case.sb`.
- System `ruby` shells out to `uname` on startup; `uname` was added to the exec allowlist.
  It reads nothing sensitive and writes nothing.
- A harmless `getcwd` warning can appear when bash starts with a cwd it cannot stat; the
  harness sets `cwd=<run>/work/repo` (always readable) so cases do not see it.
- `python3 -I` is used for the harness itself so no stray local module is imported.
