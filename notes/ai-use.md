# Material AI use and verification

Codex was used to help inspect the baseline matcher, draft and implement the
two new Python tools and shell scripts, organize preliminary evidence, and
draft prior project documentation. The authors reviewed the resulting source
and retained only claims checked by local evidence. The historical checks are:

- syntax checks: `bash -n scripts/*.sh` and `python3 -m py_compile src/*.py scripts/*.py`;
- mechanism checks: `preliminary/raw/ast-fidelity-regression-20261023T213245Z/summary.json` (nine passed checks);
- execution checks: the sanitizer-enabled fixed-seed replay logs under `preliminary/raw/`;
- integrity checks: before/after SHA-256 records for the upstream primary
  source; and
- calculation check: `python3 preliminary/scripts/derive_prototype_comparison.py` against the historical evidence layout.

The authors remain responsible for the scope, interpretation, and final
submission. AI was not used as evidence in place of a command, log, source
file, or calculation. Future final-project experiments will record their
commands and raw output under `raw/` and update this disclosure if material
AI assistance is used.

## Final-project regression controls

Codex helped add the C replay harness, pre-registered control plan, runner,
and derivation script. The authors verified this work with shell syntax and
Python compilation checks, the nine-check AST integration suite, direct review
of the raw compiler/replay logs, and the successful complete control run at
`raw/regression-controls-20261114T164000Z/index.json`. The derived result is
`derived/regression-controls-20261114T164000Z.md`. The two retained setup
failures and the derivation-parser failure are documented in `raw/README.md`;
they were not omitted or treated as successful measurements.
