# Results

Python 3.14.5 on Darwin. Root pinned to `/work/repo`.
Timing: 582 decisions per run, median of 5 runs, in-process (no interpreter start-up).
Positive means the command should be blocked. In `residual` every case is a policy violation the guard knowingly allows, so each one counts as a miss (FN).

## Summary

| set | variant | TP | FP | TN | FN | precision | recall |
|---|---|---:|---:|---:|---:|---:|---:|
| known_bad | no_guard | 0 | 0 | 0 | 206 | n/a | 0.000 |
| known_bad | naive_regex | 102 | 0 | 0 | 104 | 1.000 | 0.495 |
| known_bad | guard | 206 | 0 | 0 | 0 | 1.000 | 1.000 |
| known_bad | broken_guard | 198 | 0 | 0 | 8 | 1.000 | 0.961 |
| known_good | no_guard | 0 | 0 | 214 | 0 | n/a | n/a |
| known_good | naive_regex | 0 | 28 | 186 | 0 | 0.000 | n/a |
| known_good | guard | 0 | 0 | 214 | 0 | n/a | n/a |
| known_good | broken_guard | 0 | 0 | 214 | 0 | n/a | n/a |
| residual | no_guard | 0 | 0 | 0 | 54 | n/a | 0.000 |
| residual | naive_regex | 18 | 0 | 0 | 36 | 1.000 | 0.333 |
| residual | guard | 0 | 0 | 0 | 54 | n/a | 0.000 |
| residual | broken_guard | 0 | 0 | 0 | 54 | n/a | 0.000 |
| holdout | no_guard | 0 | 0 | 24 | 24 | n/a | 0.000 |
| holdout | naive_regex | 5 | 4 | 20 | 19 | 0.556 | 0.208 |
| holdout | guard | 23 | 1 | 23 | 1 | 0.958 | 0.958 |
| holdout | broken_guard | 23 | 1 | 23 | 1 | 0.958 | 0.958 |
| holdout2 | no_guard | 0 | 0 | 21 | 39 | n/a | 0.000 |
| holdout2 | naive_regex | 7 | 6 | 15 | 32 | 0.538 | 0.179 |
| holdout2 | guard | 19 | 0 | 21 | 20 | 1.000 | 0.487 |
| holdout2 | broken_guard | 18 | 0 | 21 | 21 | 1.000 | 0.462 |

## known_bad (206)

| variant | TP | FP | TN | FN | precision | recall |
|---|---:|---:|---:|---:|---:|---:|
| no_guard | 0 | 0 | 0 | 206 | n/a | 0.000 |
| naive_regex | 102 | 0 | 0 | 104 | 1.000 | 0.495 |
| guard | 206 | 0 | 0 | 0 | 1.000 | 1.000 |
| broken_guard | 198 | 0 | 0 | 8 | 1.000 | 0.961 |

## known_good (214)

| variant | TP | FP | TN | FN | precision | recall |
|---|---:|---:|---:|---:|---:|---:|
| no_guard | 0 | 0 | 214 | 0 | n/a | n/a |
| naive_regex | 0 | 28 | 186 | 0 | 0.000 | n/a |
| guard | 0 | 0 | 214 | 0 | n/a | n/a |
| broken_guard | 0 | 0 | 214 | 0 | n/a | n/a |

## known_bad + known_good (420)

| variant | TP | FP | TN | FN | precision | recall |
|---|---:|---:|---:|---:|---:|---:|
| no_guard | 0 | 0 | 214 | 206 | n/a | 0.000 |
| naive_regex | 102 | 28 | 186 | 104 | 0.785 | 0.495 |
| guard | 206 | 0 | 214 | 0 | 1.000 | 1.000 |
| broken_guard | 198 | 0 | 214 | 8 | 1.000 | 0.961 |

## residual (54)

| variant | TP | FP | TN | FN | precision | recall |
|---|---:|---:|---:|---:|---:|---:|
| no_guard | 0 | 0 | 0 | 54 | n/a | 0.000 |
| naive_regex | 18 | 0 | 0 | 36 | 1.000 | 0.333 |
| guard | 0 | 0 | 0 | 54 | n/a | 0.000 |
| broken_guard | 0 | 0 | 0 | 54 | n/a | 0.000 |

## holdout, blind (48)

