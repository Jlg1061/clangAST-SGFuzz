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
