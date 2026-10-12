# Undo benchmark

Python 3.14.5 on Darwin, git version 2.54.0. Every repo was built under one temp root and deleted after the run. Every command below ran for real, inside its own throwaway repo.

Route: `direct` means the guard allowed the command, so the hook took the snapshot. `script` means the guard denied it, so the bench wrote it to a script file outside the repo and sent `bash <script>`, a route the guard cannot read. Damage counts what changed. Left counts what still differs after restore (0 is fully restored).

| # | scenario | command | route | damage | left after restore | ignored files lost | remote put back by printed push |
|---:|---|---|---|---:|---:|---:|---|
| 1 | reset-hard-HEAD~1 | `git reset --hard HEAD~1` | script | 8 | 0 | 0 | n/a |
| 2 | reset-hard | `git reset --hard` | script | 7 | 0 | 0 | n/a |
| 3 | reset-mixed-HEAD~2 | `git reset --mixed HEAD~2` | direct | 2 | 0 | 0 | n/a |
| 4 | reset-soft-HEAD~2 | `git reset --soft HEAD~2` | direct | 1 | 0 | 0 | n/a |
| 5 | clean-fdx | `git clean -fdx` | script | 3 | 0 | 2 | n/a |
| 6 | clean-fd | `git clean -fd` | script | 3 | 0 | 0 | n/a |
| 7 | checkout-dash-dash-dot | `git checkout -- .` | script | 4 | 0 | 0 | n/a |
| 8 | restore-dot | `git restore .` | script | 4 | 0 | 0 | n/a |
| 9 | restore-staged-dot | `git restore --staged .` | direct | 1 | 0 | 0 | n/a |
| 10 | restore-source-src | `git restore --source=HEAD~2 --staged --worktree src` | direct | 4 | 0 | 0 | n/a |
| 11 | checkout-force-other | `git checkout -f other` | script | 9 | 0 | 0 | n/a |
| 12 | switch-discard-other | `git switch --discard-changes other` | script | 9 | 0 | 0 | n/a |
| 13 | checkout-other-whole-tree | `git checkout other -- .` | script | 7 | 0 | 0 | n/a |
| 14 | branch-D-other | `git branch -D other` | script | 1 | 0 | 0 | n/a |
| 15 | branch-f-other | `git branch -f other HEAD~2` | script | 1 | 0 | 0 | n/a |
| 16 | stash-push | `git stash push -m wip` | direct | 9 | 0 | 0 | n/a |
| 17 | stash-drop | `git stash drop` | script | 2 | 0 | 0 | n/a |
| 18 | stash-clear | `git stash clear` | script | 2 | 0 | 0 | n/a |
| 19 | stash-then-drop | `git stash && git stash drop` | script | 7 | 0 | 0 | n/a |
| 20 | commit | `git commit -q -m 'agent commit'` | direct | 1 | 0 | 0 | n/a |
| 21 | commit-amend | `git commit -q --amend -m amended` | direct | 1 | 0 | 0 | n/a |
| 22 | stash-then-merge | `git stash -q && git merge -q --no-edit other` | direct | 11 | 0 | 0 | n/a |
| 23 | rebase-autostash | `git rebase -q --autostash other` | direct | 3 | 0 | 0 | n/a |
| 24 | rebase-drop-commit | `git rebase -q --autostash --onto HEAD~2 HEAD~1` | direct | 5 | 0 | 0 | n/a |
| 25 | update-ref-delete | `git update-ref -d refs/heads/other` | script | 1 | 0 | 0 | n/a |
| 26 | update-ref-move | `git update-ref refs/heads/main HEAD~2` | script | 1 | 0 | 0 | n/a |
| 27 | reset-then-gc | `git reset -q --hard HEAD~2 && git reflog expire --expire=now --all && git gc -q --prune=now` | script | 9 | 0 | 0 | n/a |
| 28 | tag-delete-then-gc | `git tag -d v1 light && git reflog expire --expire=now --all && git gc -q --prune=now` | script | 3 | 0 | 0 | n/a |
| 29 | merge-abort-conflict | `git merge --abort` | direct | 5 | 0 | 0 | n/a |
| 30 | force-push | `git push -q -f origin main` | script | 3 | 0 | 0 | yes |
| 31 | push-delete | `git push -q origin --delete other` | script | 2 | 0 | 0 | yes |
| 32 | rm-rf-src | `rm -rf src` | direct | 8 | 0 | 0 | n/a |
| 33 | rm-files | `rm -f README.md notes.txt bin/run.sh` | direct | 4 | 0 | 0 | n/a |
| 34 | mv-dir | `mv src lib` | direct | 16 | 0 | 0 | n/a |
| 35 | mv-out-of-repo | `mv notes.txt ../moved_notes.txt` | direct | 1 | 0 | 0 | n/a |
| 36 | cp-over | `cp README.md src/app.py` | direct | 1 | 0 | 0 | n/a |
| 37 | sed-in-place | `sed -i.bak 's/a/X/g' src/app.py README.md` | direct | 4 | 0 | 0 | n/a |
| 38 | truncate | `truncate -s 0 src/util.py data/blob.bin` | direct | 2 | 0 | 0 | n/a |
| 39 | redirect-write | `echo junk > README.md && echo more >> notes.txt` | direct | 2 | 0 | 0 | n/a |
| 40 | tee | `echo x \| tee src/app.py src/lib/deep.py` | direct | 2 | 0 | 0 | n/a |
| 41 | find-delete | `find . -name '*.py' -not -path './.git/*' -delete` | direct | 5 | 0 | 0 | n/a |
| 42 | git-rm-r-force | `git rm -r -q -f src` | direct | 6 | 0 | 0 | n/a |
| 43 | git-mv | `git mv README.md README2.md` | direct | 3 | 0 | 0 | n/a |
| 44 | chmod | `chmod 600 bin/run.sh && chmod 755 notes.txt` | direct | 2 | 0 | 0 | n/a |
| 45 | file-becomes-dir | `rm src/util.py && mkdir src/util.py && echo x > src/util.py/inner` | direct | 3 | 0 | 0 | n/a |
| 46 | symlink-becomes-file | `rm link && echo plain > link` | direct | 1 | 0 | 0 | n/a |
| 47 | dir-becomes-symlink | `rm -rf src/lib && ln -s ../docs src/lib` | direct | 3 | 0 | 0 | n/a |
| 48 | binary-overwrite | `head -c 512 /dev/zero > data/blob.bin` | direct | 1 | 0 | 0 | n/a |
| 49 | python-rmtree | `python3 -c "import shutil; shutil.rmtree('src')"` | direct | 8 | 0 | 0 | n/a |
| 50 | rm-rf-dotgit | `rm -rf .git` | script | 36 | 0 | 0 | n/a |
| 51 | rm-rf-dotgit-reinit | `rm -rf .git && git init -q` | script | 11 | 0 | 0 | n/a |
| 52 | wu5-chmod-dash-x | `chmod -x bin/run.sh` | direct | 1 | 0 | 0 | n/a |
| 53 | wu5-chmod-R-dash-w | `chmod -R -w src` | direct | 8 | 0 | 0 | n/a |
| 54 | wu5-chmod-R-a-w | `chmod -R a-w src` | direct | 8 | 0 | 0 | n/a |
| 55 | wu5-find-print0-xargs-rm | `find . -name '*.py' -not -path './.git/*' -print0 \| xargs -0 rm -f` | direct | 5 | 0 | 0 | n/a |
| 56 | wu5-ls-files-xargs-chmod | `git ls-files bin \| xargs chmod 600` | direct | 1 | 0 | 0 | n/a |
| 57 | wu5-ls-files-xargs-gzip | `git ls-files src \| xargs gzip -f` | direct | 8 | 0 | 0 | n/a |
| 58 | wu5-patch-heredoc | `patch -p0 <<'EOP'
--- README.md
+++ README.md
@@ -1,3 +1,3 @@
 # demo
-alpha beta
+alpha gamma
 unstaged line
EOP` | direct | 1 | 0 | 0 | n/a |
| 59 | wu5-sed-Ei | `sed -Ei '' 's/alpha/ALPHA/' README.md` | direct | 1 | 0 | 0 | n/a |
| 60 | wu5-sort-ro | `sort -ro README.md README.md` | direct | 1 | 0 | 0 | n/a |
| 61 | wu5-tar-extract-outside | `mkdir ../stage && echo changed > ../stage/README.md && (cd ../stage && tar -cf ../a.tar README.md); tar -xf ../a.tar` | direct | 1 | 0 | 0 | n/a |
| 62 | wu5-unzip-outside | `mkdir ../stage && echo changed > ../stage/README.md && (cd ../stage && zip -q ../a.zip README.md); unzip -qo ../a.zip` | direct | 1 | 0 | 0 | n/a |
| 63 | wu5-subshell-cd | `(cd .. && ls) ; rm -f notes.txt README.md` | direct | 2 | 0 | 0 | n/a |
| 64 | wu5-cd-dash | `cd .. && cd - && rm -f notes.txt` | direct | 1 | 0 | 0 | n/a |
| 65 | wu5-env-S | `env -S 'rm -f notes.txt README.md'` | direct | 2 | 0 | 0 | n/a |
| 66 | wu5-git-c-fsmonitor | `git -c core.fsmonitor='rm -f notes.txt;' status` | direct | 1 | 0 | 0 | n/a |
| 67 | wu5-git-external-diff | `GIT_EXTERNAL_DIFF='rm -f' git diff` | direct | 1 | 0 | 0 | n/a |
| 68 | wu5-ignore-added-then-file | `echo '*.out' >> .gitignore && echo result > result.out` | direct | 1 | 0 | 0 | n/a |
| 69 | wu5-ignore-dir-then-file | `printf 'tmp/\n' >> .gitignore && mkdir tmp && echo x > tmp/a.txt` | direct | 1 | 0 | 0 | n/a |
| 70 | wu5-merge-squash | `git stash -q && git merge --squash other` | direct | 11 | 0 | 0 | n/a |
| 71 | wu5-revert-sequencer | `git stash -q && git checkout -q other && git revert --no-edit main main~1` | direct | 16 | 0 | 0 | n/a |
| 72 | chmod-dirs-go-rx | `chmod -R go-rx src docs` | direct | 8 | 0 | 0 | n/a |