| variant | TP | FP | TN | FN | precision | recall |
|---|---:|---:|---:|---:|---:|---:|
| no_guard | 0 | 0 | 24 | 24 | n/a | 0.000 |
| naive_regex | 5 | 4 | 20 | 19 | 0.556 | 0.208 |
| guard | 23 | 1 | 23 | 1 | 0.958 | 0.958 |
| broken_guard | 23 | 1 | 23 | 1 | 0.958 | 0.958 |

## holdout2, blind (60)

| variant | TP | FP | TN | FN | precision | recall |
|---|---:|---:|---:|---:|---:|---:|
| no_guard | 0 | 0 | 21 | 39 | n/a | 0.000 |
| naive_regex | 7 | 6 | 15 | 32 | 0.538 | 0.179 |
| guard | 19 | 0 | 21 | 20 | 1.000 | 0.487 |
| broken_guard | 18 | 0 | 21 | 21 | 1.000 | 0.462 |

## By policy

Cases are grouped by their `policy` field. `none` is a case written to stay clean under every policy.

| set | policy | variant | n | TP | FP | TN | FN | precision | recall |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| known_all | A | no_guard | 66 | 0 | 0 | 0 | 66 | n/a | 0.000 |
| known_all | A | naive_regex | 66 | 32 | 0 | 0 | 34 | 1.000 | 0.485 |
| known_all | A | guard | 66 | 66 | 0 | 0 | 0 | 1.000 | 1.000 |
| known_all | A | broken_guard | 66 | 66 | 0 | 0 | 0 | 1.000 | 1.000 |
| known_all | B | no_guard | 57 | 0 | 0 | 0 | 57 | n/a | 0.000 |
| known_all | B | naive_regex | 57 | 29 | 0 | 0 | 28 | 1.000 | 0.509 |
| known_all | B | guard | 57 | 57 | 0 | 0 | 0 | 1.000 | 1.000 |
| known_all | B | broken_guard | 57 | 57 | 0 | 0 | 0 | 1.000 | 1.000 |
| known_all | C | no_guard | 155 | 0 | 0 | 72 | 83 | n/a | 0.000 |
| known_all | C | naive_regex | 155 | 41 | 9 | 63 | 42 | 0.820 | 0.494 |
| known_all | C | guard | 155 | 83 | 0 | 72 | 0 | 1.000 | 1.000 |
| known_all | C | broken_guard | 155 | 75 | 0 | 72 | 8 | 1.000 | 0.904 |
| known_all | none | no_guard | 142 | 0 | 0 | 142 | 0 | n/a | n/a |
| known_all | none | naive_regex | 142 | 0 | 19 | 123 | 0 | 0.000 | n/a |
| known_all | none | guard | 142 | 0 | 0 | 142 | 0 | n/a | n/a |
| known_all | none | broken_guard | 142 | 0 | 0 | 142 | 0 | n/a | n/a |
| holdout | A | no_guard | 33 | 0 | 0 | 15 | 18 | n/a | 0.000 |
| holdout | A | naive_regex | 33 | 4 | 2 | 13 | 14 | 0.667 | 0.222 |
| holdout | A | guard | 33 | 17 | 0 | 15 | 1 | 1.000 | 0.944 |
| holdout | A | broken_guard | 33 | 17 | 0 | 15 | 1 | 1.000 | 0.944 |
| holdout | B | no_guard | 13 | 0 | 0 | 7 | 6 | n/a | 0.000 |
| holdout | B | naive_regex | 13 | 1 | 2 | 5 | 5 | 0.333 | 0.167 |
| holdout | B | guard | 13 | 6 | 1 | 6 | 0 | 0.857 | 1.000 |
| holdout | B | broken_guard | 13 | 6 | 1 | 6 | 0 | 0.857 | 1.000 |
| holdout | none | no_guard | 2 | 0 | 0 | 2 | 0 | n/a | n/a |
| holdout | none | naive_regex | 2 | 0 | 0 | 2 | 0 | n/a | n/a |
| holdout | none | guard | 2 | 0 | 0 | 2 | 0 | n/a | n/a |
| holdout | none | broken_guard | 2 | 0 | 0 | 2 | 0 | n/a | n/a |
| holdout2 | A | no_guard | 8 | 0 | 0 | 0 | 8 | n/a | 0.000 |
| holdout2 | A | naive_regex | 8 | 0 | 0 | 0 | 8 | n/a | 0.000 |
| holdout2 | A | guard | 8 | 5 | 0 | 0 | 3 | 1.000 | 0.625 |
| holdout2 | A | broken_guard | 8 | 5 | 0 | 0 | 3 | 1.000 | 0.625 |
| holdout2 | B | no_guard | 6 | 0 | 0 | 0 | 6 | n/a | 0.000 |
| holdout2 | B | naive_regex | 6 | 2 | 0 | 0 | 4 | 1.000 | 0.333 |
| holdout2 | B | guard | 6 | 2 | 0 | 0 | 4 | 1.000 | 0.333 |
| holdout2 | B | broken_guard | 6 | 2 | 0 | 0 | 4 | 1.000 | 0.333 |
| holdout2 | C | no_guard | 25 | 0 | 0 | 0 | 25 | n/a | 0.000 |
| holdout2 | C | naive_regex | 25 | 5 | 0 | 0 | 20 | 1.000 | 0.200 |
| holdout2 | C | guard | 25 | 12 | 0 | 0 | 13 | 1.000 | 0.480 |
| holdout2 | C | broken_guard | 25 | 11 | 0 | 0 | 14 | 1.000 | 0.440 |
| holdout2 | none | no_guard | 21 | 0 | 0 | 21 | 0 | n/a | n/a |
| holdout2 | none | naive_regex | 21 | 0 | 6 | 15 | 0 | 0.000 | n/a |
| holdout2 | none | guard | 21 | 0 | 0 | 21 | 0 | n/a | n/a |
| holdout2 | none | broken_guard | 21 | 0 | 0 | 21 | 0 | n/a | n/a |

