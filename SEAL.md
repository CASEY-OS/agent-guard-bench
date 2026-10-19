# blind_v19 seal: the test set and the guard under test, fixed BEFORE scoring

Sealed 2026-10-18 20:24 CDT. No guard had been run on this set when this file was pushed.

## The set
`blind_v19_set.jsonl` sha256 `ae5a6fb0569a08e553726cfd6d8b29ed57e8019f1c9997ffa8778b1290ff4ccf`
2,266 cases: 1,200 that must be stopped, 1,066 that must be allowed. The file itself is published with the scores; its bytes must match this hash.

## The guards that will be scored (sha256)
```
9f5d9f0b6c222d19268376bbb043e6dc7f312e8e735efd3a73b6031de8120b45  guard.py
30bb71b8ad383705ab70d30a10490b761992dda1adb0a57a2c1fbb6e75f16344  guard_v15.py
9cf6d3a12dc77cacb8127cb65588947b40383d43e7cfc9d1896a08fcdbd6fd4a  guard_v16.py
13a33d65ccc05156215d590e243df7d7dae3cc839580fbd591ee07a324b92131  guard_v17.py
c0d6d450173635cd7831ab8ba960944182c03dffff7c25ff1871a5c08898ff8c  guard_v18.py
8b70f5d30f053f1469cb0c8499f681317e9c48ded0ca1276140a4674a7b1fe71  guard_v19.py
```

## How the set was made (method only; full record ships with the scores)
- Written by free AI models from nine companies other than the guard's builder (ChatGPT, Gemini, Grok, DeepSeek, Mistral, Copilot, Kimi, Qwen, Perplexity; Kimi answered two rounds), most on their thinking modes, across eight rounds of new project settings. No writer saw the guard or any scored set.
- 2,877 written; near-duplicates of every earlier case and set (including the spent blind_v18) removed: 2,274 left.
- Three blind labelers per case (Claude, the same model family that built the guard; that is why the next two steps exist), each in its own shuffled order, read audit clean. 2,210 unanimous and confident; Fleiss kappa 0.991.
- The 64 others went to eight outside models with the rules and the commands only; majority decided 57, 7 ties dropped (rule written before any answer was read).
- Every git-only case was RUN in a throwaway repo under the macOS sandbox (no network, writes only inside the run folder; planted escapes all failed). 1,528 executed: 2 labels corrected (the command really staged the whole tree), 1 dropped (an ambiguous form), every mismatch reviewed and listed.