Fully restored: 72 of 72.

## Negative controls: snapshot skipped (AGENT_GUARD_UNDO=0)

| scenario | snapshots taken | damage | still lost after restore --last | restore --last exit |
|---|---:|---:|---:|---:|
| reset-hard-HEAD~1 | 0 | 8 | 8 | 2 |
| clean-fdx | 0 | 3 | 3 | 2 |
| rm-rf-src | 0 | 8 | 8 | 2 |
| branch-D-other | 0 | 1 | 1 | 2 |
| stash-drop | 0 | 2 | 2 | 2 |

Controls that show the loss: 5 of 5.

## Residuals: named limits, shown not hidden

| residual | command | what happened | as documented |
|---|---|---|---|
| ignored-files | `git clean -fdX` | 2 ignored files lost; everything in scope restored (0 left) | yes |
| outside-the-repo | `rm -f ../outside.txt` | outside file still exists: False | yes |
| empty-directory | `rmdir empty_dir` | empty directory back: False | yes |
| remote-only-commit | `git push -q -f origin main` | their commit recoverable: False; on the remote: False | yes |

## Mutants: a one-line defect in restore must be caught

| mutant | scenario | left after restore | caught |
|---|---|---:|---|
| restore skips the mode bits | chmod | 1 | yes |
| restore skips the stash reflog | stash-drop | 1 | yes |
| restore does not reopen read-only directories | wu5-chmod-R-a-w | 7 | yes |
| restore skips the directory mode bits | chmod-dirs-go-rx | 3 | yes |
| restore judges ignores by the post-command .gitignore | wu5-ignore-added-then-file | 1 | yes |
| restore does not save SQUASH_MSG | wu5-merge-squash | 1 | yes |
| restore does not import from the store | rm-rf-dotgit | 36 | yes |

