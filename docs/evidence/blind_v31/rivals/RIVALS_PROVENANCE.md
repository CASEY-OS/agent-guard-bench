# RIVALS_PROVENANCE: what was fetched, from where, and what was checked (2026-11-23)

Nothing below was executed. Each rival was downloaded and unpacked only; its hash was read, its source text was read. No rival binary or rival JS has been started by whoever prepared this folder.

## dcg (Destructive Command Guard)

| | |
|---|---|
| Repo | https://github.com/Dicklesworthstone/destructive_command_guard (6,378 stars on 2026-11-23; the 6,155 in ANSWERS A102 on 2026-10-12 is the same repo) |
| Version | v0.17.1 ("Latest"), published 2026-11-23T14:59:13Z, tag object aa58b4dc786afe3904736e26b4ad0ab5ddddc369 |
| License | GitHub reports NOASSERTION (not a plain SPDX id); nothing here redistributes it |
| Asset | dcg-aarch64-apple-darwin.tar.xz, 6,388,148 bytes |
| URL | https://github.com/Dicklesworthstone/destructive_command_guard/releases/download/v0.17.1/dcg-aarch64-apple-darwin.tar.xz |
| Archive sha256 | a096296cf64e813a82c911717c9b2d4b252a78583539ac472401409d16bd9be9 |
| Where that hash was read from (4 routes, all equal) | the GitHub release API `digest` field; the release's `.sha256` file; the release's `SHA256SUMS` file; `shasum -a 256` of the downloaded file |
| Extracted binary | dcg/dcg, Mach-O 64-bit arm64, 26,565,648 bytes, sha256 881953634ec7e040bb6574a02b72f5f6b374e431bb06d528121437ed7de6c57d (pinned in RIVAL_PINS) |
| Not done | the release's `.minisig` signatures were downloaded to dl_dcg/ but NOT verified (minisign is not installed here; the signing key is in dcg's README, line "RWSoYi6N..."). The sha256 routes above all come from the same GitHub release, so they prove the download is intact, not who made it |

Hook invocation (from dcg's README): the hook command is the bare binary path with no arguments; the payload comes on stdin; an allowed command prints nothing, a block prints `hookSpecificOutput.permissionDecision` = deny (or ask). Default policy with no config file: packs core.filesystem, core.git and system.disk. Strings in the binary show an update check and a self-heal of the hook (`DCG_NO_UPDATE_CHECK`, `DCG_NO_SELF_HEAL`); the scorer sets both to 1 and also runs every guard with no network at all (sandbox-exec). `DCG_HOOK_TIMEOUT_MS=10000` raises dcg's 1 s evaluation deadline so that machine load cannot turn an allow into an "ask"; that is the only setting changed, and it changes timing, not rules.

## cc-safety-net

| | |
|---|---|
| Repo | https://github.com/kenryu42/cc-safety-net (MIT, 2,096 stars) |
| Version | 2.8.3 (npm `latest`), published 2026-11-23T17:13:19Z; GitHub release v2.8.3 at 17:09:34Z |
| URL | https://registry.npmjs.org/cc-safety-net/-/cc-safety-net-2.8.3.tgz |
| Tarball sha256 | 7b0103f509f7057eaf7cd1f0a944893732f122e8cffd9be3667de8559ac5eee2 (694,523 bytes) |
| Registry integrity | sha512-nR4jTWOMpSgdrrhBMjEmQLXDX+GVMQdnHqW3CBJTOgktQu+JnuA/3k6+pQ7OhPIzzuWU23HXVudYnTWVubJ4wA== (recomputed from the downloaded tarball: equal); registry shasum 1ede8e2aeeddb0087fa8be55cd31855bda6eac36 (recomputed sha1: equal) |
| Install | `npm pack cc-safety-net@2.8.3 --ignore-scripts` (dl_ccsn/), then `npm install --ignore-scripts --no-audit --no-fund --prefix ./ccsn cc-safety-net@2.8.3` -> "added 1 package". No dependencies; no preinstall/install/postinstall/prepare script in package.json |
| Installed tree | 26 files; tree hash (sha256 of the sorted "path file-sha256" lines) 80285c1e2abf2e72fbfdc0693da6eb0223a030c791f969586d506c65a06b4ded (pinned in RIVAL_PINS) |
| Hook files | dist/bin/cc-safety-net.js sha256 2c417307b1fbe5fa9f7b338d41c197ea78814d2bb21c999c38fec739fe7b6143 (a 355-byte launcher that `require`s ./hook.js); dist/bin/hook.js sha256 04a6266c78d14032d2983b4b9bba6beefad3ad34d0b23b075c6ff55bd3a42dee |

What was read in hook.js (text only): the only child-process use is `git` at fixed paths (/usr/bin/git, /usr/local/bin/git, /opt/homebrew/bin/git); there is no fetch, http or https module in the hook bundle; the URL strings in it are test text (an uploads.example.com example and the AWS metadata address inside rule examples). `hook --claude-code` is now a legacy spelling of `hook --coding-cli` (both accepted); the scorer uses the current one. Level is chosen by `CC_SAFETY_NET_LEVEL` = standard | strict | paranoid (the same variable the 10/12 script used). When the payload has no `permission_mode` (this scorer sends none), a command that standard mode cannot verify is denied; in a live default-mode session it would be "ask". Both count as a stop here. The audit log goes to $HOME/.cc-safety-net/logs, inside the throwaway home.

## Our guard

~/agent-guard-bench/guard.py, v30, sha256 08bf8c61aa7a6462a2f3aadefdc865ccb0d1f47cbf60aebf012581532721f887 (equal to the sha256 in docs/evidence/blind_v31/SEAL_GUARDS.md and SCORES.json; asserted in full, not only the 08bf8c61 prefix). Set: blind_v31_set.jsonl sha256 dbac99f83e61e3e872fbf5028706be76a17633351cf95358910c06e8498bfed8, equal to LOCK.txt (checked by the scorer before every run).

## What changed since the 2026-10-12 run (ANSWERS A102)

The only saved output of the 10/12 harness (~/agent-guard-bench-dev6/rivals/rival_scores.json) covers one set, holdout7: 110 rows (65 dangerous, 45 safe). On it dcg stopped 21 of 65, cc-safety-net standard 20, strict 21, paranoid 22, our v6 65 of 65; false stops dcg 7 of 45, standard 3, strict 4, paranoid 7, ours 1. ANSWERS A102 says "the same blind sets" and "20 to 42%"; the script's own header says "all 6 blind sets" but its `SETS` list is `["holdout7"]`, so only that one set is on disk. This run is the 2,429-row blind_v31 set (1,124 dangerous, 1,305 safe), current rival releases, and our v30. The two are not comparable row for row.
