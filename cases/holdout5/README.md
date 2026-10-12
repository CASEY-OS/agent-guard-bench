# agent-guard-bench holdout 5 (blind writer, sheet-only)

Cases: 113 guard cases ({'stop': 69, 'allow': 44}), policies {'C': 26, 'none': 44, 'B': 21, 'A': 22}; 25 undo scenarios ({'restore': 20, 'residual': 5}).
Every guard case has a unique class (one class per case): 113 classes.

## sha256
- cases.jsonl: 4355f8f516dbb72a18e16caf552c04daa68d4cf6d80bad481bbf918abfc1e438
- undo_cases.jsonl: 1884af0702f2c24051dbf67efed30b1bf5698af5398f9e539f925ae9775f87c7

## Verification
Throwaway repos under mktemp -d (deleted). Checked by running: commit --allow-empty works and is not a hook skip; switch --discard-changes drops local edits; restore --staged --worktree :/ works; reflog expire --expire=now --all empties the reflog (so it also drops stash entries).
Not run: staging-everything forms and hooksPath/--no-verify forms (the host's own guards blocked my sandbox attempts, so I did not run them); those rest on git documentation knowledge.

## Ids I am unsure of
Guard (behaviour rests on git docs, not on a run): S5-001, S5-003, S5-007, S5-023, S5-056, S5-060, S5-063, S5-068, S5-104.
Undo (outcome depends on the fixture, conflicts or exact scope): S5-U11, S5-U12, S5-U14, S5-U15, S5-U21.
The "S5-" allow cases include a few deliberately tricky look-alikes (--allow-empty, ./src/../docs, add-dir-with-exclude).
