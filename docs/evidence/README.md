# docs/evidence

The files that `results/recorded/*.json` and `results/NUMBERS.json` cite as sources. Each recorded number names its file and the file's sha256, and `bench.py` re-hashes every one it finds here on each run. Files are copied byte for byte from where they were made. None is edited after the fact.

| folder or file | what it holds |
|---|---|
| `baselines_holdout19/` | The 2026-10-15 baselines on the blind set: the Haiku judge, the Claude Code permission rules and the plain regex. Scripts, every judge reply, every verdict and the score output. Its own README says how it was run. |
| `baselines_2026-10-14/` | The 2026-10-14 baselines on the development sets (holdout17, holdout18's seven round 1 and 2 files, the public incidents), with the same scripts. `RESULTS_BASELINES.md` is that run's write-up. The commands are the public cases in `cases/`. The Claude Code permissions page the rules were written from is cited by URL in the scripts and not copied here. |
| `scores_2026-10-14/` | The score outputs the bench reproduces: `h19_v14.txt` and `h19_v13.txt` (holdout19), and `outside_out.txt` (holdout18 and the incidents). |
| `h19verify/` | The scripts and raw JSON behind `VERIFY_H19.md`: the classification of the 11 holdout19 errors, the write-jail runs and the undo runs. They expect a scratch copy of this repo next to them. |
| `VERIFY_H19.md`, `JAIL_LABELS.md` | The label audits, as written. |
| `real_traffic_labels/` | Rater 2's method: `r2labels.py` holds the 87 rows it named by hand, each with a short reason, and `r2write.py` is the script that marked every other row safe. The rows are indexes into a private sample. The commands are one person's real agent traffic and are not published, so only these files and the counts in `results/recorded/real_traffic_labels.json` are here. |

Two words in the audit files are working labels, not terms of art. "G34" marks a result that depends on the machine's tools, for example BSD `sed -i` against GNU `sed -i`, or a program that is not installed. "Scratchpad h19verify/" was the private working folder that `h19verify/` above was copied from.
