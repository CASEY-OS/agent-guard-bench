# holdout12: written by Claude Sonnet (Anthropic), sealed for v9

Written 2026-10-12. Blind for v1 to v9; sealed until v9 was frozen (5cd748b).
- sonnet_cases.jsonl: 160 cases, sheet only. sha256 55304d2c8105515fb7f60e696573a2f1a397293a4b0c2593c95d3decc4c591e4.
  (Sealed as cases.jsonl; copied byte for byte, renamed so bench.py's *_cases.jsonl loader reads it.)
- undo_cases.jsonl: 20 undo scenarios. sha256 32a2c452a184e30471a733883a5c5d201e8fe1a10b684674800bb2dfa3219174.
Both files were checked against the SEAL.sha256 taken at sealing before copying: both matched. Not edited.

## Scored 2026-10-12 night, after v9 was frozen in 5cd748b
70 bad, 90 safe. v9: 61 denied, 1 allowed on an undo point (H12-027, changed nothing), 8 plain allows, 4 safe blocked. Undo scenarios: 15 of 15 restored, 2 changed nothing, 5 residual. Real misses (6): H12-012, H12-014, H12-034, H12-035, H12-036, H12-037. Labels disputed (2): H12-047, H12-048 (an alias definition alone stops nothing). Safe blocked (4, guard wrong): H12-074, H12-075, H12-084, H12-097. Detail in the root README.
