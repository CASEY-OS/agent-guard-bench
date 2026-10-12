# holdout9: written by Gemini (Google), not by any Claude model

Written 2026-10-12 by Gemini (free tier) from the same prompt as holdout8 (the three rules and the output
format only). Pasted by Casey Rose into the session; RAW_PASTE.txt is that paste, byte for byte.
holdout9.jsonl is the paste with ONE kind of repair: five lines (T008, T009, T015, T032, T062) carried
unescaped double quotes inside the command and were not valid JSON; their fields were read as written and
re-encoded. No command, label or reason was changed.
Damage the paste carried, left as written: `HEAD1` (T035, T053) was almost surely `HEAD~1`, and `git add ''`
(T011) was almost surely `git add '*'`; a chat renderer drops ~ and * in pairs.
Labels I dispute, kept and scored as written: T033 (`push -o no-verify` sends a push option to the server; the
local pre-push hook still runs) and T034 (`commit -c` after the subcommand means reuse a commit's message, so the
command fails and changes nothing).
80 cases: 50 stop (A 17, B 17, C 16), 30 allow. Guard v6 was frozen in 71f417f before it was written.
