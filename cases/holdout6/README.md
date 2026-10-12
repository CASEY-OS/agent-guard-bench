# agent-guard-bench holdout 6: writer output

Blind writer output from WRITER_SHEET.md only. No file under agent-guard-bench was opened.

## cases.jsonl

- Total: 116 (expect stop 75, allow 41)
- By policy: A stop 23, B stop 22, C stop 30, allow (policy none) 41
- By class (count each): amend-no-flags 1, bash-c-read-only 1, branch-force-delete-xargs 1, branch-force-move 1, branch-rename-force 1, branch-safe-delete 1, checkout-force 1, checkout-force-here-string 1, checkout-new-branch 1, clean-dry-run 1, clean-force-under-eval-single 1, clean-force-under-sudo 1, clean-force-via-function 1, clean-force-via-process-substitution 1, clean-force-via-python-list 1, clean-force-via-sh-here-string 1, comment-with-forbidden-text 1, commit-all-escaped-flag-short 1, commit-all-under-sh-c 1, commit-all-via-backticks 1, commit-message-contains-force 1, commit-message-from-file 1, commit-message-heredoc 1, commit-staged-only 1, delete-dot-git 1, discard-all-worktree 1, echo-forbidden-text 1, force-push-plus-refspec 1, force-push-under-bash-c 1, force-push-under-sh-c 1, force-push-under-timeout 1, force-push-via-process-substitution 1, gc-plain 1, hard-reset-via-config-alias 1, hook-bypass-plumbing-commit 1, hook-content-edit-by-name 1, hook-file-delete-find 1, hook-file-delete-git-dir 1, hook-file-delete-githooks 1, hook-file-delete-in-subshell 1, hook-file-delete-multiline 1, hook-file-delete-node 1, hook-file-delete-piped-to-sh 1, hook-file-delete-via-heredoc-script 1, hook-file-unexecute 1, hook-manager-env-off 1, hook-read 1, hooks-skip-chain 1, hooks-skip-push 1, hooks-skip-under-eval-quoted 1, hooks-skip-via-function 1, hookspath-env-override 1, hookspath-global-null 1, hookspath-override-flag 1, hookspath-read 1, hookspath-redirect-elsewhere 1, hookspath-redirect-null 1, hookspath-to-githooks 1, hookspath-under-bash-c 1, hookspath-unset 1, log-grep-flag-text 1, merge-normal 1, push-dry-run 1, push-normal 1, push-upstream-set 1, rebase-onto-branch 1, remote-branch-delete 1, remove-build-output 1, remove-dependency-dir 1, remove-whole-tree 1, reset-hard-escaped-flag 1, reset-hard-in-subshell 1, reset-hard-to-cmdsub-target 1, reset-hard-under-bash-c 1, reset-hard-via-backticks 1, reset-hard-via-function 1, reset-hard-via-ifs-split 1, reset-soft 1, reset-soft-flag-order 1, restore-named-file 1, stage-all-in-chain 1, stage-all-in-heredoc 1, stage-all-in-subshell-cd 1, stage-all-piped-to-sh 1, stage-all-tracked-via-xargs 1, stage-all-under-env 1, stage-all-under-eval-quoted 1, stage-all-under-sh-c 1, stage-all-under-sudo 1, stage-all-untracked-via-plumbing 1, stage-all-untracked-via-plumbing-herestring 1, stage-all-untracked-via-xargs 1, stage-all-via-backticks-echo 1, stage-all-via-git-config-alias 1, stage-all-via-ifs-comma 1, stage-all-via-ifs-split 1, stage-all-via-perl 1, stage-all-via-process-substitution-input 1, stage-escaped-dot 1, stage-interactive-named 1, stage-named-directory 1, stage-named-file 1, stage-named-file-all-txt 1, stage-root-via-pwd 1, stash-clear 1, stash-drop 1, stash-pop 1, stash-push 1, stash-show 1, switch-discard 1, switch-plain 1, tag-delete-local 1, unstage-named-file 1, untrack-named-file 1, worktree-remove-clean 1, write-forbidden-text-to-file 1
- Shell families: every family in the sheet appears at least three times among stop cases (checked by regex over command text, approximate).

## undo_cases.jsonl

- Total: 26 (restore 21, residual 5)
- Classes: hard-reset, clean-untracked, checkout-force, stash-clear, stash-drop, branch-force-delete, branch-force-move, force-push-remote, remote-branch-delete, remove-tracked-dir, merge-with-conflict, rebase-rewrite, stage-everything, untrack-dir, amend-head, discard-unstaged-edit, mode-bit-change, binary-truncate, annotated-tag-delete, delete-dot-git, symlink-retarget, mtime-only-change, xattr-change, ignored-and-outside-files, nested-repo-create, remote-fetch-prune

## sha256 (shasum -a 256)

- cases.jsonl: 9340c707127f1018b9a69800fb14805e0f512b2ecd824797ee22187432ef4b28
- undo_cases.jsonl: bfe07094b91d98858e30b155739fb7566e79a886c734a87c4abff0912f82a050

## Verification

- No throwaway-repo checks were completed: a sandbox guard blocked the verification command, so effects are stated from the sheet's definitions, not run.

## Unsure ids

- cases: H6-096, H6-101 (branch -D may not be unmerged in the fixture; depends on fixture branch state)
- undo: H6-U08, H6-U09, H6-U11, H6-U20, H6-U21 (restore vs residual depends on whether the bench treats the remote push, .git deletion, merge conflict stages and symlink retarget as in scope)
