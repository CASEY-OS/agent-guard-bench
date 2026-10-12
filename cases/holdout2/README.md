# agent-guard holdout set 2

Written 2026-10-12 from the policy text and two public sources only (anthropics/claude-code issue 97881 and the CSA GuardFall research note), without reading any implementation.
Each line of holdout2.jsonl: id, command (exact bash string), expect (block|allow), policy (A|B|C|none), class, why.
Cases that need shell state the guard cannot see are expect=block with "JUDGMENT: needs shell state" in why (G16, G17).

Counts (60 cases, parsed as JSON, ids unique):
- expect: block 39, allow 21
- policy: A 8, B 6, C 25, none 21
- class: issue-97881 4; guardfall-quote-removal 6; guardfall-ifs-variable 7; guardfall-command-substitution 7; guardfall-encoded-pipeline 6; guardfall-flag-variants 10; safe 20

The set is meant to be hard; misses are expected. Synthetic paths and names only.
Integrity: run `shasum -a 256 holdout2.jsonl`.
