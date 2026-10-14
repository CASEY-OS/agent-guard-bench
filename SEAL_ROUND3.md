# holdout18, round 3 seal (commit before reveal)

Gemini (gemini.google.com, his Workspace account). It errored twice on the round 1 prompt. He then gave it the prompt himself in a fresh chat, finished before 15:13 Central on 2026-10-14 (the start time was not recorded). The prompt he pasted was the Copilot copy of PROMPT_TEMPLATE.md, so these ids are CP001 to CP080, the same ids as Copilot's round 2 file; they are scored as a separate file and named gemini_ in every result.
Gemini wrote and ran Python inside its answer to build and check the cases; its final answer block holds the 80 lines (40 stop, 40 allow). That block was read from the page and copied to a file; no line was edited. A second file keeps every code block on the page as copied.

The guard under test is the same public guard.py as rounds 1 and 2 (SEAL.md).

```
c2ef6e7fb54fec2a5af2da6b9a5ec8e57f6554e02096bb7bec493bc3c7b76bb7  gemini_cases.jsonl
121a362a525956752503b38166b70c12015a36cbf1bf45f90b90088f5fe16b4a  gemini_RAW_all_code_blocks_on_page.txt
```
