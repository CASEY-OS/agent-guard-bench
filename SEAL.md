# holdout19 seal: hashes of outside-model cases, before scoring

Sealed 2026-10-14 18:00 CT (machine clock reading at sealing).

The guard under test is v14, frozen publicly at 2026-10-14 17:50 CT (branch v14, commit e88a7d8, guard.py blob 025f02e72411e55150931075c9c32ac40af60423). That freeze was published before these cases existed. The collector did not read guard.py or any case files in the repo. Nothing here has been scored.

## Sites that answered (all in Casey's signed-in Chrome, one prompt each, prompt text unchanged)

| Site | Model / mode shown | URL | Lines | stop / allow |
|---|---|---|---|---|
| ChatGPT | free tier, temporary chat | https://chatgpt.com/?temporary-chat=true | 80 | 39 / 41 |
| DeepSeek | default chat, no DeepThink toggle set | https://chat.deepseek.com/ | 80 | 40 / 40 |
| Mistral | Le Chat "Vibe" Work mode (model not named on page) | https://chat.mistral.ai/chat | 80 | 40 / 40 |
| Grok | Fast mode, Private chat | https://grok.com/ | 80 | 48 / 32 |
| Copilot | Auto | https://copilot.microsoft.com/ | 80 | 40 / 40 |
| Kimi | Instant High (K3 per page title) | https://www.kimi.ai/ | 80 | 40 / 40 |
| Qwen | Qwen3.7-Plus, Auto | https://chat.qwen.ai/ | 80 | 40 / 40 |
| Perplexity | free plan, Search mode | https://www.perplexity.ai/ | 180 (ids H19PX001 to H19PX180; it wrote more than the 80 asked) | 104 / 76 |

Perplexity searches the web. Its answer may have used web results, although the prompt said not to search.

## Skipped

- Gemini (https://gemini.google.com/app): returned "Sorry, something went wrong" on the first send, then "I encountered an error doing what you asked" on Try again. Skipped as instructed. No Gemini file exists.

## How each answer was copied

Byte for byte from the page, never retyped. The clipboard was set to a marker first and checked after.
- Site code-block Copy button, then pbpaste to file: ChatGPT, DeepSeek, Mistral, Grok, Copilot, Kimi, Qwen, Perplexity. (Copilot and Kimi copy buttons worked this time.)
- No site needed the JS text-selection fallback.
- `*_RAW.txt` is the copied text as saved. `*_cases.jsonl` is the JSON lines only. For seven sites RAW and cases are identical (no fences came through). For Qwen the copy included the two fence lines ("```jsonl" and "```"); the cases file drops those two lines and nothing else.
- Each cases file was checked: every line parses as JSON, ids unique, ids carry the site prefix (H19CG, H19DS, H19MS, H19GK, H19CP, H19KM, H19QW, H19PX), and no two cases files are identical.

## SHA256SUMS

```
e8378b4d1b8bd251c4af06048691a1f76f67bd63b796dd186e404f69b19e931f  chatgpt_cases.jsonl
d7d4d615d8e955a633aa46c45d509d87b2255e289ec85e7b38652e79fd8650a8  copilot_cases.jsonl
9af3e3f108b1731a86761f83619caa3fe22a8e780406363787203a3b52cf4d10  deepseek_cases.jsonl
5f59b066d820df67efc898dd90cb0e4cb82f6849753b94c2f05729b15e7b3c07  grok_cases.jsonl
dbdbb47c1255adbcde045530c2c0035951798994d53edb74f87a2d5d800ff169  kimi_cases.jsonl
5b88ca2b188cb3ad0d638cd1d74cb813665c9e9b9d502e7f0ca34dde5254c343  mistral_cases.jsonl
74099bbfd3bdab890e36e2ff429aea74730dca70674f119b62b782d01f74655d  perplexity_cases.jsonl
ee83d45a213ad35239b67968e004aaec39b9adea778e04371dd2ffb5c3cb285b  qwen_cases.jsonl
e8378b4d1b8bd251c4af06048691a1f76f67bd63b796dd186e404f69b19e931f  chatgpt_RAW.txt
d7d4d615d8e955a633aa46c45d509d87b2255e289ec85e7b38652e79fd8650a8  copilot_RAW.txt
9af3e3f108b1731a86761f83619caa3fe22a8e780406363787203a3b52cf4d10  deepseek_RAW.txt
5f59b066d820df67efc898dd90cb0e4cb82f6849753b94c2f05729b15e7b3c07  grok_RAW.txt
dbdbb47c1255adbcde045530c2c0035951798994d53edb74f87a2d5d800ff169  kimi_RAW.txt
5b88ca2b188cb3ad0d638cd1d74cb813665c9e9b9d502e7f0ca34dde5254c343  mistral_RAW.txt
74099bbfd3bdab890e36e2ff429aea74730dca70674f119b62b782d01f74655d  perplexity_RAW.txt
9913da96d45db791e0ee0c97f5ae6657c406bd8012358a2f0788a8859f266a92  qwen_RAW.txt
6a37b234d7e2d079a622f3702154a0ec744cbed4402790ad085eca3a5aeb116d  prompts/prompt_template.md
```

Note: for seven sites the cases and RAW hashes are equal because the files are identical. Only Qwen differs.
