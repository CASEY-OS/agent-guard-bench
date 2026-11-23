# RESULTS_v31: guards on blind_v31

Made 2026-11-23 12:30 CST by score_rivals_v31.py. Set: 2,429 rows, sha256 dbac99f83e61e3e872fbf5028706be76a17633351cf95358910c06e8498bfed8 (checked against LOCK.txt before use). Dangerous = label `expect` is stop (1124), safe = allow (1305).
No command was run: each row was handed to each guard as text on stdin, as a PreToolUse hook payload. Each guard ran in a fresh git repo with uncommitted changes, with a throwaway HOME holding files in .ssh, .aws, .claude and Documents; the room was deleted afterwards.

## Result

| guard | dangerous stopped (Wilson 95%) | A staging | B hooks | C data loss | D delete/home | safe wrongly stopped (Wilson 95%) |
|---|---|---:|---:|---:|---:|---|
| ours v30, README convention (undo fallback counted allowed) | 1,107 of 1,124 (98.5%, 97.6 to 99.1) | 347/349 | 313/318 | 219/221 | 228/236 | 36 of 1,305 (2.8%, 2.0 to 3.8) |
| ours v30, hook as run, undo off (fallback deny counted stopped) | 1,107 of 1,124 (98.5%, 97.6 to 99.1) | 347/349 | 313/318 | 219/221 | 228/236 | 96 of 1,305 (7.4%, 6.1 to 8.9) |
| dcg v0.17.1 (default packs) | 417 of 1,124 (37.1%, 34.3 to 40.0) | 25/349 | 24/318 | 147/221 | 221/236 | 300 of 1,305 (23.0%, 20.8 to 25.3) |
| cc-safety-net 2.8.3 standard | 359 of 1,124 (31.9%, 29.3 to 34.7) | 13/349 | 21/318 | 175/221 | 150/236 | 149 of 1,305 (11.4%, 9.8 to 13.3) |
| cc-safety-net 2.8.3 strict | 449 of 1,124 (39.9%, 37.1 to 42.8) | 17/349 | 30/318 | 176/221 | 226/236 | 213 of 1,305 (16.3%, 14.4 to 18.4) |
| cc-safety-net 2.8.3 paranoid | 464 of 1,124 (41.3%, 38.4 to 44.2) | 17/349 | 36/318 | 177/221 | 234/236 | 293 of 1,305 (22.5%, 20.3 to 24.8) |

Ours is shown two ways (see the script header). `README convention` counts a command the guard would only allow on an undo point as allowed, which is how the README's 1,107 and 36 are counted. `hook as run, undo off` counts that fallback deny as a stop, which is what the hook does when no undo point can be taken. Rivals have no such state.

## Ours against its stored record

Ours (hook route) was compared row by row with docs/evidence/blind_v31/scores/res_v30.json (verdict, and rule name on each deny): 2,429 of 2,429 rows agree. Of the record's 103 rows marked allowed-on-an-undo-point, 43 were allowed outright here (the hook was given a real working directory; the record was made with none), the same under the README convention.

## Crashes, timeouts, unparseable output (each counted as allow for a rival)

- ours v30: none
- dcg v0.17.1 (default packs): none
- cc-safety-net 2.8.3 standard: none
- cc-safety-net 2.8.3 strict: none
- cc-safety-net 2.8.3 paranoid: none

## Sensitivity: the 50 rows that name /work/repo

Those commands name the repo root the set was written for. On this machine that path does not exist, so a rival sees an absolute path outside its working directory. Here the same 50 rows are re-scored with /work/repo rewritten to the real fixture repo (ours with its root pinned there too). Headline numbers above are NOT these.

| guard | dangerous stopped | safe wrongly stopped |
|---|---|---|
| ours v30, README convention (undo fallback counted allowed) | 41 of 41 | 0 of 9 |
| ours v30, hook as run, undo off (fallback deny counted stopped) | 41 of 41 | 0 of 9 |
| dcg v0.17.1 (default packs) | 23 of 41 | 7 of 9 |
| cc-safety-net 2.8.3 standard | 18 of 41 | 1 of 9 |
| cc-safety-net 2.8.3 strict | 23 of 41 | 1 of 9 |
| cc-safety-net 2.8.3 paranoid | 24 of 41 | 7 of 9 |

## Provenance

See RIVALS_PROVENANCE.md. This run: {"ccsn_tree_sha256": "80285c1e2abf2e72fbfdc0693da6eb0223a030c791f969586d506c65a06b4ded", "ccsn_version": "2.8.3", "dcg_binary_sha256": "881953634ec7e040bb6574a02b72f5f6b374e431bb06d528121437ed7de6c57d", "guard_sha256": "08bf8c61aa7a6462a2f3aadefdc865ccb0d1f47cbf60aebf012581532721f887", "node": "/opt/homebrew/bin/node", "platform": "macOS-27.2.1-arm64-arm-64bit-Mach-O", "python": "3.14.5", "set_sha256": "dbac99f83e61e3e872fbf5028706be76a17633351cf95358910c06e8498bfed8"}

Blind to: whether the labels are right; the real Claude Code payload (no permission_mode or transcript, so cc-safety-net answers deny where a live session could get ask; both count as a stop); user or project rule files for a rival (none present: out-of-the-box policy); policies A to D are ours, a rival never claimed them; /work/repo paths (see the sensitivity table); rival versions newer than the pinned ones; load (dcg's 1 s deadline raised to 10 s).
