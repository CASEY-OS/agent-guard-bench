# agent-guard holdout set

Independent holdout test set for the agent-guard benchmark: Bash commands a PreToolUse guard must BLOCK or ALLOW.

- Author: a Claude Code subagent (Sonnet 5.5), working under my direction.
- Written from the policy text alone (Policy A "stage by name only", Policy B "never disarm the hooks").
  No implementation, no existing benchmark, and no other code of mine was read.
- Date: 2026-10-12
- Cases: 48 in holdout.jsonl (ids H01 to H48), one JSON object per line.
- Split: 24 block, 24 allow.
- Cases whose `why` starts with "JUDGMENT:" are places where the policy text is silent or ambiguous; the call is the author's.
- All paths and names are synthetic.
- Integrity: run `shasum -a 256 holdout.jsonl` and compare with the hash recorded by whoever received the file.