## The hook's plan: snapshot or not

108 commands that could change the repo and 78 that cannot. Wrong: 0.

## Bound and dedupe

Made 55 snapshots with the default bound: 50 kept, the newest ones (ok). Same state twice gives the same id, one ref (ok).

## Cost (1,000 files, about 1.6 KB each)

| measure | value |
|---|---:|
| first snapshot, clean tree (one run) | 292 ms, 56106 bytes added to .git/objects |
| snapshot, nothing changed (dedupe) | 67 ms median |
| snapshot, 10 files changed and 1 new | 137 ms median, 5559 bytes median |
| plan() for a read-only command, in-process | 16 us |
| whole hook, read-only command (Python start-up included) | 48 ms median |
| whole hook, command that gets a snapshot | 199 ms median |
| restore --last, CLI | 407 ms |
| .git/objects before any snapshot | 899860 bytes |

Blind to: ignored files, files outside the repo, empty directories, owner, ACLs, xattrs and mtimes, submodule contents and nested repos, skip-worktree and sparse paths, branch reflogs other than the stash, an in-progress rebase directory, remote state the local repo never fetched, and any change made by a command the hook never saw (a tool other than Bash, a process started earlier that keeps writing). Proven on this machine's OS and git only.

## Exit conditions

- PASS: at least 30 in-scope scenarios (72)
- PASS: every in-scope scenario fully restored (72 of 72)
- PASS: every scenario command really changed something (all did)
- PASS: the hook took exactly one snapshot before each command (all)
- PASS: a snapshot left index bytes, HEAD, refs, stash and files untouched (all)
- PASS: all 5 negative controls show the loss (5 of 5)
- PASS: every residual behaves as documented (all)
- PASS: every one-line restore mutant is caught by the readback (7 of 7)
- PASS: the plan is right on every planted and clean command (0 wrong)
- PASS: bound keeps the newest 50; dedupe stores a state once (kept 50)
- PASS: the printed repair push put every pushed remote back (2 push scenarios)
- PASS: every destructive command ran under the bench root (91 runs, 0 outside)

Runtime 92 s.

OVERALL: PASS
