# AGENT_GUARD_PROFILE: a design, not built

**Status: not built, on purpose.** The brief for this setting was to add it only if it maps onto code the guard already has, with no change in behaviour at the default. One value does. The value that would answer "it blocks me too often" does not, so nothing was added to `guard.py` and there is no `AGENT_GUARD_PROFILE` today. The README says so: "There is no strictness dial to turn."

## What exists

`guard.decide_full(command)` already returns why a command got its answer, as `origin`. The README names the three kinds Floor (`block`), Reflex (`irreversible`) and Finish (`recoverable`). They are outcomes, not settings: nothing in `guard.py` reads a level. The only switches it reads are `AGENT_GUARD_UNDO` (undo points off), `AGENT_GUARD_JUDGE` (the optional model judge, off by default) and the root and store paths.

## What each kind did on blind_v20

The same 3,300 commands as the README's table (1,717 dangerous, 1,583 safe), run through `guard.py` (v26d, so seen, not blind; the page was written at v22, and its table was re-counted at v26d on 2026-11-20) with the undo layer off, the judge unset and the root pinned to `/work/repo`. `python3 tools/verdict_check.py --self-test` recomputes this table and fails if it drifts from this page or from `results/NUMBERS.json`.

| Kind | Dangerous commands | Safe commands |
|---|---:|---:|
| Floor: denied | 1,638 | 20 |
| Reflex: denied | 51 | 13 |
| Finish: allowed on an undo point | 8 | 110 |
| Plain allow | 20 | 1,440 |

The deny rows add up to the README's 1,689 of 1,717 dangerous and 33 of 1,583 safe; the 20 plain allows are its misses.

## The three profiles the steal named, and what each would need

**`standard` (the default).** Today's behaviour, byte for byte. It needs no code: it is the absence of the setting.

**`strict`: deny Finish too.** This one maps onto existing code. When the hook cannot take an undo point it already denies with the `fallback` reason that `decide_full` carries on every recoverable allow. Strict would take that branch always. At the default nothing changes. The cost is on the table above: 8 more dangerous commands denied and 110 more safe ones wrongly denied, so safe commands wrongly denied would go from 33 to 143 of 1,583 (2.1% to 9.0%). That is the opposite of what the steal wanted the setting for.

**`minimal`: Floor only.** This is the setting that answers "it blocked me too often", and it is new behaviour. Reflex exists because an undo point cannot take the command back, so letting it through means letting through something that cannot be undone. Dropping Reflex would remove 13 of the 33 false blocks and let 51 more dangerous commands through, so the misses would go from 20 to 71. Whether that trade is right is a ruling, not a naming job. It also needs a guard version of its own, because `guard.py` v22 is checked against v21 plus one named change (`tools/v22_check.py`), and any new version has to be scored on a blind set that does not exist yet (v21 and v22 have none).

## What building it would take

1. A guard version (v23) that reads the setting in `main()` and nowhere else, with the current `guard.py` (v22) first copied to `variants/guard_v22.py`, which does not exist yet.
2. A proof file like `tools/v22_check.py`: at the default, v23's verdict and origin equal v22's on every row of every set (the same assertion v22_check makes against v21), and each non-default value planted against a clean control.
3. A fresh blind set before any number about a non-default profile is published.
4. New numbers added to `tools/SURFACE_MAP.json` and `results/NUMBERS.json`.

## Recommendation

Do not build `minimal`. The 13 Reflex false blocks are the lever: each is a safe command the guard denied because part of it could not be read and an undo point cannot take that part back, and fixing a class at a time is what v14 to v22 did. A dial would hide those 13 behind a setting, and would let 51 dangerous commands through to do it. If a user-facing way to relax the guard is wanted anyway, it is a decision for the owner of the repo, made with the table above in front of him.