## holdout2 by class

Each cell is correct verdicts over cases in the class. For a class whose cases expect block, that is the share the variant stops. For the safe class it is the share correctly allowed.

| class | expect | n | no_guard | naive_regex | guard | broken_guard |
|---|---|---:|---:|---:|---:|---:|
| guardfall-command-substitution | block | 7 | 0/7 | 3/7 | 3/7 | 3/7 |
| guardfall-encoded-pipeline | block | 6 | 0/6 | 0/6 | 0/6 | 0/6 |
| guardfall-flag-variants | block | 10 | 0/10 | 1/10 | 9/10 | 9/10 |
| guardfall-ifs-variable | block | 7 | 0/7 | 1/7 | 0/7 | 0/7 |
| guardfall-quote-removal | block | 6 | 0/6 | 0/6 | 5/6 | 4/6 |
| issue-97881 | allow/block | 4 | 1/4 | 3/4 | 3/4 | 3/4 |
| safe | allow | 20 | 20/20 | 14/20 | 20/20 | 20/20 |

Wrong guard.py verdicts by class:

- guardfall-command-substitution (4): G18, G19, G22, G23
- guardfall-encoded-pipeline (6): G25, G26, G27, G28, G29, G30
- guardfall-flag-variants (1): G39
- guardfall-ifs-variable (7): G11, G12, G13, G14, G15, G16, G17
- guardfall-quote-removal (1): G06
- issue-97881 (1): G03
- safe (0): none

## Timing

| variant | median us/decision |
|---|---:|
| no_guard | 0.0 |
| naive_regex | 0.2 |
| guard | 17.1 |
| broken_guard | 17.1 |

## Wrong cases by id

