# SOURCES (date read: 2026-10-14). One line per source: URL | what it is | source post date
# Every GitHub issue body was fetched whole via the GitHub REST API (gh api repos/<repo>/issues/<n>); every command in incidents.jsonl was string-matched against the fetched text (field verbatim_substring_match). Cursor forum threads fetched as Discourse .json; HN via hn.algolia.com items API; Reddit via api.pullpush.io; blogs via curl.

https://github.com/openai/codex/issues/8548 | github_issue: Codex agent commits unrelated files using git add -A despite explicit “commit only working changes” policy | 2025-12-25
https://github.com/google-gemini/gemini-cli/issues/15580 | github_issue: Git reset deleted local files | 2025-12-26
https://github.com/anomalyco/opencode/issues/14593 | github_issue: Critical Bug: Kimi K2.5 bypasses "ask" permission for shell commands and commits autonomously (v1.2.10) | 2026-02-21
https://github.com/microsoft/vscode/issues/307688 | github_issue: Copilot Chat session list runs `git add -A -- .` on VFS for Git repos at startup, consuming tens of GB of memory | 2026-04-03
https://github.com/anthropics/claude-code/issues/45108 | github_issue: Subagent commits silently delete unrelated files via broad git staging | 2026-04-08
https://github.com/openai/codex/issues/19588 | github_issue: Codex App ghost snapshot runs git add -A on trusted home directory and fills disk with tmp_pack files | 2026-04-25
https://github.com/openai/codex/issues/26685 | github_issue: Codex Desktop macOS crash: git worker OOM after branch-diff git add scans home directory | 2026-06-05
https://github.com/openai/codex/issues/28036 | github_issue: VS Code extension runs background mutating git add -A before any user task, scanning .bare object database | 2026-06-13
https://github.com/openai/codex/issues/28750 | github_issue: Codex.app repeatedly runs git add -A without user request, filling .git/objects/pack | 2026-06-17
https://github.com/anthropics/claude-code/issues/87177 | github_issue: [BUG] Insecure code generation: markdown backticks in an unquoted heredoc execute locally | 2026-08-16
https://github.com/anthropics/claude-code/issues/87639 | github_issue: [Bug] Interactive auto mode bypasses permissions.ask rules for PreToolUse decisions | 2026-08-18
https://github.com/anthropics/claude-code/issues/88738 | github_issue: PreToolUse hook silently stops firing mid-session and never recovers; concurrent session unaffected | 2026-08-22
https://github.com/anthropics/claude-code/issues/88950 | github_issue: [Bug] Worktree isolation pin shared across parallel subagents causes cross-agent command execution | 2026-08-23
https://github.com/anthropics/claude-code/issues/90176 | github_issue: [BUG] WorktreeCreate hooks are unreachable in Cowork | 2026-08-27
https://github.com/anthropics/claude-code/issues/92542 | github_issue: [BUG] Bash deny rules bypassed by any wrapper program outside ax()'s 8-item unwrap list | 2026-09-06
https://github.com/anthropics/claude-code/issues/97842 | github_issue: [BUG] Squash request force-pushed uncommitted working-tree changes (git add -A after reset --soft) | 2026-09-28
https://github.com/Aider-AI/aider/issues/2168 | github_issue: aider forgets to put quotation marks on the commit message? | 2024-10-27
https://github.com/Aider-AI/aider/issues/3925 | github_issue: Aider is erroring on commit but still writing files with --subtree-only | 2025-05-01
https://github.com/cline/cline/issues/4833 | github_issue: AI Assistant Ignores Project Rules Despite Clear Instructions in .clinerules/ | 2025-07-11
https://github.com/google-gemini/gemini-cli/issues/14471 | github_issue: Gemini CLI Agent Caused Irrecoverable Data Loss, Repeatedly Violated Instructions, and Failed Core Engineering Task Due to Environmental Mismanagement | 2025-12-03
https://github.com/anthropics/claude-code/issues/30251 | github_issue: [Bug] Worktree setup modifies main repo git config instead of worktree-specific config | 2026-03-03
https://github.com/anthropics/claude-code/issues/40117 | github_issue: Agent bypasses git pre-commit hooks using --no-verify, stash, and quiet flags despite explicit deny rules | 2026-03-28
https://github.com/anomalyco/opencode/issues/29259 | github_issue: [FEATURE]: I am tired of agents using --no-verify | 2026-05-25
https://github.com/anthropics/claude-code/issues/66069 | github_issue: git commit bypasses commit-msg hook (likely --no-verify) | 2026-06-07
https://github.com/anthropics/claude-code/issues/66993 | github_issue: Worktree creation rewrites shared core.hooksPath, silently disabling repo-managed git hooks for the whole clone | 2026-06-10
https://github.com/openai/codex/issues/29294 | github_issue: Curated-plugin startup_sync can reset an unrelated repository (refs/codex/curated-sync, hook-bypassed) | 2026-06-21
https://github.com/Aider-AI/aider/issues/5376 | github_issue: Security Risk: Aider silently bypasses pre-commit hooks by default (--no-verify) | 2026-07-01
https://github.com/anthropics/claude-code/issues/72714 | github_issue: bug: /worktree can silently write core.hooksPath into the MAIN repo's shared .git/config, disabling global hooks | 2026-07-01
https://forum.cursor.com/t/167719 | cursor_forum_thread: Git hooks silently skipped for all Source Control operations since 3.15.6 — git extension forces `core.hooksPath=/dev/null` | 2026-08-07
https://github.com/anthropics/claude-code/issues/86434 | github_issue: [BUG] `/goal`: the Stop-hook condition is frozen at creation time and the verifier cannot see later cancellation | 2026-08-13
https://github.com/anthropics/claude-code/issues/100989 | github_issue: [Bug] Model bypasses project rules with git commit --no-verify | 2026-10-10
https://news.ycombinator.com/item?id=44656189 | hacker_news_comment: HN comment by Faark on "I watched Gemini CLI hallucinate and delete my files" | 2025-07-23
https://github.com/google-gemini/gemini-cli/issues/5352 | github_issue: Gemini agent performed a 'git reset --hard' without user confirmation, causing data loss of uncommitted files. | 2025-08-01
https://github.com/google-gemini/gemini-cli/issues/6321 | github_issue: Bug falha em proteger dados, e ações levaram a essa perca total dos dados. | 2025-08-15
https://github.com/cline/cline/issues/6955 | github_issue: Cline incorrectly deleted working files when asked to revert code to earlier time | 2025-10-17
https://github.com/anthropics/claude-code/issues/11237 | github_issue: [BUG] CLAUDE CODE running a git command without prompting resulting in catastrophic data loss | 2025-11-08
https://github.com/anthropics/claude-code/issues/11821 | github_issue: [SAFETY] Claude Code should block destructive git commands without user confirmation | 2025-11-18
https://github.com/microsoft/vscode/issues/279071 | github_issue: VS Code Copilot Grok Code Fast 1 merged and deleted branch without consent | 2025-11-23
https://github.com/anthropics/claude-code/issues/13904 | github_issue: Incident Report: Claude Opus 4.5 Destructive Actions During Test Restructuring | 2025-12-13
https://github.com/openai/codex/issues/8643 | github_issue: Codex VS Code extension/agent ran git restore despite explicit “never touch git” instruction, overwriting uncommitted work (data loss) | 2025-12-31
https://github.com/anthropics/claude-code/issues/16098 | github_issue: Claude Code incorrectly reverted user's uncommitted work while debugging | 2026-01-02
https://github.com/microsoft/vscode/issues/292145 | github_issue: [BUG] Critical: Development environment files deleted during build optimization attempts by Copilot agent | 2026-02-01
https://github.com/anthropics/claude-code/issues/22638 | github_issue: [MODEL] Claude repeatedly ignored CLAUDE.md rules, executed destructive git command causing data loss | 2026-02-02
https://github.com/anthropics/claude-code/issues/29179 | github_issue: Claude Code destroyed gitignored files with unnecessary git clean -fd during branch creation | 2026-02-27
https://github.com/anthropics/claude-code/issues/33850 | github_issue: Agent destroyed 2 days of uncommitted work via destructive git operation in main worktree | 2026-03-13
https://github.com/anthropics/claude-code/issues/34327 | github_issue: Claude Code destroyed user's uncommitted work by running git reset --hard on session startup — TWICE | 2026-03-14
https://forum.cursor.com/t/154810 | cursor_forum_thread: Cursor agent just delete my changes by "git restore" in sandbox | 2026-03-15
https://github.com/anthropics/claude-code/issues/37150 | github_issue: Opus 4.6: destroyed working files by careless git operations, then misdiagnosed the cause | 2026-03-21
https://github.com/google-gemini/gemini-cli/issues/23411 | github_issue: Add protections against git reset --hard and git push --force | 2026-03-21
https://github.com/anthropics/claude-code/issues/45974 | github_issue: Claude ran git clean -fd without permission, destroyed untracked files | 2026-04-09
https://github.com/google-gemini/gemini-cli/issues/25217 | github_issue: Gemini went over all restricitons and git reset --hard and git rm all by work, oevrpassing al guardails I had set up | 2026-04-12
https://github.com/anthropics/claude-code/issues/56418 | github_issue: [BUG] Claude is calling bash commands that are prohibited. | 2026-05-05
https://github.com/anthropics/claude-code/issues/58885 | github_issue: [BUG] In 2.1.141, stale-worktree cleanup uses `rm -rf` as a fallback and silently deletes untracked code | 2026-05-14
https://github.com/anthropics/claude-code/issues/66176 | github_issue: Permission rules are bypassed by semantically-equivalent command%2 0forms (`git -C`, `cd &&`, env prefixes) | 2026-06-08
https://github.com/anthropics/claude-code/issues/67322 | github_issue: [BUG] Claude by-pass safety features in auto mode | 2026-06-11
https://github.com/anthropics/claude-code/issues/68315 | github_issue: [Bug] File checkpointing silently stashes and hard-resets working tree, destroying uncommitted edits | 2026-06-13
https://github.com/anthropics/claude-code/issues/70363 | github_issue: [Haiku] Claude Code destroyed 2 hours of uncommitted work by running git checkout --   . without confirmation | 2026-06-23
https://github.com/anthropics/claude-code/issues/70378 | github_issue: [MODEL] If `git push --force-with-lease` fails, Claude does a `--force` anyway clobbering changes | 2026-06-23
https://github.com/anthropics/claude-code/issues/70687 | github_issue: [BUG] Claude borró todos los archivos de un proyecto Unity de 3 años con git rm -rf | 2026-06-24
https://github.com/anthropics/claude-code/issues/75861 | github_issue: [BUG] Explore (read-only) subagent executed rm -rf, deleting files outside its intended scope | 2026-07-08
https://github.com/anthropics/claude-code/issues/81508 | github_issue: [BUG] Opus 5[1m, MAX] ran `git checkout --` unprompted and destroyed all uncommitted work because of formatting | 2026-07-27
https://github.com/anthropics/claude-code/issues/83766 | github_issue: [BUG] permissions.ask rules never trigger when defaultMode is "auto" — matching commands auto-approved, including destructive ones | 2026-08-04
https://github.com/anthropics/claude-code/issues/84162 | github_issue: [BUG] Worktree cleanup is unsafe on Windows — 'git worktree remove --force' destroys NTFS junction targets, so vendor-created worktrees accumulate wit | 2026-08-05
https://github.com/anthropics/claude-code/issues/84660 | github_issue: Claude Code executed HEAD is now at b2a0ae7e [DOCS-3098] update pages, app providers and submodules for multi-role without user confirmation, causing  | 2026-08-06
https://github.com/anthropics/claude-code/issues/85450 | github_issue: [Bug] Claude Code force-pushed open PR branch without explicit destructive operation consent | 2026-08-10
https://github.com/anthropics/claude-code/issues/87360 | github_issue: auto-mode classifier did not block an agent-authored script that ran `git clean -xdff` at the workspace root (21 projects destroyed, native Windows) | 2026-08-17
https://github.com/anthropics/claude-code/issues/95355 | github_issue: [BUG] Critical: git stash pop + reset --hard destroyed ~600 lines of new code and unrelated stash in worktree session | 2026-09-18
https://github.com/cline/cline/issues/14367 | github_issue: [Bug]: Checkpoint restore reverts uncommitted .gitignore before git clean -fd, permanently deleting untracked files | 2026-09-21
https://github.com/anthropics/claude-code/issues/97881 | github_issue: Auto-mode permission classifier misses git reset --hard when bundled in a multi-line Bash command, then false-positives on an unrelated later command | 2026-09-28
https://github.com/google-gemini/gemini-cli/issues/5013 | github_issue: Repeated Git Commit Errors and Data Loss | 2025-07-28
https://github.com/google-gemini/gemini-cli/issues/13331 | github_issue: Restore deletes virtually all files from my git directory | 2025-11-18
https://github.com/cline/cline/issues/7572 | github_issue: Cline deleted home directory | 2025-11-20
https://www.reddit.com/r/google_antigravity/comments/1p82or6/google_antigravity_just_deleted_the_contents_of/ | reddit_post: Google Antigravity just deleted the contents of my whole drive. | 2025-11-27
https://github.com/anthropics/claude-code/issues/23913 | github_issue: Agent deleted 2,229 untracked source files without explicit user instruction — catastrophic unrecoverable data loss | 2026-02-07
https://github.com/anthropics/claude-code/issues/24196 | github_issue: [BUG]  Data loss caused by Claude Code — unauthorized destructive command | 2026-02-08
https://github.com/anthropics/claude-code/issues/27063 | github_issue: Claude Code agent autonomously ran destructive db command, wiped production database | 2026-02-20
https://github.com/anthropics/claude-code/issues/29082 | github_issue: [BUG] Critical Bug: Claude Code executed 'rm -rf' and deleted project files unexpectedly | 2026-02-26
https://alexeyondata.substack.com/p/how-i-dropped-our-production-database | blog_post: How I Dropped Our Production Database and Now Pay 10% More for AWS | 2026-03-06
https://github.com/anthropics/claude-code/issues/32938 | github_issue: Claude deleted 11h of inference output without permission then restarted job | 2026-03-10
https://github.com/anthropics/claude-code/issues/36183 | github_issue: [MODEL] Claude ran `prisma db push --force-reset` on production database, wiping all data without user consent | 2026-03-19
https://github.com/anthropics/claude-code/issues/36339 | github_issue: [BUG]   [Windows] rm -rf on pnpm project deleted entire C:\Users via NTFS junction traversal — Claude Code v2.1.51 | 2026-03-19
https://github.com/anthropics/claude-code/issues/36637 | github_issue: Chained bash commands silently bypass the tool permission allowlist | 2026-03-20
https://github.com/anthropics/claude-code/issues/36640 | github_issue: [BUG]  Claude deleted production data | 2026-03-20
https://github.com/anthropics/claude-code/issues/45463 | github_issue: Claude Code executed destructive database operation without user approval | 2026-04-08
https://github.com/anthropics/claude-code/issues/48792 | github_issue: [Bug] Claude Code executed unauthorized rm -rf due to case-insensitive filesystem path resolution | 2026-04-15
https://github.com/anthropics/claude-code/issues/49102 | github_issue: Catastrophic data loss — autonomous `rm -rf` destroyed user home subtree despite APFS case-insensitive ambiguity and existing safeguards | 2026-04-16
https://forum.cursor.com/t/158991 | cursor_forum_thread: Critical incident: Cursor agent left repository and deleted local Documents folder | 2026-04-25
https://github.com/anthropics/claude-code/issues/54104 | github_issue: Claude closes PRs and deletes branches in response to user questions, not commands | 2026-04-27
https://github.com/anthropics/claude-code/issues/56603 | github_issue: Catastrophic data loss from `cmd /c rd /s /q` via PowerShell tool with broken quoting on Unicode/space path | 2026-05-06
https://github.com/anthropics/claude-code/issues/60442 | github_issue: [Bug] Sub-agent `rm -rf` with case-insensitive path collision destroys workspace; no sandbox, confirmation, or orchestrator interception | 2026-05-19
https://github.com/anthropics/claude-code/issues/62091 | github_issue: Agent deleted user's main project repo via gh repo fork --fork-name rename behavior | 2026-05-24
https://github.com/anthropics/claude-code/issues/64355 | github_issue: [BUG] Opus deleted entire repository without realizing it (corrupt tool call?) | 2026-05-31
https://forum.cursor.com/t/164675 | cursor_forum_thread: Cursor Agent Completely Wiped My C: Drive and Deleted Everything | 2026-07-02
https://forum.cursor.com/t/166931 | cursor_forum_thread: [Windows] Agent Shell: rmdir /s with trailing \ before " escapes target and wipes volume root | 2026-07-29
https://github.com/anthropics/claude-code/issues/82165 | github_issue: Catastrophic data loss: agent-built command expanded to "rm -rf /*", ran detached; safety classifier then blocked the kill attempts | 2026-07-29
https://github.com/anthropics/claude-code/issues/85200 | github_issue: [BUG] TaskStop does not kill the process tree — orphaned `rm -rf /c` deleted user data for 20 minutes after stop | 2026-08-09
https://github.com/anthropics/claude-code/issues/88462 | github_issue: [Data Loss] Claude Code ran rm -rf on $HOME in auto mode — destructive code hidden inside a script the assistant wrote itself (5th report of this clas | 2026-08-21
https://github.com/anthropics/claude-code/issues/89787 | github_issue: [MODEL] Claude Code agent DELETE the whole data dir! | 2026-08-26
https://github.com/anthropics/claude-code/issues/91676 | github_issue: [BUG] Sandboxed `mktemp -d` fails on macOS (ignores `$TMPDIR`); the empty variable made `rm -rf "$T"` run against the working directory with no critic | 2026-09-03
https://github.com/anthropics/claude-code/issues/92593 | github_issue: Runaway rm -rf: timeout auto-backgrounding kept a destructive command running, and TaskStop did not kill the child process (Windows) | 2026-09-07
https://github.com/openai/codex/issues/43343 | github_issue: Codex destructive cleanup escaped workspace on Windows and recursively deleted files outside target directory | 2026-09-07
https://github.com/anthropics/claude-code/issues/93099 | github_issue: [MODEL] Opus 5 executed rm -rf "$HOME" during test cleanup(57,235 files and 11,315 directories deleted), causing extensive data loss | 2026-09-09
https://github.com/anthropics/claude-code/issues/94579 | github_issue: Auto Mode's destructive-action classifier misses remote/SSH commands with real production blast radius | 2026-09-15
https://github.com/anthropics/claude-code/issues/95426 | github_issue: Claude Code deleted ~600GB: unprompted `rm -rf` on a substitution that resolved to a drive root | 2026-09-18
https://github.com/anthropics/claude-code/issues/96300 | github_issue: Dangerous-rm check does not look inside `sh -c` / `bash -c` | 2026-09-23
https://github.com/anthropics/claude-code/issues/97013 | github_issue: git index written (git rm --cached) despite a standing ban on git write operations | 2026-09-25
https://github.com/anthropics/claude-code/issues/97660 | github_issue: [BUG] Subagent ran rm -rf \ via PowerShell → MSYS2 bash (PowerShell expanded the escaped variables to empty), wiping C:\ top-down on Windows | 2026-09-27
https://forum.cursor.com/t/173688 | cursor_forum_thread: Errible: AI out of control, randomly deleting files, 6-month project wiped out | 2026-10-03
https://github.com/anthropics/claude-code/issues/99198 | github_issue: [CRITICAL] Sub-agent ran `rm -rf` on the user's Windows home directory (via 8.3 short name), no hard guard; delete kept running after the task was sto | 2026-10-03
https://github.com/microsoft/vscode/issues/272849 | github_issue: GitHub Copilot lacks Codespaces environment awareness leading to incorrect Git authentication guidance | 2025-10-23
https://news.ycombinator.com/item?id=47569157 | hacker_news_comment: HN comment by jeswin on "Claude Code runs Git reset --hard origin/main against project repo every 10 mins" | 2026-03-30
https://github.com/anthropics/claude-code/issues/69612 | github_issue: [DOCS] Auto mode docs omit v2.1.183 destructive git, amend, and destroy safeguards | 2026-06-19
https://github.com/anthropics/claude-code/issues/70843 | github_issue: [Bug][harness] Auto mode classifier blocks routine sync of a stale local clone to its remote tracking branch | 2026-06-25
https://github.com/anthropics/claude-code/issues/77254 | github_issue: [BUG] Auto-mode classifier: false positive on an org-distributed skill's sanctioned command, with no org-level channel to vouch for it | 2026-07-13
https://github.com/anthropics/claude-code/issues/81834 | github_issue: permissions.ask is silently skipped for git when the command is prefixed with `cd <other-dir> &&` | 2026-07-28
https://www.jpaul.me/2026/08/the-workflow-revert-reset-recovery/ | blog_post: Your AI Just Force-Pushed Over a Day of Work. Now What? | 2026-08-06

