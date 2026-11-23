# Rival run on blind_v31 (2026-11-23)

The same 2,429 commands as the parent folder, scored against dcg v0.17.1 and cc-safety-net 2.8.3 (standard, strict, paranoid) as well as this guard (v30). The README's section "Against two free rivals, same blind set" states the result and its limits.

| file | what it is |
|---|---|
| `RESULTS_v31.md` | the scorer's own table, and a sensitivity table for the 50 commands that name `/work/repo` |
| `rival_scores_v31.json` | every guard's verdict on every row, and the tallies the README table is checked against |
| `RIVALS_PROVENANCE.md` | where each rival was fetched, its hashes, and what was and was not verified |
| `score_rivals_v31.py` | the scorer. It never runs a command from the set: each row goes to a guard as text on stdin, as a hook payload |

Two things differ from the files as the run wrote them:

- In `rival_scores_v31.json` the machine's home path was replaced with `/Users/USER/` in the text of the guards' deny messages. Nothing else was changed; the counts, labels and verdict kinds are as written. The path is the only difference, so the file's checksum is not the run's.
- `RIVALS_PROVENANCE.md` mentions `ANSWERS A102` and `~/agent-guard-bench-dev6`: notes from a 2026-10-12 run that are not in this repo. They explain why that older run is not comparable and are kept as written.

## Re-running

- From a clone, with no rival started: `python3 docs/evidence/blind_v31/rivals/score_rivals_v31.py --ours-only --no-write --bench .` re-scores this guard against its stored record and prints `OVERALL: PASS` when all 2,429 rows agree. The scorer's `--self-test` starts no rival either (36 checks).
- To run the rivals you fetch them yourself. dcg goes at `WORK/dcg/dcg` and cc-safety-net at `WORK/ccsn/node_modules/cc-safety-net`, fetched as `RIVALS_PROVENANCE.md` says. Then `python3 docs/evidence/blind_v31/rivals/score_rivals_v31.py --approved --bench . --work WORK`. It refuses to start unless every file hash equals the pinned one, and it executes third-party code as hooks, so read what you fetched first. A newer rival release is refused by those pins; to score one, change `RIVAL_PINS` in the script and say so.
- The script's default `--bench` is `~/agent-guard-bench` and its default `--work` is its own folder. Those are the paths on the machine that made the run; pass `--bench` and `--work` from a clone.
- `python3 tools/rivals_check.py` checks the README's rival numbers against these files; `python3 tools/rivals_check.py --self-test` proves it can fail.

Proven on one machine (macOS, Python 3.14.5, Node from Homebrew). A different Python or operating system is untested.