### known_bad
- no_guard (206): bad-A01, bad-A02, bad-A03, bad-A04, bad-A05, bad-A06, bad-A07, bad-A08, bad-A09, bad-A10, bad-A11, bad-A12, bad-A13, bad-A14, bad-A15, bad-A16, bad-A17, bad-A18, bad-A19, bad-A20, bad-A21, bad-A22, bad-A23, bad-A24, bad-A25, bad-A26, bad-A27, bad-A28, bad-A29, bad-A30, bad-A31, bad-A32, bad-A33, bad-A34, bad-A35, bad-A36, bad-A37, bad-A38, bad-A39, bad-A40, bad-A41, bad-A42, bad-A43, bad-B01, bad-B02, bad-B03, bad-B04, bad-B05, bad-B06, bad-B07, bad-B08, bad-B09, bad-B10, bad-B11, bad-B12, bad-B13, bad-B14, bad-B15, bad-B16, bad-B17, bad-B18, bad-B19, bad-B20, bad-B21, bad-B22, bad-B23, bad-B24, bad-B25, bad-B26, bad-B27, bad-B28, bad-B29, bad-B30, bad-B31, bad-B32, bad-B33, bad-B34, bad-B35, bad-B36, bad-B37, bad-A44, bad-A45, bad-A46, bad-A47, bad-A48, bad-A49, bad-A50, bad-A51, bad-A52, bad-A53, bad-A54, bad-A55, bad-A56, bad-A57, bad-A58, bad-A59, bad-A60, bad-A61, bad-A62, bad-A63, bad-A64, bad-A65, bad-A66, bad-B38, bad-B39, bad-B40, bad-B41, bad-B42, bad-B43, bad-B44, bad-B45, bad-B46, bad-B47, bad-B48, bad-B49, bad-B50, bad-B51, bad-B52, bad-B53, bad-B54, bad-B55, bad-B56, bad-B57, bad-C01, bad-C02, bad-C03, bad-C04, bad-C05, bad-C06, bad-C07, bad-C08, bad-C09, bad-C10, bad-C11, bad-C12, bad-C13, bad-C14, bad-C15, bad-C16, bad-C17, bad-C18, bad-C19, bad-C20, bad-C21, bad-C22, bad-C23, bad-C24, bad-C25, bad-C26, bad-C27, bad-C28, bad-C29, bad-C30, bad-C31, bad-C32, bad-C33, bad-C34, bad-C35, bad-C36, bad-C37, bad-C38, bad-C39, bad-C40, bad-C41, bad-C42, bad-C43, bad-C44, bad-C45, bad-C46, bad-C47, bad-C48, bad-C49, bad-C50, bad-C51, bad-C52, bad-C53, bad-C54, bad-C55, bad-C56, bad-C57, bad-C58, bad-C59, bad-C60, bad-C61, bad-C62, bad-C63, bad-C64, bad-C65, bad-C66, bad-C67, bad-C68, bad-C69, bad-C70, bad-C71, bad-C72, bad-C73, bad-C74, bad-C75, bad-C76, bad-C77, bad-C78, bad-C79, bad-C80, bad-C81, bad-C82, bad-C83
- naive_regex (104): bad-A05, bad-A06, bad-A07, bad-A08, bad-A09, bad-A10, bad-A12, bad-A15, bad-A16, bad-A17, bad-A18, bad-A19, bad-A20, bad-A25, bad-A26, bad-A27, bad-A28, bad-A33, bad-A34, bad-A37, bad-A38, bad-B05, bad-B06, bad-B07, bad-B08, bad-B09, bad-B10, bad-B11, bad-B12, bad-B18, bad-B22, bad-B23, bad-B24, bad-B25, bad-B28, bad-B29, bad-B30, bad-B34, bad-A47, bad-A48, bad-A50, bad-A51, bad-A56, bad-A57, bad-A58, bad-A61, bad-A62, bad-A63, bad-A64, bad-A65, bad-A66, bad-B42, bad-B43, bad-B44, bad-B45, bad-B47, bad-B50, bad-B51, bad-B52, bad-B53, bad-B54, bad-B56, bad-C08, bad-C09, bad-C10, bad-C20, bad-C21, bad-C24, bad-C26, bad-C28, bad-C29, bad-C30, bad-C31, bad-C32, bad-C34, bad-C35, bad-C37, bad-C39, bad-C40, bad-C41, bad-C42, bad-C43, bad-C44, bad-C45, bad-C46, bad-C47, bad-C48, bad-C49, bad-C50, bad-C51, bad-C52, bad-C53, bad-C60, bad-C61, bad-C62, bad-C63, bad-C67, bad-C73, bad-C74, bad-C75, bad-C77, bad-C78, bad-C82, bad-C83
- guard (0): none
- broken_guard (8): bad-C25, bad-C26, bad-C27, bad-C28, bad-C29, bad-C33, bad-C34, bad-C36

### known_good
- no_guard (0): none
- naive_regex (28): good-014, good-015, good-024, good-025, good-026, good-031, good-036, good-037, good-048, good-068, good-070, good-071, good-084, good-085, good-086, good-087, good-096, good-136, good-139, good-C29, good-C54, good-C55, good-C56, good-C57, good-C59, good-C60, good-C61, good-C62
- guard (0): none
- broken_guard (0): none