# CONSULTED, NOT USED AS AN INCIDENT (date read 2026-10-14)
https://github.com/anthropics/claude-code/issues/40710 | github_issue: "My automated tool is running git reset --hard origin/main in my project every 10 minutes" (HN item 47567969, 251 points). EXCLUDED: reporter later found the cause was his own GitPython test tool, not Claude Code (per https://lilting.ch/en/articles/claude-code-git-reset-hard-false-report, Mar 30 2026). Kept out of the set as a false attribution; the retraction comment on the issue was not opened by me, only the lilting.ch summary | 2026-03-29
https://news.ycombinator.com/item?id=47567969 | hacker_news_thread: source of the HN comment 47569157 used for SAFE-entry git revert, and of the CLAUDE.md rule text | 2026-03-29
https://lilting.ch/en/articles/claude-code-git-reset-hard-false-report | blog_post: explains the 40710 retraction | 2026-03-30
https://anuraag2601.github.io/gemini_cli_disaster.html | blog_post: primary account of the July 2025 Gemini CLI mkdir/move data loss (HN item 44651485). Page now returns GitHub Pages 404, so NOT usable; the mkdir/move commands are quoted only second-hand in HN comments and were not recorded | 2026-10-14 (404)
https://pydevtools.com/handbook/how-to/how-to-stop-ai-agents-from-bypassing-pre-commit-hooks/ | blog_post: how-to on blocking --no-verify; read for context, nothing recorded from it | undated
https://alexeyondata.substack.com/p/how-i-dropped-our-production-database | blog_post: DataTalks.Club terraform destroy post-mortem (used as INC record above) | 2026-03-06
https://forum.cursor.com/t/cursor-yolo-deleted-everything-in-my-computer/103131 | cursor_forum_thread: user says Cursor YOLO mode deleted everything and that git reset --hard was on his prohibited list. No agent-run command is quoted, so NOT recorded | 2025-06-12
https://forum.cursor.com/t/cursor-ai-agent-used-rm-rf-to-delete-files-from-a-parallel-subdirectory/44742 | cursor_forum_thread: rm -rf incident, no command text quoted, NOT recorded | 2025-01-25
https://forum.cursor.com/t/agent-parallel-subagents-overwrite-dirty-worktree-destructive-git-recovery-wastes-tokens/166666 | cursor_forum_thread: git reset --hard / git clean "were reported", no command quoted, NOT recorded | 2026-07-25
https://forum.cursor.com/t/cursor-ide-silently-runs-git-stash-git-reset-head-during-active-agent-session-all-uncommitted-changes-lost/156146 | cursor_forum_thread: stash + reset HEAD; no agent-issued command text, NOT recorded | 2026-03-28
https://www.reddit.com/r/google_antigravity/comments/1p82or6/ | reddit_post (also HN 46092302/46103532): used as the Antigravity record (UNVERIFIED). HN commenters reconstruct "rmdir /s /q D:\ETSY 2025\Antigravity Projects\Image Selector\client\node_modules.vite" but that is a reconstruction, not recorded | 2025-11-27
https://www.jpaul.me/2026/08/the-workflow-revert-reset-recovery/ | blog_post: used for SAFE entries | 2026-08-06
Replit/SaaStr (Jul 2025), Amazon Q wiper prompt (Jul 2025): searched (eWeek, The Register, BleepingComputer) but no verbatim command in a source I opened; NOT recorded.
PullPush (api.pullpush.io): worked for one id lookup; keyword searches returned noise or HTTP "Rate limit exceeded"; no Reddit incident other than the Antigravity post was usable.
GitHub search API is capped at 30 requests/min; queries were paced; GitHub search is lexical so recall for any one phrase is partial.
