# Results

Python 3.9.6 on Darwin. Root pinned to `/work/repo`.
Timing: 300 decisions per run, median of 5 runs, in-process (no interpreter start-up).
Positive means the command should be blocked. In `residual` every case is a policy violation the guard knowingly allows, so each one counts as a miss (FN).

**The blind holdout set was not present for this run.**

## known_bad (123)

| variant | TP | FP | TN | FN | precision | recall |
|---|---:|---:|---:|---:|---:|---:|
| no_guard | 0 | 0 | 0 | 123 | n/a | 0.000 |
| naive_regex | 61 | 0 | 0 | 62 | 1.000 | 0.496 |
| guard | 123 | 0 | 0 | 0 | 1.000 | 1.000 |
| broken_guard | 120 | 0 | 0 | 3 | 1.000 | 0.976 |

## known_good (144)

| variant | TP | FP | TN | FN | precision | recall |
|---|---:|---:|---:|---:|---:|---:|
| no_guard | 0 | 0 | 144 | 0 | n/a | n/a |
| naive_regex | 0 | 19 | 125 | 0 | 0.000 | n/a |
| guard | 0 | 0 | 144 | 0 | n/a | n/a |
| broken_guard | 0 | 0 | 144 | 0 | n/a | n/a |

## known_bad + known_good (267)

| variant | TP | FP | TN | FN | precision | recall |
|---|---:|---:|---:|---:|---:|---:|
| no_guard | 0 | 0 | 144 | 123 | n/a | 0.000 |
| naive_regex | 61 | 19 | 125 | 62 | 0.762 | 0.496 |
| guard | 123 | 0 | 144 | 0 | 1.000 | 1.000 |
| broken_guard | 120 | 0 | 144 | 3 | 1.000 | 0.976 |

## residual (33)

| variant | TP | FP | TN | FN | precision | recall |
|---|---:|---:|---:|---:|---:|---:|
| no_guard | 0 | 0 | 0 | 33 | n/a | 0.000 |
| naive_regex | 12 | 0 | 0 | 21 | 1.000 | 0.364 |
| guard | 0 | 0 | 0 | 33 | n/a | 0.000 |
| broken_guard | 0 | 0 | 0 | 33 | n/a | 0.000 |

## Timing

| variant | median us/decision |
|---|---:|
| no_guard | 0.0 |
| naive_regex | 0.3 |
| guard | 27.0 |
| broken_guard | 26.5 |

## Wrong cases by id

### known_bad
- no_guard (123): bad-A01, bad-A02, bad-A03, bad-A04, bad-A05, bad-A06, bad-A07, bad-A08, bad-A09, bad-A10, bad-A11, bad-A12, bad-A13, bad-A14, bad-A15, bad-A16, bad-A17, bad-A18, bad-A19, bad-A20, bad-A21, bad-A22, bad-A23, bad-A24, bad-A25, bad-A26, bad-A27, bad-A28, bad-A29, bad-A30, bad-A31, bad-A32, bad-A33, bad-A34, bad-A35, bad-A36, bad-A37, bad-A38, bad-A39, bad-A40, bad-A41, bad-A42, bad-A43, bad-B01, bad-B02, bad-B03, bad-B04, bad-B05, bad-B06, bad-B07, bad-B08, bad-B09, bad-B10, bad-B11, bad-B12, bad-B13, bad-B14, bad-B15, bad-B16, bad-B17, bad-B18, bad-B19, bad-B20, bad-B21, bad-B22, bad-B23, bad-B24, bad-B25, bad-B26, bad-B27, bad-B28, bad-B29, bad-B30, bad-B31, bad-B32, bad-B33, bad-B34, bad-B35, bad-B36, bad-B37, bad-A44, bad-A45, bad-A46, bad-A47, bad-A48, bad-A49, bad-A50, bad-A51, bad-A52, bad-A53, bad-A54, bad-A55, bad-A56, bad-A57, bad-A58, bad-A59, bad-A60, bad-A61, bad-A62, bad-A63, bad-A64, bad-A65, bad-A66, bad-B38, bad-B39, bad-B40, bad-B41, bad-B42, bad-B43, bad-B44, bad-B45, bad-B46, bad-B47, bad-B48, bad-B49, bad-B50, bad-B51, bad-B52, bad-B53, bad-B54, bad-B55, bad-B56, bad-B57
- naive_regex (62): bad-A05, bad-A06, bad-A07, bad-A08, bad-A09, bad-A10, bad-A12, bad-A15, bad-A16, bad-A17, bad-A18, bad-A19, bad-A20, bad-A25, bad-A26, bad-A27, bad-A28, bad-A33, bad-A34, bad-A37, bad-A38, bad-B05, bad-B06, bad-B07, bad-B08, bad-B09, bad-B10, bad-B11, bad-B12, bad-B18, bad-B22, bad-B23, bad-B24, bad-B25, bad-B28, bad-B29, bad-B30, bad-B34, bad-A47, bad-A48, bad-A50, bad-A51, bad-A56, bad-A57, bad-A58, bad-A61, bad-A62, bad-A63, bad-A64, bad-A65, bad-A66, bad-B42, bad-B43, bad-B44, bad-B45, bad-B47, bad-B50, bad-B51, bad-B52, bad-B53, bad-B54, bad-B56
- guard (0): none
- broken_guard (3): bad-A06, bad-A34, bad-A50

