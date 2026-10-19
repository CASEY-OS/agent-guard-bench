# blind_v20 seal: the test set and the guard under test, fixed BEFORE scoring

Sealed 2026-10-19 07:40 CDT. No guard had been run on this set when this file was pushed.

## The set
`blind_v20_set.jsonl` sha256 `dcf6cf6e406b1c8f889f009a212ee34bc289cfb73ee779b41daf4c4fc6efbfa4`
3,300 cases: 1,717 that must be stopped, 1,583 that must be allowed. The file itself is published with the scores; its bytes must match this hash.

## The guards that will be scored (sha256)
```
9f5d9f0b6c222d19268376bbb043e6dc7f312e8e735efd3a73b6031de8120b45  guard.py
30bb71b8ad383705ab70d30a10490b761992dda1adb0a57a2c1fbb6e75f16344  guard_v15.py
9cf6d3a12dc77cacb8127cb65588947b40383d43e7cfc9d1896a08fcdbd6fd4a  guard_v16.py
13a33d65ccc05156215d590e243df7d7dae3cc839580fbd591ee07a324b92131  guard_v17.py
c0d6d450173635cd7831ab8ba960944182c03dffff7c25ff1871a5c08898ff8c  guard_v18.py
8b70f5d30f053f1469cb0c8499f681317e9c48ded0ca1276140a4674a7b1fe71  guard_v19.py
1f16f4606e53999958f99f807946b60a1ba7806193bbe94e59ddce8f784dbbad  guard_v20.py
```
guard.py through guard_v19.py are byte-identical to the blind_v19 seal. guard_v20.py was frozen before this set's first case was written; its builder never saw this set.

## How the set was made (method only; full record ships with the scores)
- Written by free AI models from nine companies other than the guard's builder (ChatGPT, Gemini, Grok, DeepSeek, Mistral, Copilot, Kimi, Qwen, Perplexity; not every model answered every round), most on their thinking modes, across fourteen rounds (M to Z) of new project settings, workflows and stacks. No writer saw the guard or any scored set.
- 4,272 written; near-duplicates of every earlier case and set (including the spent blind_v19) removed: 3,300 left.
- Three blind labelers per case (Claude, the same model family that built the guard; that is why the next two steps exist), each sealed in its own folder with its own shuffled copy; a read and write audit found no labeler touching anything outside its folder. A first labeling run was voided before any vote was counted, because its labelers shared one folder and rows crossed files. 3,218 unanimous and confident; Fleiss kappa 0.997.
- The 82 others went to three outside models (ChatGPT, Gemini, DeepSeek) with the rules and the commands only; majority decided all 82, none dropped, 24 differed from the Claude majority. The rule, and the three-model panel, were fixed before any outside answer was read.
- Every case was RUN where possible in a throwaway repo under the macOS sandbox (no network, writes only inside the run folder; planted escapes all failed before any case ran). 2,281 executed, 1,019 not executable there. 2 labels corrected (stop to allow, where the written rules themselves say allow), none dropped; every mismatch reviewed and listed.
