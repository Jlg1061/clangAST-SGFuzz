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
