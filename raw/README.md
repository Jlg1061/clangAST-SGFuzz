# Final-project raw evidence

The completed regression-control experiment is
`regression-controls-20261114T164000Z/`. Its `index.json` connects each
pre-registered case to the raw regex and AST run directory; the corresponding
derived table is `../derived/regression-controls-20261114T164000Z.md`.

The other `regression-controls-*` directories are retained setup evidence:

- `20261114T000000Z` records the initial C link failure: the C compiler was
  incorrectly asked to link the C++ SGFuzz runtime.
- `20261114T162000Z` records the initial anonymous-C harness assertion: its
  fuzzer entry point returned the test function's nonzero value instead of the
  required zero.
- `20261114T163000Z` records a result-derivation parser failure after all five
  controls completed; the parser was corrected to search the complete
  LibFuzzer status line, and the full suite was rerun successfully.

These failures are implementation/setup diagnostics, not evidence about the
relative fuzzing effectiveness of regex and AST instrumentation.

The completed real-project static audit is
`real-project-static-audit-20261114T173000Z/`. Its `index.json` pins both
target commits, lists and hashes the frozen translation-unit scopes, and
connects the raw manifests to
`../derived/real-project-static-audit-20261114T173000Z.md`. The H2O raw folder
also retains the fresh out-of-tree CMake configuration and the exact
`compile_commands.json` used for every selected translation unit.

`real-project-static-audit-20261114T170000Z/` is the intentionally retained
superseded attempt. `RUN_STOPPED.md` records the diagnosis of the analyzer's
stderr-pipe capture stall. It is setup evidence only, not a result.

The completed Stage A feasibility pilot is
`stage-a-feasibility-20261115T101000Z/`. Its index connects the pre-registered
inputs and expected tuples to the control and AST copied-source build/replay
logs; the derived table is
`../derived/stage-a-feasibility-20261115T101000Z.md`. The preceding
`stage-a-feasibility-20261115T100000Z/` directory is retained setup evidence;
its `RUN_SUPERSEDED.md` explains the safely rejected output-directory mistake.
