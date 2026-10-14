# holdout18, round 2 seal (commit before reveal)

Written 2026-10-14, about 14:30 to 14:43 Central (an earlier version of this line said 14:40 to 15:05, which was wrong; the push time is the record), after round 1 (SEAL.md) was already public.
Three more outside models got the same prompt (PROMPT_TEMPLATE.md in round 1, only the id prefix changed) in a fresh chat on its own site:
Microsoft Copilot (copilot.microsoft.com), Kimi (kimi.ai; the prompt went in as an attached text file with the line "Follow the attached writer sheet exactly."), Qwen (chat.qwen.ai, Qwen3.7-Plus).
Each wrote 80 cases, 40 stop and 40 allow.

How each answer reached a file, byte for byte from the page:
- Qwen: the site's copy button. The raw copy carries the code fence lines; the cases file is the raw copy minus those two lines.
- Copilot and Kimi: their copy buttons did not reach the clipboard, so the code block's text was selected on the page and copied. Copilot's selection also caught three page labels ("Plain Text", a syntax-highlighting note, "Copy code"); the cases file is the selection minus those lines. Kimi's selection was the 80 case lines only.
No case line was edited. The raw copies are hashed too.

The guard under test is the same public guard.py as round 1 (blob in SEAL.md, commit 0ed413b).

```
f4f7424534d44174377d4989384d14c9c0162ba115560d871c5c2c92a80da926  copilot_cases.jsonl
2db68a1afde566e13928ad69c6e93f59300347d26515f8a36ca8b349bfd615cf  kimi_cases.jsonl
e2ba4494e8bb80988e6b0e53bb4d897447248b6cce8e67e69afc11048d19c7e4  qwen_cases.jsonl
c1df0f66c74b2431bac39c76c62229bd024019e49947c47801306c917a05b0ed  copilot_RAW_page_selection.txt
2add5923b11f7d073f9a4b52b7975e81eee0e9185f2cde5cd48922de9b7d11bd  kimi_RAW_page_selection.txt
81dddb451409845fb27ccdcb17b0c129c7db3d3d7364022f6582b8b7780131ca  qwen_RAW_copy_button.txt
```