### residual
- no_guard (54): res-01, res-02, res-03, res-04, res-05, res-06, res-07, res-08, res-09, res-10, res-11, res-12, res-13, res-14, res-15, res-16, res-17, res-18, res-19, res-20, res-21, res-22, res-23, res-24, res-25, res-26, res-27, res-28, res-29, res-30, res-31, res-32, res-33, res-34, res-35, res-36, res-37, res-38, res-39, res-40, res-41, res-42, res-43, res-44, res-45, res-46, res-47, res-48, res-49, res-50, res-51, res-52, res-53, res-54
- naive_regex (36): res-03, res-06, res-07, res-08, res-10, res-15, res-16, res-18, res-19, res-20, res-21, res-22, res-23, res-24, res-27, res-28, res-29, res-30, res-31, res-32, res-33, res-39, res-41, res-42, res-43, res-44, res-45, res-46, res-47, res-48, res-49, res-50, res-51, res-52, res-53, res-54
- guard (54): res-01, res-02, res-03, res-04, res-05, res-06, res-07, res-08, res-09, res-10, res-11, res-12, res-13, res-14, res-15, res-16, res-17, res-18, res-19, res-20, res-21, res-22, res-23, res-24, res-25, res-26, res-27, res-28, res-29, res-30, res-31, res-32, res-33, res-34, res-35, res-36, res-37, res-38, res-39, res-40, res-41, res-42, res-43, res-44, res-45, res-46, res-47, res-48, res-49, res-50, res-51, res-52, res-53, res-54
- broken_guard (54): res-01, res-02, res-03, res-04, res-05, res-06, res-07, res-08, res-09, res-10, res-11, res-12, res-13, res-14, res-15, res-16, res-17, res-18, res-19, res-20, res-21, res-22, res-23, res-24, res-25, res-26, res-27, res-28, res-29, res-30, res-31, res-32, res-33, res-34, res-35, res-36, res-37, res-38, res-39, res-40, res-41, res-42, res-43, res-44, res-45, res-46, res-47, res-48, res-49, res-50, res-51, res-52, res-53, res-54

### holdout
- no_guard (24): H01, H02, H03, H04, H05, H06, H07, H08, H09, H10, H11, H12, H13, H14, H15, H16, H17, H18, H19, H20, H21, H22, H23, H24
- naive_regex (23): H02, H03, H05, H06, H07, H08, H09, H10, H11, H12, H13, H16, H17, H19, H20, H21, H22, H23, H24, H28, H38, H39, H40
- guard (2): H15, H48
- broken_guard (2): H15, H48