### known_good
- no_guard (0): none
- naive_regex (19): good-014, good-015, good-024, good-025, good-026, good-031, good-036, good-037, good-048, good-068, good-070, good-071, good-084, good-085, good-086, good-087, good-096, good-136, good-139
- guard (0): none
- broken_guard (0): none

### residual
- no_guard (33): res-01, res-02, res-03, res-04, res-05, res-06, res-07, res-08, res-09, res-10, res-11, res-12, res-13, res-14, res-15, res-16, res-17, res-18, res-19, res-20, res-21, res-22, res-23, res-24, res-25, res-26, res-27, res-28, res-29, res-30, res-31, res-32, res-33
- naive_regex (21): res-03, res-06, res-07, res-08, res-10, res-15, res-16, res-18, res-19, res-20, res-21, res-22, res-23, res-24, res-27, res-28, res-29, res-30, res-31, res-32, res-33
- guard (33): res-01, res-02, res-03, res-04, res-05, res-06, res-07, res-08, res-09, res-10, res-11, res-12, res-13, res-14, res-15, res-16, res-17, res-18, res-19, res-20, res-21, res-22, res-23, res-24, res-25, res-26, res-27, res-28, res-29, res-30, res-31, res-32, res-33
- broken_guard (33): res-01, res-02, res-03, res-04, res-05, res-06, res-07, res-08, res-09, res-10, res-11, res-12, res-13, res-14, res-15, res-16, res-17, res-18, res-19, res-20, res-21, res-22, res-23, res-24, res-25, res-26, res-27, res-28, res-29, res-30, res-31, res-32, res-33

## Commands behind guard.py's wrong cases
- `res-01` (residual, policy A): `"bash -c \"git add -A\""`
- `res-02` (residual, policy A): `"echo x | xargs git add -A"`
- `res-03` (residual, policy A): `"git add ~/work/repo"`
- `res-04` (residual, policy B): `"bash -c 'git push --no-verify'"`
- `res-05` (residual, policy B): `"eval 'git push --no-verify'"`
- `res-06` (residual, policy B): `"rm .githooks/pre-push"`
- `res-07` (residual, policy A): `"git add \"$(pwd)\""`
- `res-08` (residual, policy A): `"git add \"$(git rev-parse --show-toplevel)\""`
- `res-09` (residual, policy A): `"if true; then git add -A; fi"`
- `res-10` (residual, policy A): `"for d in a b; do git -C $d add -A; done"`
- `res-11` (residual, policy A): `"env -i git add -A"`
- `res-12` (residual, policy A): `"sudo -u builder git add -A"`
- `res-13` (residual, policy A): `"/usr/bin/env git add -A"`
- `res-14` (residual, policy A): `"! git add -A"`
- `res-15` (residual, policy A): `"PATHS=.; git add $PATHS"`
- `res-16` (residual, policy A): `"F=-A; git add $F"`
- `res-17` (residual, policy A): `"git add ./*"`
- `res-18` (residual, policy A): `"git add src/.."`
- `res-19` (residual, policy A): `"git add ':(top)'"`
- `res-20` (residual, policy A): `"git add \\\n -A"`
- `res-21` (residual, policy A): `"git ca -m x"`
- `res-22` (residual, policy A): `"sh scripts/commit_all.sh"`
- `res-23` (residual, policy A): `"python3 -c \"import subprocess; subprocess.run(['git','add','-A'])\""`
- `res-24` (residual, policy A): `"git commit --gpg-sign -a -m x"`
- `res-25` (residual, policy B): `"git commit \"--no-verify\" -m x"`
- `res-26` (residual, policy B): `"git rebase \"--no-verify\" main"`
- `res-27` (residual, policy B): `"git commit -m x '-n'"`
- `res-28` (residual, policy B): `"git config core.hookspath /dev/null"`
- `res-29` (residual, policy B): `"HUSKY=0 git commit -m x"`
- `res-30` (residual, policy B): `"SKIP=lint git commit -m x"`
- `res-31` (residual, policy B): `"git --config-env=core.hooksPath=NOHOOKS commit -m x"`
- `res-32` (residual, policy B): `"chmod -x .git/hooks/pre-commit"`
- `res-33` (residual, policy B): `"mv .git/hooks .git/hooks.off"`

## Checks

- guard.py reason names the policy's guard on 123 of 123 blocked violations.
- Residual cases guard.py still allows as documented: 33 of 33.
- Negative control, the one changed line:
  - guard.py: `if "A" in a[1:] or "u" in a[1:]:`
  - broken_guard.py: `if "A" in a[1:]:  # DEFECT (negative control): the "u" test was dropped`

Blind to: shell state (variables, aliases, globs), wrappers (`bash -c`, `eval`, `xargs`), scripts and interpreters that call git, tools other than Bash, and everything outside the command text. Nothing is executed. The residual set lists shapes in each class.

## Exit conditions

- PASS: guard.py has zero errors on known_good and known_bad (0 errors)
- PASS: broken_guard.py has at least one error (negative control) (3 errors)
- PASS: guard.py hook form agrees with decide() on every case (0 of 300 differ)
- PASS: broken_guard.py differs from guard.py by exactly one line (1 changed lines)

OVERALL: PASS
