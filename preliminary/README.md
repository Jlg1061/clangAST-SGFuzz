# Preliminary evidence

This directory preserves the curated evidence gathered during the earlier
prototype work so that the implementation's origin and initial mechanism
checks remain auditable.

It includes deterministic fixture replays, the IXWebSocket and H2O build/smoke
checks, the early failed filtered-AST attempt, and a one-fixture preprocessing
cost measurement. These are not a final randomized fuzzing evaluation:

- fixed `-runs=0` replays demonstrate callback and STT behavior only;
- the IXWebSocket harness directly drives `setReadyState`, so it is not a
  protocol-fuzzing effectiveness benchmark;
- the H2O smoke executes one fixed input and establishes build/runtime safety,
  not coverage, throughput, or bug-finding performance;
- some entries pre-date this repository import and therefore retain their
  original absolute command paths.

`raw/` contains unedited logs and manifests. `derived/` is an historical table
derived from those logs. The table's older callback counts are not final values
for the current tree; new final-project measurements must be written under the
repository-root `raw/` directory with their own commands and derivation script.

`notes/` retains the original prediction and decision record for provenance.
The historical table can be regenerated with
`python3 preliminary/scripts/derive_prototype_comparison.py` from the
repository root.