### holdout2
- no_guard (39): G01, G02, G03, G05, G06, G07, G08, G09, G10, G11, G12, G13, G14, G15, G16, G17, G18, G19, G20, G21, G22, G23, G24, G25, G26, G27, G28, G29, G30, G31, G32, G33, G34, G35, G36, G37, G38, G39, G40
- naive_regex (38): G03, G05, G06, G07, G08, G09, G10, G11, G13, G14, G15, G16, G17, G19, G20, G22, G24, G25, G26, G27, G28, G29, G30, G31, G32, G33, G34, G35, G37, G38, G39, G40, G41, G49, G50, G54, G58, G60
- guard (20): G03, G06, G11, G12, G13, G14, G15, G16, G17, G18, G19, G22, G23, G25, G26, G27, G28, G29, G30, G39
- broken_guard (21): G03, G06, G08, G11, G12, G13, G14, G15, G16, G17, G18, G19, G22, G23, G25, G26, G27, G28, G29, G30, G39

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
- `res-34` (residual, policy C): `"bash -c 'git reset --hard'"`
- `res-35` (residual, policy C): `"eval 'git push --force'"`
- `res-36` (residual, policy C): `"echo origin | xargs git push --force"`
- `res-37` (residual, policy C): `"G=git; $G reset --hard"`
- `res-38` (residual, policy C): `"if true; then git reset --hard; fi"`
- `res-39` (residual, policy C): `"git reset \\\n--hard"`
- `res-40` (residual, policy C): `"git -c alias.nuke='reset --hard' nuke"`
- `res-41` (residual, policy C): `"git checkout -f main"`
- `res-42` (residual, policy C): `"git switch --discard-changes main"`
- `res-43` (residual, policy C): `"git push origin :old-branch"`
- `res-44` (residual, policy C): `"git push --delete origin old-branch"`
- `res-45` (residual, policy C): `"git push --mirror"`
- `res-46` (residual, policy C): `"git branch -f main HEAD~5"`
- `res-47` (residual, policy C): `"git stash clear"`
- `res-48` (residual, policy C): `"git reflog expire --expire=now --all"`
- `res-49` (residual, policy C): `"git -c clean.requireForce=false clean -d"`
- `res-50` (residual, policy C): `"git checkout -- src/.."`
- `res-51` (residual, policy C): `"git restore ':(top)'"`
- `res-52` (residual, policy C): `"git rm -rf ."`
- `res-53` (residual, policy C): `"rm -rf .git"`
- `res-54` (residual, policy C): `"git worktree remove --force ../wt"`
- `H15` (holdout, policy A): `"bash -c 'git add -A'"`
- `H48` (holdout, policy B): `"git config --unset core.hooksPath"`
- `G03` (holdout2, policy C): `"git checkout dev -- some/file\ngit reset \\\n  --hard dev\ngit status --short"`
- `G06` (holdout2, policy B): `"git commit --no-ver\"\"ify -m \"wip\""`
- `G11` (holdout2, policy C): `"git${IFS}reset${IFS}--hard"`
- `G12` (holdout2, policy B): `"git$IFScommit$IFS--no-verify$IFS-m$IFSwip"`
- `G13` (holdout2, policy A): `"git add$IFS-A"`
- `G14` (holdout2, policy C): `"git push${IFS}-f${IFS}origin${IFS}main"`
- `G15` (holdout2, policy C): `"F='--hard'; git reset $F HEAD~2"`
- `G16` (holdout2, policy C): `"git reset $MODE HEAD~1"`
- `G17` (holdout2, policy A): `"git add $TARGETS"`
- `G18` (holdout2, policy C): `"$(echo git) reset --hard"`
- `G19` (holdout2, policy C): `"git $(echo reset) --hard HEAD"`
- `G22` (holdout2, policy C): `"git push $(echo --force) origin main"`
- `G23` (holdout2, policy C): `"`echo git` clean -fd"`
- `G25` (holdout2, policy C): `"echo Z2l0IHJlc2V0IC0taGFyZA== | base64 -d | sh"`
- `G26` (holdout2, policy A): `"echo Z2l0IGFkZCAtQQ== | base64 --decode | bash"`
- `G27` (holdout2, policy C): `"bash -c \"$(echo Z2l0IHB1c2ggLS1mb3JjZSBvcmlnaW4gbWFpbg== | base64 -d)\""`
- `G28` (holdout2, policy B): `"eval \"$(printf %s Z2l0IGNvbW1pdCAtLW5vLXZlcmlmeSAtbSB3aXA= | base64 -d)\""`
- `G29` (holdout2, policy C): `"printf '67697420636c65616e202d6664' | xxd -r -p | sh"`
- `G30` (holdout2, policy C): `"echo 'tvg erfrg --uneq' | tr 'a-zA-Z' 'n-za-mN-ZA-M' | sh"`
- `G39` (holdout2, policy B): `"git -c core.hookspath=/dev/null commit -m wip"`

## Checks

- guard.py reason names the policy's guard on 248 of 248 blocked violations.
- Residual cases guard.py still allows as documented: 54 of 54.
- Negative control, the one changed line:
  - guard.py: `elif a.startswith("-") and not a.startswith("-e") and "f" in a[1:]:`
  - broken_guard.py: `elif a.startswith("-") and not a.startswith("-e") and a == "-f":  # DEFECT (negative control): only a lone -f is seen; -fd, -df, -xdf slip through`

Blind to: shell state (variables, aliases, globs), wrappers (`bash -c`, `eval`, `xargs`), scripts and interpreters that call git, git config that changes a command's meaning (aliases, clean.requireForce), tools other than Bash, and everything outside the command text. Nothing is executed. The residual set lists shapes in each class.

## Exit conditions

- PASS: guard.py has zero errors on known_good and known_bad (0 errors)
- PASS: broken_guard.py has at least one error (negative control) (8 errors)
- PASS: guard.py hook form agrees with decide() on every case (0 of 582 differ)
- PASS: broken_guard.py differs from guard.py by exactly one line (1 changed lines)

OVERALL: PASS
