# agent-guard-bench holdout 10: writer output

Blind writer output, built only from WRITER_SHEET.md. No agent-guard-bench folder was opened.
Claims were checked only in a throwaway git repo under mktemp -d (one check: git refuses `git branch -f` on the checked-out branch, rc 128).

## cases.jsonl (guard cases, prefix K10-)
- Total: 100
- By expect: allow=40, stop=60
- By policy: A=20, B=20, C=20, none=40
- By class: alias-sweep=1, comment-with-forbidden-text=1, commit-all=2, discard-all-worktree=2, dry-run=1, eval-wrapped=1, exclude-only-pathspec=1, force-branch-delete=1, force-branch-move=1, force-push=2, forced-checkout=2, forced-clean=1, forced-worktree-remove=1, gc-allowed=1, glob-whole-tree=1, hard-reset=4, hook-file-delete=2, hook-file-move=1, hook-file-unexecute=1, hook-manager-env-off=3, hook-manager-uninstall=2, hook-read=3, hook-skip-flag=5, hookspath-allowed=1, hookspath-redirect=6, index-sweep=1, merge=1, mirror-push=1, named-restore=1, normal-fetch=2, normal-push=1, print-only=1, read-only=7, rebase-onto-branch=2, reflog-expire=1, remote-branch-delete=1, rm-dependencies=1, root-pathspec=2, safe-branch-ops=4, safe-named-stage=5, safe-unstage=2, scary-text-in-message=2, shell-wrapped=1, soft-reset=1, stage-all=7, stash-destroy=2, stash-push-pop=2, tracked-sweep=2, whole-tree-removal=1, worktree-add=1, wrapper-sweep=1

## undo_cases.jsonl (undo scenarios, prefix K10U)
- Total: 20
- By expect: residual=5, restore=15

## sha256 (taken before chmod)
- cases.jsonl: 906a46a55264f37df0caa667e82645b044b2d74e1468e5235bdd0a4f0a0024d8
- undo_cases.jsonl: 43d62e25d37024a3a8a13f8c40ae839d8daaec0cdc6e19a23a17bbf474a9e1d0

## Unsure ids
- Guard: K10-008 (exclude-only-pathspec), K10-010 (tracked-sweep), K10-032 (hook-manager-env-off), K10-036 (hookspath-redirect), K10-048 (force-branch-delete), K10-052 (reflog-expire), K10-055 (remote-branch-delete), K10-065 (safe-named-stage), K10-075 (stash-push-pop), K10-099 (gc-allowed), K10-100 (worktree-add). The force-delete of a possibly merged branch, the ambiguous `git add -u` and `:(exclude)` pathspec, `gc --auto`, and the global hooksPath write are judgement calls under the sheet.
- Undo: K10U12 (stash-then-rebase-multiline), K10U14 (rm-untracked-file), K10U16 (clean-x-ignored), K10U20 (reflog-expire-all). Restore scope for the reflog, the untracked-file delete and the rebase-with-stash is read from the sheet's listed scope, not verified against a live layer.
- Not checked against a live guard or undo layer; expectations come from the sheet text.
