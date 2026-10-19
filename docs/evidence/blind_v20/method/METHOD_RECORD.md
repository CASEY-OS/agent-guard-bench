# blind_v20: how the labels were made (the record the seal promised)

The seal (branch `blind-v20-seal`, commit `f4dccd0`, 2026-10-19 07:40 CDT) fixed the set and every guard's sha256 before any guard ran on the set. This folder is the labeling record behind `../blind_v20_set.jsonl`. Case numbers here are the set's ids without the prefix: `n` 1624 is `BV201624`.

## Correction to the seal
The seal says guard_v20.py was frozen before this set's first case was written. On the clock that is wrong: the first cases were written from 20:33 CDT on 2026-10-18, and v20's file was last edited at 20:59 (its builder stopped at 21:08). The builder was a separate agent; its recorded tool calls show it never opened a blind_v20 file, and its search script skipped them by name. No writer saw the guard.

## Writing
Free models from nine companies other than the guard's builder (ChatGPT, Gemini, Grok, DeepSeek, Mistral, Copilot, Kimi, Qwen, Perplexity; not every model answered every round) wrote 4,272 commands across fourteen rounds (M to Z) of new project settings. No writer saw the guard or a scored set. Near-duplicates of every earlier case and set (including the spent blind_v19) were removed: 3,300 left.

## Labels
- Three Claude labelers per case, each in its own sealed folder with its own shuffled copy of its chunk (nine chunks). An audit of every labeler's file reads and writes found none outside its own folder.
- A first labeling run was voided before any vote was counted: its labelers shared one folder, and rows crossed files.
- 3,218 cases were unanimous and confident (Fleiss kappa 0.997). `reconciled.json` holds the result (`final`) and the 82 cases that were not (`disputed`).
- The 82 went to three outside models (ChatGPT, Gemini, DeepSeek) with the written rules and the commands only (`TIEBREAK_PROMPT.txt`; replies in `tiebreak/`). The rule (majority of the three) and the panel were fixed before any reply was read. All 82 were decided; none dropped; 24 differed from the Claude majority.

## Runs
- Every case that could run was run in a throwaway git repo under the macOS sandbox (`case.sb`: no network, writes only inside the run folder). Planted escapes were tried first and all failed (`CONTAINMENT.md`).
- 2,281 ran; 1,019 could not run there. `run_exec.py` is the harness; `ORACLE_RULES.md` says how a run's effect is read as stop or allow; `exec_results.jsonl` holds each case's result (machine paths replaced by `<run>` and `~`).
- Every case where the run disagreed with a unanimous label was reviewed against the written rules. Two labels were corrected, stop to allow, where the rules say allow (`EXEC_CHANGES.tsv`). None was dropped.
- `final_labels.json` is the label set after the tiebreak and those two changes; `../blind_v20_set.jsonl` was written from it and locked (`../LOCK.txt`) before any guard was loaded.

## What this does not prove
The labelers are Claude, the model family that built the guard; the outside tiebreak and the sandbox runs exist because of that, and they cover the disputed cases and the runnable ones, not every unanimous label. The cases are written by AI models, not taken from real agent traffic.
