# agent-guard-bench holdout 3

Written 2026-10-12 from the policy text and one public source only (CSA research note on GuardFall, AI coding agent shell injection). No implementation or earlier test set was read.

File: holdout3.jsonl, 69 cases, one JSON object per line: id, command, expect, policy, class, why. The guard reads each command string and never runs it. All paths and names are synthetic.

Counts by expect: block 44, allow 25.
Counts by policy: A 23, B 14, C 23, none 9.
Counts by class: guardfall-quote-removal 9, guardfall-ifs-variable 8, guardfall-command-substitution 9, guardfall-encoded-pipeline 9, guardfall-flag-variants 9, safe 25 (over-refusal traps that must be allowed).

Policies: A stage by name only; B never disarm the hooks; C never destroy uncommitted or pushed work.
Two cases are marked JUDGMENT in the why field (K17, K26). They need shell state the guard cannot know. Expect is block, but a reasonable guard may differ.
Encoded payloads were decode-checked (decode stage only, payload never run).
