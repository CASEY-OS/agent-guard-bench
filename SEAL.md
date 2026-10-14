# holdout18 seal (commit before reveal)

Written 2026-10-14, about 14:00 to 14:12 Central (an earlier version of this line said 14:30 to 15:00, which was wrong; the push time of the commit before this one is the record). Four outside models each got the same prompt in a fresh chat on its own site:
ChatGPT (chatgpt.com, temporary chat; its "Unpersonalized" switch did not take, so the chat may have read account memory),
DeepSeek (chat.deepseek.com), Mistral (Le Chat), Grok (grok.com, private chat). Each was asked for 80 cases, 40 stop and 40 allow.
Gemini was asked too and returned an error twice; it is not in this set.
Each answer was copied with the site's own copy button straight to a file. No line was edited.

The guard under test is guard.py as public on GitHub before these cases existed: blob d4bc48dea0943a106ae96b47f2101cdc665dbd2b (commit 0ed413b).
The cases are not in this repository yet. They will be added unedited, and scored, only after this commit is on GitHub.
Anyone can check the files then against these hashes.

```
dd0c9b680edb669ca7e0c13afb8b3964add923b92509fd7370aef85a794dd9b1  chatgpt_cases.jsonl
f2b00f76fed38904f27d775b099fb86b437ac5c0d47922b130dcbeee0f6bbb29  deepseek_cases.jsonl
47a64b6f0ec4e8a8764300535650eb7173cdeb103e95aac3b4038bf65123304e  grok_cases.jsonl
9d3512d1ed8b25df6bab882fbf2cf81318ae9ae357843b1b627bf9940cbb0602  mistral_cases.jsonl
7a912f32696d50b6803a4330696196d344f8f2b888a7894449964115cecf6d0d  PROMPT_TEMPLATE.md
```
