# blind_v31 seal: the guards were frozen before any case was written

**Where this seal lives.** It was written on 2026-11-21 at 23:02 CST and committed in a private repository, at commit `acd7f7236` there (committed 2026-11-21 23:02:40 -0600). That repository is not public. This repo has no public commit that holds the seal, so unlike blind_v20 (sealed on the public `blind-v20-seal` branch at `f4dccd0`) nobody outside can check the order from git history. What you can check from here: the sha256 of the set, the sha256 of `guard.py` and `variants/guard_v30.py` and `variants/guard_v20.py`, and that the per-row results re-score from them. The text below is the seal's text, with private file paths and commit ids left out.

At the moment of sealing, no writer prompt had been sent and no case file existed. The folder held only the writer sheet (copied from blind_v29's, with the title changed; see `method/WRITER_SHEET.md`) and the seven project settings (`method/ROUND_SETTINGS.tsv`). The hashes were read with `shasum -a 256`.

| guard | file | sha256 |
|---|---|---|
| v30 (the candidate that became `guard.py`; built from blind_v29's misses and a wrapper red team, so SEEN on blind_v29) | `variants/guard_v30.py` | 08bf8c61aa7a6462a2f3aadefdc865ccb0d1f47cbf60aebf012581532721f887 |
| v29 (candidate before v30; scored blind on blind_v29) | not in this repo | b8aec17156c43a2ce658720e17a3eeacb5f755d1e4db6708df3c21e8b29820d9 |
| v28 (the guard in use on my own machine then; file not in this repo) | not in this repo | e0bd220e6574d7ecfce4af43b625efc99098bcaf28f139709d839a1cdd592cf8 |
| v20 (the version behind this README's earlier 98.3%) | `variants/guard_v20.py` | 1f16f4606e53999958f99f807946b60a1ba7806193bbe94e59ddce8f784dbbad |

The rule for this set: no file above changes after the first writer prompt is sent. A later fix is a new version scored seen on this set.

A version I was building while the set was written (v31) was not sealed. Any score of it on this set would be reported as "not sealed before writing", never as blind. v31 and v32 are not in this repo and are not scored here.

Method: blind_v29's, unchanged. Eight outside free models (ChatGPT, Gemini, Grok, DeepSeek, Mistral, Copilot, Qwen, Perplexity) wrote cases from the writer sheet, one row of `method/ROUND_SETTINGS.tsv` per round. Near-duplicates of every earlier case file were removed. Three sealed Claude labelers labeled every case, with `method/LABEL_RULES.md` byte for byte in each prompt; an outside tiebreak decided the disputed ones. The set was locked before any guard scored it (`LOCK.txt`).

Disclosure from the labeler audit: the tool that ran the labelers also put my private repository's standing instructions into each labeler's context. None of that text holds a case, a label, a blind set or guard code. The audit found 0 voided labelers; 24 labelers, three labels per case, Fleiss kappa 0.99 over the 2,429 cases.
