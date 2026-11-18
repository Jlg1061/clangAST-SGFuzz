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

## Team contributions

Jose Luis Gonzalez Paniagua implemented and verified the AST detector,
copy-only instrumenter, regression and real-project runners, and their raw
evidence. Will D'Andrade developed the project framing and evaluation idea,
wrote and integrated the report, and reviewed the experimental interpretation
and deliverable. Both authors reviewed the final source and evidence.

## Final-project regression controls

Codex helped add the C replay harness, pre-registered control plan, runner,
and derivation script. The authors verified this work with shell syntax and
Python compilation checks, the nine-check AST integration suite, direct review
of the raw compiler/replay logs, and the successful complete control run at
`raw/regression-controls-20261114T164000Z/index.json`. The derived result is
`derived/regression-controls-20261114T164000Z.md`. The two retained setup
failures and the derivation-parser failure are documented in `raw/README.md`;
they were not omitted or treated as successful measurements.

## Final-project real-project static audit

Codex helped add compilation-database handling, freeze the IXWebSocket and H2O
translation-unit lists, and implement the static-audit runner and derivation.
The authors verified the change with `python3 -m py_compile`, the nine-check
AST integration suite, a CMake-backed H2O single-unit check, and the completed
fresh audit at `raw/real-project-static-audit-20261114T173000Z/index.json`.
The first retained attempt exposed a stderr-pipe capture stall; the diagnosis,
safe target-external fix, and superseded raw directory are documented in
`raw/real-project-static-audit-20261114T170000Z/RUN_STOPPED.md`. The static
counts are explicitly interpreted only as candidate-discovery and parse-
coverage evidence, not as fuzzing effectiveness or semantic ground truth.

## Final-project Stage A feasibility pilot

Codex helped create the pre-registered Stage A plan and its copied-source
runner/derivation scripts. The authors verified the scripts with Python
compilation and the completed fresh run at
`raw/stage-a-feasibility-20261115T101000Z/index.json`. The control and AST
conditions used the same frozen 36-unit source list, harness, seeds, sanitizer
flags, runtime archive, and deterministic `-runs=0` budget. A pre-run output-
directory setup mistake was retained in the superseded
`raw/stage-a-feasibility-20261115T100000Z/` directory; the corrected run did
not alter the pinned IXWebSocket source. The result is only an end-to-end
feasibility check, not an AI-derived claim of fuzzing effectiveness.

## Sustained IXWebSocket feasibility campaign

Codex helped add the pre-registered 23-hour campaign plan and the runner that
records source integrity, commands, build output, LibFuzzer output, resource
checkpoints, and final STT counts. The authors verified the runner with Python
compilation, a completed 60-second sanitizer preflight at
`raw/ixwebsocket-long-feasibility-20261118-smoke/index.json`, and review of
its raw logs. The full campaign is retained as raw evidence only after it
completes; it is a sustained operational-feasibility check, not a performance
or bug-finding comparison.
